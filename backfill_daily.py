"""
backfill_daily.py — MacroPulse India
Day 2 (Block C): one-time load of ~2 years of daily history for every
daily-layer indicator into the MySQL `daily_indicators` table.

Run ONCE (re-running is safe — the UPSERT updates in place, never duplicates):
    python backfill_daily.py

Reuses INDICATORS and get_connection from fetch_daily.py so the indicator list
and DB connection live in exactly one place (single source of truth).
"""

from __future__ import annotations

import logging
import sys

import pandas as pd
import yfinance as yf
from mysql.connector import Error as MySQLError

# Canonical config + connection helper — defined once, in fetch_daily.py.
from fetch_daily import INDICATORS, get_connection

BACKFILL_PERIOD = "2y"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("macropulse.backfill_daily")

# Same UPSERT as fetch_daily, so backfill and the daily run stay consistent.
UPSERT_SQL = """
    INSERT INTO daily_indicators (date, indicator, value, pct_change)
    VALUES (%s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        value      = VALUES(value),
        pct_change = VALUES(pct_change);
"""


def backfill_indicator(cursor, indicator_name: str, ticker: str) -> int:
    """
    Download ~2 years of daily closes for one ticker, compute each day's
    day-over-day % change, and bulk-upsert every row.

    Returns the number of rows written. Raises ValueError if no data.
    """
    log.info("Backfilling %s (%s)...", indicator_name, ticker)
    df = yf.Ticker(ticker).history(period=BACKFILL_PERIOD, interval="1d")

    if df is None or df.empty:
        raise ValueError(f"No data returned for {ticker}.")

    closes = df["Close"].dropna()
    pct = closes.pct_change() * 100.0  # first row is NaN — no prior day to compare

    rows = []
    for ts, close in closes.items():
        change = pct.loc[ts]
        # earliest day has no previous close -> store NULL, not a fake 0.
        change_val = None if pd.isna(change) else round(float(change), 4)
        rows.append((ts.date(), indicator_name, round(float(close), 4), change_val))

    # executemany batches the writes — far faster than one execute per row.
    cursor.executemany(UPSERT_SQL, rows)
    return len(rows)


def main() -> int:
    try:
        conn = get_connection()
    except MySQLError as exc:
        log.error("Could not connect to MySQL: %s", exc)
        return 1

    successes = 0
    failures = 0
    total_rows = 0
    cursor = None

    try:
        cursor = conn.cursor()
        for indicator_name, ticker in INDICATORS.items():
            # Per-indicator isolation — one bad ticker never aborts the rest.
            try:
                n = backfill_indicator(cursor, indicator_name, ticker)
                conn.commit()  # commit per indicator so partial progress is durable
                successes += 1
                total_rows += n
                log.info("%s: %d rows upserted.", indicator_name, n)
            except Exception as exc:
                conn.rollback()
                failures += 1
                log.error("%s (%s) failed: %s", indicator_name, ticker, exc)
                continue
    finally:
        if cursor is not None:
            cursor.close()
        if conn.is_connected():
            conn.close()

    total = len(INDICATORS)
    log.info(
        "Backfill complete: %d/%d indicators, %d rows total, %d failed.",
        successes, total, total_rows, failures,
    )

    if successes == 0:
        log.error("Every indicator failed — treating the backfill as failed.")
        return 1

    print(f"\u2705 BACKFILL DONE — {successes}/{total} indicators, {total_rows} rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())