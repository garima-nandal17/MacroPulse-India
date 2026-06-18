"""
sensitivity_engine.py — MacroPulse India, Day 7 (Sector Sensitivity Engine)

The reusable service layer that the Industry Impact Panel, What-if Simulator, and
AI Briefing Engine all depend on. It reads the materialized betas (sensitivity_results)
and correlations (correlation_results) from TiDB and exposes a clean query/projection API.

Key method — project_impact(shocks): the analytical core of the What-if Simulator.
Given hypothetical macro factor shocks, it returns each asset's expected response as
  response_asset = Σ_factor  beta[asset, factor] * shock[factor]
optionally restricting to statistically significant betas.

Usage (downstream):
    eng = SensitivityEngine()
    eng.factor_view("CPI_chg")                     # Impact Panel: who moves with inflation
    eng.project_impact({"CPI_chg": 0.005})         # What-if Simulator: +0.5% MoM CPI shock
    eng.sector_view("BankNifty_ret")               # AI Briefing: one asset's macro exposure
"""
from __future__ import annotations

import logging

import pandas as pd

from fetch_daily import get_connection

log = logging.getLogger("sensitivity_engine")


def _query_df(conn, sql):
    cur = conn.cursor()
    cur.execute(sql)
    cols = [c[0] for c in cur.description]
    rows = cur.fetchall()
    cur.close()
    return pd.DataFrame(rows, columns=cols)


class SensitivityEngine:
    def __init__(self, conn=None):
        self._own = conn is None
        self._conn = conn or get_connection()
        self.betas = _query_df(self._conn, "SELECT * FROM sensitivity_results")
        try:
            self.corrs = _query_df(self._conn, "SELECT * FROM correlation_results")
        except Exception:
            log.warning("correlation_results not found — run correlation_matrix.py.")
            self.corrs = pd.DataFrame()
        for df in (self.betas, self.corrs):
            for col in ("beta", "pvalue", "corr"):
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")

    # ---- views -----------------------------------------------------------------
    def sector_view(self, asset, freq="daily"):
        """One asset's sensitivity to every macro factor (beta + significance)."""
        b = self.betas[(self.betas.asset == asset) & (self.betas.freq == freq)]
        return b[["factor", "beta", "pvalue", "r2", "n"]].sort_values("pvalue").reset_index(drop=True)

    def factor_view(self, factor, freq="daily"):
        """Every asset's sensitivity to one macro factor — the Industry Impact Panel input."""
        b = self.betas[(self.betas.factor == factor) & (self.betas.freq == freq)]
        return b[["asset", "beta", "pvalue", "r2", "n"]].sort_values(
            "beta", ascending=False).reset_index(drop=True)

    def correlation_matrix(self, freq="daily", method="pearson"):
        c = self.corrs[(self.corrs.freq == freq) & (self.corrs.method == method)]
        if c.empty:
            return pd.DataFrame()
        return c.pivot(index="asset", columns="factor", values="corr")

    # ---- projection (What-if Simulator core) -----------------------------------
    def project_impact(self, shocks: dict, freq="daily", significant_only=True, alpha=0.10):
        """Expected per-asset response to hypothetical macro shocks.

        shocks: {factor_name: shock_value} in the factor's own units
                (e.g. {"CPI_chg": 0.005} = +0.5% MoM CPI; {"Unemployment_chg": 0.2} = +0.2pp UR).
        Returns a DataFrame [asset, projected_response] sorted desc. Response units match
        each asset's transform (log return for _ret, Δ for _diff).
        """
        b = self.betas[(self.betas.freq == freq) & (self.betas.factor.isin(shocks))].copy()
        if b.empty:
            return pd.DataFrame(columns=["asset", "projected_response"])
        if significant_only:
            b.loc[b.pvalue > alpha, "beta"] = 0.0
        b["contrib"] = b.apply(lambda r: r["beta"] * shocks[r["factor"]], axis=1)
        out = (b.groupby("asset")["contrib"].sum()
               .reset_index().rename(columns={"contrib": "projected_response"}))
        return out.sort_values("projected_response", ascending=False).reset_index(drop=True)

    def top_drivers(self, asset, freq="daily", alpha=0.10, n=3):
        """The strongest *significant* macro drivers of one asset (for briefings)."""
        b = self.betas[(self.betas.asset == asset) & (self.betas.freq == freq)
                       & (self.betas.pvalue <= alpha)].copy()
        b["abs_beta"] = b["beta"].abs()
        return b.sort_values("abs_beta", ascending=False).head(n)[
            ["factor", "beta", "pvalue"]].reset_index(drop=True)

    def close(self):
        if self._own and self._conn is not None:
            self._conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
    eng = SensitivityEngine()
    log.info("Industry Impact Panel — factor_view('CPI_chg'):\n%s",
             eng.factor_view("CPI_chg").to_string(index=False))
    log.info("What-if Simulator — project_impact({'CPI_chg': 0.005}):\n%s",
             eng.project_impact({"CPI_chg": 0.005}).to_string(index=False))
    eng.close()