"""
correlation_matrix.py — MacroPulse India, Day 7 (sensitivity engine: correlation half)

Computes asset x macro-factor correlations on the stationary analysis_daily layer,
the companion to the HAC beta matrix. Pearson + Spearman, daily + monthly.

Asset columns  = analysis_daily columns ending in _ret or _diff.
Factor columns = columns ending in _chg.

Output: long table `correlation_results` (freq, asset, factor, method, corr, pvalue, n),
full-refreshed. Mirrors sensitivity_results so the engine can read both uniformly.

Env: DB_* (via fetch_daily.get_connection); DRY_RUN=1 -> compute & print, write nothing.
"""
from __future__ import annotations

import logging
import os
import sys

import pandas as pd
from scipy import stats
from mysql.connector import Error as MySQLError

from fetch_daily import get_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("correlation")

RESULT_TABLE = "correlation_results"
MIN_OBS = 10
DRY_RUN = os.getenv("DRY_RUN") == "1"


def _query_df(conn, sql):
    cur = conn.cursor()
    cur.execute(sql)
    cols = [c[0] for c in cur.description]
    rows = cur.fetchall()
    cur.close()
    return pd.DataFrame(rows, columns=cols)


def to_monthly(df, assets, factors):
    m = df.set_index(pd.to_datetime(df["date"])).drop(columns=["date"])
    agg = {a: "sum" for a in assets}
    agg.update({f: "last" for f in factors})
    return m.resample("ME").agg(agg).reset_index(drop=True)


def _corr(x, y, method):
    d = pd.concat([x.rename("x"), y.rename("y")], axis=1).dropna()
    if len(d) < MIN_OBS or d["x"].std() == 0 or d["y"].std() == 0:
        return None
    fn = stats.pearsonr if method == "pearson" else stats.spearmanr
    r, p = fn(d["x"], d["y"])
    return {"corr": float(r), "pvalue": float(p), "n": int(len(d))}


def compute(df, assets, factors, freq):
    rows = []
    for a in assets:
        for f in factors:
            for method in ("pearson", "spearman"):
                res = _corr(df[a], df[f], method)
                if res is None:
                    continue
                rows.append({"freq": freq, "asset": a, "factor": f, "method": method, **res})
    return rows


def write_results(conn, rows):
    cur = conn.cursor()
    cur.execute(f"""CREATE TABLE IF NOT EXISTS `{RESULT_TABLE}` (
        freq VARCHAR(10), asset VARCHAR(48), factor VARCHAR(48), method VARCHAR(12),
        corr DOUBLE, pvalue DOUBLE, n INT,
        PRIMARY KEY (freq, asset, factor, method))""")
    cur.execute(f"TRUNCATE TABLE `{RESULT_TABLE}`")
    cur.executemany(
        f"""INSERT INTO `{RESULT_TABLE}` (freq, asset, factor, method, corr, pvalue, n)
            VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        [(r["freq"], r["asset"], r["factor"], r["method"], r["corr"], r["pvalue"], r["n"])
         for r in rows])
    conn.commit()
    cur.close()
    log.info("Wrote %d rows to %s.", len(rows), RESULT_TABLE)


def main() -> int:
    conn = None
    try:
        conn = get_connection()
        df = _query_df(conn, "SELECT * FROM analysis_daily").apply(
            lambda c: pd.to_numeric(c, errors="coerce") if c.name != "date" else c)
        if df.empty:
            log.error("analysis_daily is empty — run build_analysis.py first.")
            return 1
        assets = [c for c in df.columns if c.endswith(("_ret", "_diff"))]
        factors = [c for c in df.columns if c.endswith("_chg")]

        rows = compute(df, assets, factors, "daily")
        rows += compute(to_monthly(df, assets, factors), assets, factors, "monthly")

        pear = pd.DataFrame([r for r in rows if r["method"] == "pearson" and r["freq"] == "daily"])
        if not pear.empty:
            log.info("--- daily Pearson correlation matrix ---\n%s",
                     pear.pivot(index="asset", columns="factor", values="corr").round(3).to_string())

        if DRY_RUN:
            log.info("DRY_RUN — computed %d rows, nothing written.", len(rows))
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