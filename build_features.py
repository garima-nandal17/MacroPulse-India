"""
build_features.py — MacroPulse India, Day 5 (intelligence layer)

Builds the POINT-IN-TIME feature table: for each daily (trading) date, attach
that day's market indicators PLUS the latest monthly macro indicator values that
were ALREADY RELEASED as of that date.

Why release_date, not period:
  April CPI has period = 2026-04-01 but release_date ≈ 2026-05-12. If we joined on
  `period`, every early-April daily row would "know" April CPI weeks before it was
  published — lookahead bias, which silently inflates every downstream correlation
  and model. We therefore merge_asof on `release_date` (direction="backward"), so a
  date only ever sees macro values that were public on or before it.

Output: a wide table `features_daily` (date PK + daily indicators + point-in-time
monthly indicators), full-refreshed each run (idempotent).

Env:
  DB_* connection vars (reused via fetch_daily.get_connection)
  DRY_RUN=1  -> print shape/head/NaN summary + lookahead audit, write nothing
"""
from __future__ import annotations

import logging
import os
import sys

import pandas as pd
from mysql.connector import Error as MySQLError

from fetch_daily import get_connection  # canonical, TLS-aware TiDB connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("build_features")

MONTHLY_INDICATORS = ["CPI", "IIP", "Unemployment", "RepoRate"]
FEATURE_TABLE = "features_daily"
DRY_RUN = os.getenv("DRY_RUN") == "1"


def _query_df(conn, sql):
    cur = conn.cursor()
    cur.execute(sql)
    cols = [c[0] for c in cur.description]
    rows = cur.fetchall()
    cur.close()
    return pd.DataFrame(rows, columns=cols)


def load_daily_wide(conn):
    """daily_indicators (long) -> wide: one row per date, one column per indicator."""
    d = _query_df(conn, "SELECT date, indicator, value FROM daily_indicators")
    if d.empty:
        return d
    wide = d.pivot_table(index="date", columns="indicator", values="value", aggfunc="last")
    wide = wide.reset_index()
    wide["date"] = pd.to_datetime(wide["date"])
    return wide.sort_values("date").reset_index(drop=True)


def load_monthly_long(conn):
    m = _query_df(conn, "SELECT indicator, value, release_date FROM monthly_indicators")
    if not m.empty:
        m["release_date"] = pd.to_datetime(m["release_date"], errors="coerce")
    return m


def build_features(daily_wide, monthly_long):
    """Attach each monthly indicator as the latest value released on/before each date."""
    feat = daily_wide.copy()
    for ind in MONTHLY_INDICATORS:
        sub = monthly_long[monthly_long["indicator"] == ind][["release_date", "value"]].copy()
        sub = sub.dropna(subset=["release_date"]).sort_values("release_date")
        # one value per release_date (latest period wins, just in case)
        sub = sub.drop_duplicates(subset=["release_date"], keep="last")
        if sub.empty:
            log.warning("%s: no rows with a release_date — column left NaN.", ind)
            feat[ind] = pd.NA
            continue
        sub = sub.rename(columns={"value": ind})
        feat = pd.merge_asof(
            feat.sort_values("date"),
            sub,
            left_on="date",
            right_on="release_date",
            direction="backward",   # only values released AT or BEFORE the date
        ).drop(columns=["release_date"])
    return feat.sort_values("date").reset_index(drop=True)


def lookahead_audit(feat, monthly_long):
    """Prove no lookahead: first non-null date of each monthly column must be
    >= that indicator's earliest release_date."""
    log.info("--- lookahead audit (first known date vs earliest release) ---")
    for ind in MONTHLY_INDICATORS:
        if ind not in feat.columns:
            continue
        known = feat.loc[feat[ind].notna(), "date"]
        first_known = known.min() if not known.empty else None
        rel = monthly_long.loc[monthly_long["indicator"] == ind, "release_date"].min()
        ok = (first_known is None) or (rel is None) or (first_known >= rel)
        log.info("  %-12s first_known=%s  earliest_release=%s  %s",
                 ind, first_known, rel, "OK" if ok else "LOOKAHEAD!")


def write_features(conn, df):
    cols = [c for c in df.columns if c != "date"]
    coldefs = ", ".join(f"`{c}` DOUBLE" for c in cols)
    cur = conn.cursor()
    cur.execute(f"CREATE TABLE IF NOT EXISTS `{FEATURE_TABLE}` "
                f"(`date` DATE PRIMARY KEY, {coldefs})")
    cur.execute(f"SHOW COLUMNS FROM `{FEATURE_TABLE}`")
    existing = {r[0] for r in cur.fetchall()}
    for c in cols:
        if c not in existing:
            cur.execute(f"ALTER TABLE `{FEATURE_TABLE}` ADD COLUMN `{c}` DOUBLE")
    cur.execute(f"TRUNCATE TABLE `{FEATURE_TABLE}`")  # derived table -> full refresh
    collist = ", ".join(f"`{c}`" for c in ["date"] + cols)
    placeholders = ", ".join(["%s"] * (len(cols) + 1))
    insert = f"INSERT INTO `{FEATURE_TABLE}` ({collist}) VALUES ({placeholders})"
    data = []
    for _, r in df.iterrows():
        row = [r["date"].date() if pd.notna(r["date"]) else None]
        row += [None if pd.isna(r[c]) else float(r[c]) for c in cols]
        data.append(tuple(row))
    cur.executemany(insert, data)
    conn.commit()
    cur.close()
    log.info("Wrote %d rows x %d cols to %s.", len(data), len(cols) + 1, FEATURE_TABLE)


def main() -> int:
    conn = None
    try:
        conn = get_connection()
        daily_wide = load_daily_wide(conn)
        if daily_wide.empty:
            log.error("daily_indicators is empty — run backfill_daily.py first.")
            return 1
        monthly_long = load_monthly_long(conn)
        feat = build_features(daily_wide, monthly_long)

        log.info("features: %d rows x %d cols  (%s -> %s)",
                 len(feat), feat.shape[1], feat["date"].min().date(), feat["date"].max().date())
        lookahead_audit(feat, monthly_long)

        if DRY_RUN:
            log.info("DRY_RUN — not writing. Head:\n%s", feat.head().to_string(index=False))
            log.info("NaN per column:\n%s", feat.isna().sum().to_string())
            return 0

        write_features(conn, feat)
        return 0
    except MySQLError as e:
        log.error("DB error: %s", e)
        return 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())