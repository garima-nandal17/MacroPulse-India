"""
build_analysis.py — MacroPulse India, Day 6 analysis layer

Reads features_daily (levels) from TiDB, applies the stationarity transforms in
transforms.py, trims to the analysis window, and materializes `analysis_daily`
(idempotent full-refresh) — the stationary substrate for the sector-sensitivity
matrix, correlations, and modeling.

Env:
  DB_* connection vars (reused via fetch_daily.get_connection)
  DRY_RUN=1  -> print shape/head, NaN summary, stationarity sanity (+ optional ADF); write nothing
"""
from __future__ import annotations

import logging
import os
import sys

import pandas as pd
from mysql.connector import Error as MySQLError

from fetch_daily import get_connection
from transforms import build_analysis_frame, apply_window

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("build_analysis")

ANALYSIS_TABLE = "analysis_daily"
DRY_RUN = os.getenv("DRY_RUN") == "1"


def _query_df(conn, sql):
    cur = conn.cursor()
    cur.execute(sql)
    cols = [c[0] for c in cur.description]
    rows = cur.fetchall()
    cur.close()
    return pd.DataFrame(rows, columns=cols)


def stationarity_report(df):
    """Returns/diffs should have mean ~0; print basic stats and optional ADF p-values."""
    num = df.drop(columns=["date"]).apply(pd.to_numeric, errors="coerce")
    log.info("mean / std per column:\n%s",
             pd.DataFrame({"mean": num.mean(), "std": num.std()}).to_string())
    try:
        from statsmodels.tsa.stattools import adfuller
        log.info("--- ADF stationarity (p<0.05 => stationary) ---")
        for c in num.columns:
            s = num[c].dropna()
            if len(s) > 20 and s.nunique() > 2:
                log.info("  %-22s ADF p=%.4f", c, adfuller(s, autolag="AIC")[1])
    except ImportError:
        log.info("(install statsmodels for ADF p-values; skipping formal test)")


def write_table(conn, df):
    cols = [c for c in df.columns if c != "date"]
    coldefs = ", ".join(f"`{c}` DOUBLE" for c in cols)
    cur = conn.cursor()
    cur.execute(f"CREATE TABLE IF NOT EXISTS `{ANALYSIS_TABLE}` "
                f"(`date` DATE PRIMARY KEY, {coldefs})")
    cur.execute(f"SHOW COLUMNS FROM `{ANALYSIS_TABLE}`")
    existing = {r[0] for r in cur.fetchall()}
    for c in cols:
        if c not in existing:
            cur.execute(f"ALTER TABLE `{ANALYSIS_TABLE}` ADD COLUMN `{c}` DOUBLE")
    cur.execute(f"TRUNCATE TABLE `{ANALYSIS_TABLE}`")
    collist = ", ".join(f"`{c}`" for c in ["date"] + cols)
    placeholders = ", ".join(["%s"] * (len(cols) + 1))
    insert = f"INSERT INTO `{ANALYSIS_TABLE}` ({collist}) VALUES ({placeholders})"
    data = []
    for _, r in df.iterrows():
        row = [r["date"].date() if pd.notna(r["date"]) else None]
        row += [None if pd.isna(r[c]) else float(r[c]) for c in cols]
        data.append(tuple(row))
    cur.executemany(insert, data)
    conn.commit()
    cur.close()
    log.info("Wrote %d rows x %d cols to %s.", len(data), len(cols) + 1, ANALYSIS_TABLE)


def main() -> int:
    conn = None
    try:
        conn = get_connection()
        feat = _query_df(conn, "SELECT * FROM features_daily")
        if feat.empty:
            log.error("features_daily is empty — run build_features.py first.")
            return 1

        analysis = apply_window(build_analysis_frame(feat))
        log.info("analysis_daily: %d rows x %d cols  (%s -> %s)",
                 len(analysis), analysis.shape[1],
                 analysis["date"].min().date(), analysis["date"].max().date())
        stationarity_report(analysis)

        if DRY_RUN:
            log.info("DRY_RUN — not writing. Head:\n%s", analysis.head().to_string(index=False))
            log.info("NaN per column:\n%s", analysis.isna().sum().to_string())
            return 0

        write_table(conn, analysis)
        return 0
    except MySQLError as e:
        log.error("DB error: %s", e)
        return 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())