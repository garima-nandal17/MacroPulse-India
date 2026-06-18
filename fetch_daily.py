"""
fetch_daily.py — MacroPulse India
Day 2: Download the 8 daily-layer indicators from Yahoo Finance, compute each
one's day-over-day percentage change, and upsert one row per indicator into the
MySQL `daily_indicators` table.

Run:
    python fetch_daily.py

Design notes (each is an interview talking point):
  * Config-driven  — add an indicator by adding one line to INDICATORS. (DRY)
  * Fault-isolated — each indicator is fetched + stored inside its OWN
    try/except, so one bad ticker (a Yahoo hiccup, a delisting) never kills
    the whole run.
  * Idempotent     — the UPSERT means re-running never creates duplicate rows
    for the same (date, indicator).
  * Observable     — every step is logged and the run ends with a summary line.

Exit codes:
    0  at least one indicator stored successfully
    1  fatal error (could not connect to the DB) OR every indicator failed
       — lets GitHub Actions (Day 4) flag a broken run.
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
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),                 # console / stdout — GitHub Actions captures this
        logging.FileHandler("fetch_daily.log"),  # persisted local run log
    ],
)


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
# DB credentials come from environment variables so no secret is ever committed.
# Locally: a .env file. On GitHub Actions (Day 4): repository Secrets.
load_dotenv()

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": int(os.environ.get("DB_PORT", "3306")),
    "user": os.environ.get("DB_USER", "macropulse"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "database": os.environ.get("DB_NAME", "macropulse_india"),
}

# Add an indicator by adding ONE line here — nothing else in the file changes.
# Unit noted per ticker: silently mixing units would corrupt later correlations.
INDICATORS = {
    "USDINR":     "INR=X",      # FX rate
    "Nifty50":    "^NSEI",      # index level
    "BankNifty":  "^NSEBANK",   # index level
    "BrentCrude": "BZ=F",       # USD price / barrel
    "Gold":       "GC=F",       # USD price / oz
    "IndiaVIX":   "^INDIAVIX",  # index level (fear gauge)
    "DXY":        "DX-Y.NYB",   # index level
    "US10Y":      "^TNX",       # 10Y Treasury yield  (verify scale — see note)
  # Sector indices
    "NiftyIT":     "^CNXIT",
    "NiftyPharma": "^CNXPHARMA",
    "NiftyAuto":   "^CNXAUTO",
    "NiftyFMCG":   "^CNXFMCG",
    "NiftyRealty": "^CNXREALTY",
    "NiftyMetal":  "^CNXMETAL",
    "NiftyEnergy": "^CNXENERGY",
}

LOOKBACK_PERIOD = "7d"  # a week guarantees >=2 trading days even after a long weekend


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("macropulse.fetch_daily")


# --------------------------------------------------------------------------- #
# Fetch
# --------------------------------------------------------------------------- #
def fetch_indicator(indicator_name: str, ticker: str) -> tuple[date, float, float]:
    """
    Download recent closes for one ticker and compute the latest
    day-over-day % change.

    Returns
    -------
    (as_of_date, latest_close, pct_change)

    Raises
    ------
    ValueError
        If no data is returned, or there are fewer than two trading days to
        compare.
    """
    log.info("Fetching %s (%s)...", indicator_name, ticker)
    df = yf.Ticker(ticker).history(period=LOOKBACK_PERIOD, interval="1d")

    if df is None or df.empty:
        raise ValueError(f"No data returned for {ticker}.")

    # Drop rows with a missing close before computing the change.
    closes = df["Close"].dropna()
    if len(closes) < 2:
        raise ValueError(
            f"Need >=2 trading days to compute a change; got {len(closes)}."
        )

    latest_close = float(closes.iloc[-1])
    prev_close = float(closes.iloc[-2])
    pct_change = ((latest_close - prev_close) / prev_close) * 100.0

    # Use the date of the LATEST available close, not today's date — they differ
    # on weekends/holidays when the market is shut.
    as_of_date = closes.index[-1].date()

    log.info(
        "%s on %s: %.4f  (prev %.4f, change %+.2f%%)",
        indicator_name, as_of_date, latest_close, prev_close, pct_change,
    )
    return as_of_date, round(latest_close, 4), round(pct_change, 4)


# --------------------------------------------------------------------------- #
# Persist
# --------------------------------------------------------------------------- #
def get_connection():
    """Open a single MySQL connection, reused for the whole run."""
    return mysql.connector.connect(**DB_CONFIG)


def upsert_row(
    cursor,
    indicator_name: str,
    as_of_date: date,
    value: float,
    pct_change: float,
) -> None:
    """
    Insert one row into `daily_indicators`, updating it if the (date, indicator)
    pair already exists. Requires a UNIQUE constraint on (date, indicator),
    which is what makes re-runs idempotent.

    Note: with ON DUPLICATE KEY UPDATE, MySQL reports rowcount as 1 for a fresh
    insert, 2 for an update, 0 if values were unchanged.
    """
    sql = """
        INSERT INTO daily_indicators (date, indicator, value, pct_change)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            value      = VALUES(value),
            pct_change = VALUES(pct_change);
    """
    cursor.execute(sql, (as_of_date, indicator_name, value, pct_change))


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def main() -> int:
    # Connect once. If even this fails, the whole run is broken -> exit 1.
    try:
        conn = get_connection()
    except MySQLError as exc:
        log.error("Could not connect to MySQL: %s", exc)
        return 1

    successes = 0
    failures = 0
    cursor = None

    try:
        cursor = conn.cursor()
        for indicator_name, ticker in INDICATORS.items():
            # Per-indicator isolation: a single failure logs and continues,
            # so the other indicators still land.
            try:
                as_of_date, value, pct_change = fetch_indicator(indicator_name, ticker)
                upsert_row(cursor, indicator_name, as_of_date, value, pct_change)
                conn.commit()  # commit per indicator so good data is durable
                successes += 1
            except Exception as exc:  # network, parsing, insufficient-data, or DB error
                conn.rollback()
                failures += 1
                log.error("%s (%s) failed: %s", indicator_name, ticker, exc)
                continue
    finally:
        if cursor is not None:
            cursor.close()
        if conn.is_connected():
            conn.close()
            log.debug("MySQL connection closed.")

    total = len(INDICATORS)
    log.info("Run complete: %d/%d succeeded, %d failed.", successes, total, failures)
    if failures:
        log.warning("%d indicator(s) failed this run — check the log above.", failures)

    if successes == 0:
        log.error("Every indicator failed — treating the run as failed.")
        return 1

    print(f"\u2705 SUCCESS — {successes}/{total} daily indicators stored.")
    return 0


if __name__ == "__main__":
    sys.exit(main())