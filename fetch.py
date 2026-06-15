"""
fetch.py — MacroPulse India
Day 1: Download USD/INR (INR=X) from Yahoo Finance, compute the day-over-day
percentage change, and upsert a single row into the MySQL `daily_indicators`
table.

Run:
    python fetch.py

Exit codes:
    0  success
    1  failure (fetch or database error) — lets GitHub Actions (Day 4) flag a bad run.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import date

from dotenv import load_dotenv

import yfinance as yf
import mysql.connector
from mysql.connector import Error as MySQLError


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
# DB credentials come from environment variables so no secret is ever committed
# to source control. Locally you can export them (or use a .env file); on
# GitHub Actions they'll be injected from repository Secrets on Day 4.

load_dotenv()


DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": int(os.environ.get("DB_PORT", "3306")),
    "user": os.environ.get("DB_USER", "macropulse"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "database": os.environ.get("DB_NAME", "macropulse_india"),
}

TICKER = "INR=X"            # Yahoo Finance symbol for USD/INR
INDICATOR_NAME = "USDINR"  # how this indicator is labelled in the DB
LOOKBACK_PERIOD = "7d"      # a week, so we still get 2 trading days after a weekend/holiday


# --------------------------------------------------------------------------- #
# Logging  (structured output to stdout; also satisfies "print a success message")
# --------------------------------------------------------------------------- #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("macropulse.fetch")


# --------------------------------------------------------------------------- #
# Fetch
# --------------------------------------------------------------------------- #
def fetch_usdinr() -> tuple[date, float, float]:
    """
    Download recent USD/INR closes and compute the latest day-over-day % change.

    Returns
    -------
    (as_of_date, latest_close, pct_change)

    Raises
    ------
    ValueError
        If no data is returned or there are fewer than two trading days to
        compare.
    """
    log.info("Fetching %s from Yahoo Finance...", TICKER)
    df = yf.Ticker(TICKER).history(period=LOOKBACK_PERIOD, interval="1d")

    if df is None or df.empty:
        raise ValueError(f"No data returned for {TICKER}.")

    # Drop any rows with a missing close before computing the change.
    closes = df["Close"].dropna()
    if len(closes) < 2:
        raise ValueError(
            f"Need at least 2 trading days to compute a change; got {len(closes)}."
        )

    latest_close = float(closes.iloc[-1])
    prev_close = float(closes.iloc[-2])
    pct_change = ((latest_close - prev_close) / prev_close) * 100.0

    # Use the date of the LATEST available close, not today's date — they differ
    # on weekends/holidays when the FX market is shut.
    as_of_date = closes.index[-1].date()

    log.info(
        "%s on %s: %.4f  (prev %.4f, change %+.2f%%)",
        INDICATOR_NAME, as_of_date, latest_close, prev_close, pct_change,
    )
    return as_of_date, round(latest_close, 4), round(pct_change, 4)


# --------------------------------------------------------------------------- #
# Persist
# --------------------------------------------------------------------------- #
def upsert_row(as_of_date: date, value: float, pct_change: float) -> None:
    """
    Insert one row into `daily_indicators`, updating it if the (date, indicator)
    pair already exists. This UPSERT makes re-runs idempotent: running the script
    twice in a day never creates a duplicate row.

    Requires a UNIQUE constraint on (date, indicator) in the table.
    """
    sql = """
        INSERT INTO daily_indicators (date, indicator, value, pct_change)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            value      = VALUES(value),
            pct_change = VALUES(pct_change);
    """
    conn = None
    cursor = None
    try:

        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute(sql, (as_of_date, INDICATOR_NAME, value, pct_change))
        conn.commit()
        # NOTE: with ON DUPLICATE KEY UPDATE, MySQL reports rowcount as
        # 1 for a fresh insert, 2 for an update, 0 if the values were unchanged.
        log.info("daily_indicators upsert complete (rowcount=%d).", cursor.rowcount)
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None and conn.is_connected():
            conn.close()
            log.debug("MySQL connection closed.")


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def main() -> int:
    # Stage 1: fetch
    try:
        as_of_date, value, pct_change = fetch_usdinr()
    except Exception as exc:  # network, parsing, or insufficient-data errors
        log.error("Fetch failed: %s", exc)
        return 1

    # Stage 2: persist
    try:
        upsert_row(as_of_date, value, pct_change)
    except MySQLError as exc:
        log.error("Database error: %s", exc)
        return 1
    except Exception as exc:
        log.error("Unexpected error while writing to DB: %s", exc)
        return 1

    print(
        f"\u2705 SUCCESS \u2014 {INDICATOR_NAME} {value:.4f} "
        f"({pct_change:+.2f}%) stored for {as_of_date}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())