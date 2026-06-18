"""
impact_panel.py — MacroPulse India, Day 8 (Industry Impact Panel)

The first consumer of the Sector Sensitivity Engine. It maps the CURRENT macro state
(the latest prevailing macro changes) onto a ranked, explainable sector-impact reading:

    "Given today's macro environment, here is the implied pressure on each sector."

This is decision support, not a forecast — it re-presents the estimated sensitivities as
a current-state reading, with each sector's top drivers and confidence.

Pipeline: latest *_chg from analysis_daily  ->  engine.project_impact(state)
          + engine.top_drivers(asset) per row  ->  ranked panel.

Env: DB_* (via fetch_daily.get_connection); DRY_RUN=1 -> print only, no snapshot write.
"""
from __future__ import annotations

import logging
import os
import sys

import pandas as pd

from fetch_daily import get_connection
from sensitivity_engine import SensitivityEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("impact_panel")

SNAPSHOT_TABLE = "impact_panel_snapshot"
DRY_RUN = os.getenv("DRY_RUN") == "1"

# Industry targets the panel displays (others — Gold, US10Y, DXY, USDINR, Brent,
# IndiaVIX, Nifty50 — remain in the engine as market context, not industries).
SECTOR_LABELS = {
    "BankNifty_ret": "Banks", "NiftyIT_ret": "IT", "NiftyPharma_ret": "Pharma",
    "NiftyAuto_ret": "Auto", "NiftyFMCG_ret": "FMCG", "NiftyRealty_ret": "Realty",
    "NiftyMetal_ret": "Metals", "NiftyEnergy_ret": "Energy",
}


def _query_df(conn, sql):
    cur = conn.cursor()
    cur.execute(sql)
    cols = [c[0] for c in cur.description]
    rows = cur.fetchall()
    cur.close()
    return pd.DataFrame(rows, columns=cols)


class ImpactPanel:
    def __init__(self, conn=None):
        self._own = conn is None
        self.conn = conn or get_connection()
        self.engine = SensitivityEngine(conn=self.conn)

    def current_state(self):
        """Latest prevailing macro changes (the held-constant *_chg values)."""
        df = _query_df(self.conn, "SELECT * FROM analysis_daily ORDER BY date DESC LIMIT 1")
        if df.empty:
            return {}, None
        row = df.iloc[0]
        state = {}
        for c in df.columns:
            if c.endswith("_chg"):
                v = pd.to_numeric(pd.Series([row[c]]), errors="coerce").iloc[0]
                if pd.notna(v):
                    state[c] = float(v)
        return state, row["date"]

    def build(self, freq="daily", alpha=0.10, sectors_only=True):
        state, asof = self.current_state()
        impact = self.engine.project_impact(state, freq=freq, significant_only=True, alpha=alpha)
        rows = []
        for _, r in impact.iterrows():
            asset, resp = r["asset"], float(r["projected_response"])
            drv = self.engine.top_drivers(asset, freq=freq, alpha=alpha)
            drivers = ", ".join(f"{d['factor']} ({d['beta']:+.3f})" for _, d in drv.iterrows()) or "—"
            rows.append({"asset": asset, "implied_response": resp,
                         "direction": "up" if resp > 0 else "down" if resp < 0 else "flat",
                         "top_drivers": drivers})
        panel = pd.DataFrame(rows)
        if panel.empty:
            return panel, state, asof
        if sectors_only:
            sect = panel[panel["asset"].isin(SECTOR_LABELS)].copy()
            if sect.empty:
                log.warning("No sector targets in results yet — sector indices not ingested. "
                            "Showing all series; run sector enrichment for a true industry panel.")
            else:
                sect.insert(0, "sector", sect["asset"].map(SECTOR_LABELS))
                panel = sect
        order = panel["implied_response"].abs().sort_values(ascending=False).index
        panel = panel.loc[order].reset_index(drop=True)
        return panel, state, asof

    def factor_drilldown(self, factor, freq="daily"):
        """Who is exposed to one macro factor right now (Impact Panel drill-down)."""
        return self.engine.factor_view(factor, freq)

    def materialize(self, panel, asof, freq):
        cur = self.conn.cursor()
        cur.execute(f"""CREATE TABLE IF NOT EXISTS `{SNAPSHOT_TABLE}` (
            asof_date DATE, freq VARCHAR(10), asset VARCHAR(48),
            implied_response DOUBLE, direction VARCHAR(8), top_drivers VARCHAR(255),
            PRIMARY KEY (freq, asset))""")
        cur.execute(f"TRUNCATE TABLE `{SNAPSHOT_TABLE}`")
        cur.executemany(
            f"""INSERT INTO `{SNAPSHOT_TABLE}`
                (asof_date, freq, asset, implied_response, direction, top_drivers)
                VALUES (%s,%s,%s,%s,%s,%s)""",
            [(asof, freq, r["asset"], r["implied_response"], r["direction"], r["top_drivers"])
             for _, r in panel.iterrows()])
        self.conn.commit()
        cur.close()
        log.info("Wrote %d rows to %s (asof %s).", len(panel), SNAPSHOT_TABLE, asof)

    def close(self):
        if self._own and self.conn is not None:
            self.conn.close()


def main() -> int:
    panel_obj = None
    try:
        panel_obj = ImpactPanel()
        panel, state, asof = panel_obj.build()
        if panel.empty:
            log.error("No panel produced — check analysis_daily and sensitivity_results.")
            return 1

        log.info("INDUSTRY IMPACT PANEL  (as of %s)  — decision support, not a forecast", asof)
        log.info("Current macro state (prevailing changes): %s",
                 {k: round(v, 4) for k, v in state.items()})
        log.info("Implied sector pressure (ranked by magnitude):\n%s", panel.to_string(index=False))

        if DRY_RUN:
            log.info("DRY_RUN — snapshot not written.")
            return 0
        panel_obj.materialize(panel, asof, "daily")
        return 0
    finally:
        if panel_obj is not None:
            panel_obj.close()


if __name__ == "__main__":
    sys.exit(main())