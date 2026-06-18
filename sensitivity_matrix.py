"""
sensitivity_matrix.py — MacroPulse India, Day 6 (sector sensitivity matrix)

Estimates how sensitive each asset's return is to each macro factor, on the
stationary analysis_daily layer.

Method:
  - Univariate OLS  r_i = a + b * m_j + e  per (asset, factor).
  - DAILY frequency: Newey-West/HAC standard errors (maxlags=HAC_MAXLAGS), because
    the held-constant macro factor is a step function with strong serial correlation,
    which would otherwise inflate t-stats.
  - MONTHLY frequency: aggregate returns to month-end and re-estimate with ordinary
    OLS (~13 low-autocorrelation obs) as a robustness cross-check.
  - Univariate (not joint) to keep collinear macro factors interpretable.

Interpretation: betas are conditional associations with the prevailing macro regime
(state encoding), HAC-corrected — not causal impact multipliers.

Asset columns  = analysis_daily columns ending in _ret or _diff.
Factor columns = columns ending in _chg.

Output: long table `sensitivity_results` (freq, asset, factor, beta, std_err, tstat,
pvalue, r2, n), full-refreshed. Also prints a human-readable beta matrix.

Env:
  DB_* connection vars (via fetch_daily.get_connection)
  DRY_RUN=1 -> compute and print, write nothing
"""
from __future__ import annotations

import logging
import os
import sys

import numpy as np
import pandas as pd
import statsmodels.api as sm
from mysql.connector import Error as MySQLError

from fetch_daily import get_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("sensitivity")

RESULT_TABLE = "sensitivity_results"
HAC_MAXLAGS = 21          # ~1 trading month, matches the macro holding period
MIN_OBS = 10              # skip regressions with too few aligned points
DRY_RUN = os.getenv("DRY_RUN") == "1"


def _query_df(conn, sql):
    cur = conn.cursor()
    cur.execute(sql)
    cols = [c[0] for c in cur.description]
    rows = cur.fetchall()
    cur.close()
    return pd.DataFrame(rows, columns=cols)


def _regress(y, x, hac):
    """Univariate OLS; HAC errors if hac else ordinary. Returns dict or None."""
    d = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
    if len(d) < MIN_OBS or d["x"].std() == 0 or d["y"].std() == 0:
        return None
    X = sm.add_constant(d["x"])
    fit = (sm.OLS(d["y"], X).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_MAXLAGS})
           if hac else sm.OLS(d["y"], X).fit())
    return {"beta": fit.params["x"], "std_err": fit.bse["x"], "tstat": fit.tvalues["x"],
            "pvalue": fit.pvalues["x"], "r2": fit.rsquared, "n": int(len(d))}


def compute(df, assets, factors, freq, hac):
    rows = []
    for a in assets:
        for f in factors:
            res = _regress(df[a], df[f], hac)
            if res is None:
                log.warning("%-7s %-22s x %-18s skipped (too few obs / no variance).",
                            freq, a, f)
                continue
            rows.append({"freq": freq, "asset": a, "factor": f, **res})
    return rows


def to_monthly(df, assets, factors):
    m = df.set_index(pd.to_datetime(df["date"])).drop(columns=["date"])
    agg = {a: "sum" for a in assets}            # log returns / diffs are additive
    agg.update({f: "last" for f in factors})    # prevailing macro change in the month
    return m.resample("ME").agg(agg).reset_index(drop=True)


def stars(p):
    return "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""


def write_results(conn, rows):
    cur = conn.cursor()
    cur.execute(f"""CREATE TABLE IF NOT EXISTS `{RESULT_TABLE}` (
        freq VARCHAR(10), asset VARCHAR(48), factor VARCHAR(48),
        beta DOUBLE, std_err DOUBLE, tstat DOUBLE, pvalue DOUBLE, r2 DOUBLE, n INT,
        PRIMARY KEY (freq, asset, factor))""")
    cur.execute(f"TRUNCATE TABLE `{RESULT_TABLE}`")
    cur.executemany(
        f"""INSERT INTO `{RESULT_TABLE}`
            (freq, asset, factor, beta, std_err, tstat, pvalue, r2, n)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        [(r["freq"], r["asset"], r["factor"], r["beta"], r["std_err"],
          r["tstat"], r["pvalue"], r["r2"], r["n"]) for r in rows])
    conn.commit()
    cur.close()
    log.info("Wrote %d rows to %s.", len(rows), RESULT_TABLE)


def print_matrix(rows, freq):
    sub = [r for r in rows if r["freq"] == freq]
    if not sub:
        return
    df = pd.DataFrame(sub)
    df["cell"] = df.apply(lambda r: f"{r['beta']:+.4f}{stars(r['pvalue'])}", axis=1)
    mat = df.pivot(index="asset", columns="factor", values="cell")
    log.info("--- %s beta matrix (*** p<.01, ** p<.05, * p<.10) ---\n%s",
             freq, mat.to_string())


def main() -> int:
    conn = None
    try:
        conn = get_connection()
        df = _query_df(conn, "SELECT * FROM analysis_daily")
        if df.empty:
            log.error("analysis_daily is empty — run build_analysis.py first.")
            return 1
        df = df.apply(lambda c: pd.to_numeric(c, errors="coerce") if c.name != "date" else c)

        assets = [c for c in df.columns if c.endswith(("_ret", "_diff"))]
        factors = [c for c in df.columns if c.endswith("_chg")]
        log.info("assets=%s", assets)
        log.info("factors=%s", factors)

        rows = compute(df, assets, factors, "daily", hac=True)
        rows += compute(to_monthly(df, assets, factors), assets, factors, "monthly", hac=False)

        print_matrix(rows, "daily")
        print_matrix(rows, "monthly")

        if DRY_RUN:
            log.info("DRY_RUN — computed %d result rows, nothing written.", len(rows))
            return 0
        write_results(conn, rows)
        return 0
    except MySQLError as e:
        log.error("DB error: %s", e)
        return 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())