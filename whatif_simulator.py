"""
whatif_simulator.py — MacroPulse India, Day 9 (What-if Scenario Simulator)

Second consumer of the Sector Sensitivity Engine. Where the Impact Panel applies the
*current* macro state, the simulator applies *hypothetical* macro shocks and projects the
implied per-sector response — "if CPI rose 0.8% MoM and unemployment ticked up 0.3pp, which
sectors feel it, and how much?"

Same contract as the engine: response = Σ_factor beta[asset, factor] * shock[factor], over
statistically significant betas. Because the projection is linear, a scenario's response IS
its incremental impact over the current state — so simulate(shocks) is the marginal effect.

Decision support, not a forecast: directional, ranked, explainable.

Env: DB_* (via fetch_daily.get_connection).
"""
from __future__ import annotations

import logging
import sys

import pandas as pd

from fetch_daily import get_connection
from sensitivity_engine import SensitivityEngine
from impact_panel import SECTOR_LABELS  # single source of truth for industry targets

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("whatif_simulator")

# Predefined scenarios. Shocks are in each factor's own units:
#   CPI_chg / IIP_chg = MoM % change (decimal); Unemployment_chg / RepoRate_chg = Δ pp.
# Magnitudes are illustrative — tune to your narrative.
SCENARIOS = {
    "Inflation shock":     {"CPI_chg": 0.008},
    "Disinflation":        {"CPI_chg": -0.005},
    "Growth surge":        {"IIP_chg": 0.04},
    "Industrial slowdown": {"IIP_chg": -0.04, "Unemployment_chg": 0.3},
    "Stagflation":         {"CPI_chg": 0.008, "IIP_chg": -0.04, "Unemployment_chg": 0.3},
    "Soft landing":        {"CPI_chg": -0.003, "IIP_chg": 0.03, "Unemployment_chg": -0.1},
}


class WhatIfSimulator:
    def __init__(self, engine=None, conn=None):
        self._own = conn is None and engine is None
        self.conn = conn or (engine.__dict__.get("_conn") if engine else None) or get_connection()
        self.engine = engine or SensitivityEngine(conn=self.conn)

    def simulate(self, shocks: dict, freq="daily", alpha=0.10,
                 significant_only=True, sectors_only=True):
        """Per-asset implied response to a hypothetical scenario.

        significant_only=True (default): project only statistically significant betas —
        honest but sparse. significant_only=False: include all betas and label each row's
        `confidence` ('high' if every contributing beta is significant, else 'low'), so you
        can explore fuller coverage without mistaking noise for signal.
        """
        b = self.engine.betas
        b = b[(b.freq == freq) & (b.factor.isin(shocks))].copy()
        if significant_only:
            b = b[b.pvalue <= alpha]
        if b.empty:
            return pd.DataFrame(columns=["asset", "response", "direction",
                                         "dominant_factor", "confidence"])
        b["_sig"] = b["pvalue"] <= alpha
        b["contrib"] = b.apply(lambda r: r["beta"] * shocks[r["factor"]], axis=1)
        resp = b.groupby("asset")["contrib"].sum()
        dom_idx = b.groupby("asset")["contrib"].apply(lambda s: s.abs().idxmax())
        dom = b.loc[dom_idx.values].set_index("asset")["factor"]
        conf = b.groupby("asset")["_sig"].all().map({True: "high", False: "low"})
        out = pd.DataFrame({"asset": resp.index, "response": resp.values})
        out["direction"] = out["response"].apply(lambda x: "up" if x > 0 else "down" if x < 0 else "flat")
        out["dominant_factor"] = out["asset"].map(dom)
        out["confidence"] = out["asset"].map(conf)

        if sectors_only:
            sect = out[out["asset"].isin(SECTOR_LABELS)].copy()
            if sect.empty:
                log.warning("No sector targets yet — showing all series. Run sector enrichment.")
            else:
                sect.insert(0, "sector", sect["asset"].map(SECTOR_LABELS))
                out = sect
        return out.reindex(out["response"].abs().sort_values(ascending=False).index).reset_index(drop=True)

    def compare(self, scenarios: dict, freq="daily", sectors_only=True):
        """Side-by-side asset/sector x scenario matrix of implied responses."""
        cols = {}
        for name, shocks in scenarios.items():
            sim = self.simulate(shocks, freq=freq, sectors_only=sectors_only)
            key = "sector" if "sector" in sim.columns else "asset"
            cols[name] = sim.set_index(key)["response"]
        return pd.DataFrame(cols)

    def close(self):
        if self._own and self.conn is not None:
            self.conn.close()


def main() -> int:
    sim = None
    try:
        sim = WhatIfSimulator()
        log.info("WHAT-IF SIMULATOR — decision support, not a forecast")
        log.info("Scenario 'Stagflation' %s:\n%s", SCENARIOS["Stagflation"],
                 sim.simulate(SCENARIOS["Stagflation"]).to_string(index=False))
        log.info("Scenario comparison (implied response by scenario):\n%s",
                 sim.compare(SCENARIOS).round(5).to_string())
        return 0
    finally:
        if sim is not None:
            sim.close()


if __name__ == "__main__":
    sys.exit(main())