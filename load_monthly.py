"""
load_monthly.py — MacroPulse India
Day 3: parse the newest downloaded file in each data/monthly_raw/<indicator>/
folder and upsert into monthly_indicators, plus write the repo rate from config.

This is the RELIABLE half of the pipeline — fully in our control, no API.
On the first run it logs each file's structure (columns + first rows); set the
PARSE_CONFIG below to the real column names and it becomes fully automatic.

Run:
    DRY_RUN=1 python load_monthly.py    # parse + PRINT structure, no DB writes
    python load_monthly.py              # parse + upsert
"""

from __future__ import annotations

import glob
import logging
import os
import re
import shutil
import sys
from datetime import date

import pandas as pd
from mysql.connector import Error as MySQLError

from fetch_daily import get_connection  # canonical DB connection

DRY_RUN = os.environ.get("DRY_RUN") == "1"

RAW_DIRS = {
    "CPI": "data/monthly_raw/cpi",
    "IIP": "data/monthly_raw/iip",
    "Unemployment": "data/monthly_raw/plfs",
}
PROCESSED_DIR = "data/monthly_processed"

# Repo rate stays a config constant (no file). Update ~6x/yr when the MPC moves.
REPO_RATE = {"value": 5.25, "effective_date": "2025-12-05", "source": "RBI"}

# release lag per indicator: (months after the reference month, release day).
RELEASE_LAG = {"CPI": (1, 12), "IIP": (2, 12), "Unemployment": (1, 15)}

SOURCES = {"CPI": "MoSPI CPI", "IIP": "MoSPI IIP", "Unemployment": "MoSPI PLFS"}

MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], start=1)}

# === TUNE after the first inspect run (the loader logs each file's columns) ===
#   value_col  : column holding the index / rate value
#   period_col : a single date/"YYYY-MM" column, OR a (year_col, month_col) tuple
#   filter     : keep only rows matching {column: value} (the headline series)
PARSE_CONFIG = {
    # CPI General index, all-India, combined, base 2024 — now loaded from a FILE
    # (the API path is retired: it paginates the entire granular CPI universe).
    # VERIFY labels via DRY_RUN; the grain guard dumps distinct values on mismatch.
    "CPI":          {"value_col": "index", "period_col": ("year", "month"),
                     "filter": {"state": "All India", "sector": "Combined",
                                "division": "CPI (General)"},
                     "base_year": "2024"},
    # IIP General Index, all-India, base 2022-23. (type=General, category=General isolates it.)
    "IIP":          {"value_col": "index", "period_col": ("year", "month"),
                     "filter": {"type": "General", "category": "General"},
                     "base_year": "2022-23"},
    # PLFS monthly all-India UR. The file ships every disaggregation, so we filter to the
    # single headline row. VERIFY the four dimension labels against your file — a DRY_RUN
    # prints distinct values if a label mismatches (0 rows) or isn't specific enough (>1/month).
    "Unemployment": {"value_col": "value", "period_col": ("year", "month"),
                     "filter": {"indicator": "UR (Unemployment Rate, in per cent)",
                                "state": "All India", "frequency": "Monthly",
                                "gender": "person", "sector": "rural + urban",
                                "agegroup": "15 years and above"},
                     "base_year": None},
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("macropulse.load_monthly")

UPSERT_SQL = """
    INSERT INTO monthly_indicators (indicator, period, value, release_date, base_year, source)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        value        = VALUES(value),
        release_date = VALUES(release_date),
        base_year    = VALUES(base_year),
        source       = VALUES(source);
"""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _num(x):
    try:
        return round(float(str(x).replace(",", "").strip()), 4)
    except (ValueError, TypeError, AttributeError):
        return None


def _to_period(year_raw, month_raw):
    if year_raw is None or month_raw is None:
        return None
    mr = str(month_raw).strip()
    month = int(float(mr)) if mr.replace(".", "", 1).isdigit() else MONTHS.get(mr.lower())
    if not month or not (1 <= month <= 12):
        return None
    y = str(year_raw).strip()
    if "-" in y:  # financial year e.g. 2025-26
        start = int(y.split("-")[0])
        cal = start if month >= 4 else start + 1
    else:
        cal = int(float(y))
    try:
        return date(cal, month, 1)
    except ValueError:
        return None


def _release_for(indicator, period):
    lag, day = RELEASE_LAG.get(indicator, (1, 15))
    total = (period.month - 1) + lag
    y = period.year + total // 12
    m = total % 12 + 1
    try:
        return date(y, m, day)
    except ValueError:
        return date(y, m, 28)


def _period_from(row, period_col):
    if isinstance(period_col, (tuple, list)):
        return _to_period(row.get(period_col[0]), row.get(period_col[1]))
    try:
        ts = pd.to_datetime(row.get(period_col))
        return date(ts.year, ts.month, 1)
    except Exception:
        return None


def _newest_file(folder):
    files = [f for f in glob.glob(os.path.join(folder, "*"))
             if f.lower().endswith((".csv", ".xlsx", ".xls"))]
    return max(files, key=os.path.getmtime) if files else None


def _normalize_columns(df):
    """Canonicalise headers (lower/trim, spaces -> underscores) and coalesce duplicates.

    Manual merges of MoSPI exports can mix conventions ('weekly status' vs
    'weekly_status', 'AgeGroup' vs 'agegroup'), producing duplicate columns with
    data split across them. We collapse each variant set into one canonical column,
    filling nulls from the variants so no values are lost.
    """
    groups = {}
    for col in df.columns:
        key = re.sub(r"_+", "_", re.sub(r"[\s\-]+", "_", str(col).strip().lower()))
        groups.setdefault(key, []).append(col)
    out = pd.DataFrame(index=df.index)
    for key, cols in groups.items():
        s = df[cols[0]]
        for c in cols[1:]:
            s = s.combine_first(df[c])
        out[key] = s
    return out


def _read(path):
    df = pd.read_csv(path) if path.lower().endswith(".csv") else pd.read_excel(path)
    return _normalize_columns(df)  # requires openpyxl for .xlsx


# --------------------------------------------------------------------------- #
# Parse
# --------------------------------------------------------------------------- #
def _dump_distinct(df):
    """Print distinct values of low-cardinality columns so filter labels can be set."""
    for c in df.columns:
        u = pd.Series(df[c]).dropna().unique()
        if 1 < len(u) <= 15:
            log.info("  distinct %-16s: %s", c, list(u)[:15])


def parse_indicator(indicator, df, cfg):
    # On first run this is your map of the file — paste it back to configure.
    log.info("%s: %d rows x %d cols. Columns: %s", indicator, len(df), df.shape[1], list(df.columns))
    log.info("%s head:\n%s", indicator, df.head(3).to_string())

    vc, pc = cfg.get("value_col"), cfg.get("period_col")
    if not vc or not pc:
        log.warning("%s: PARSE_CONFIG not set — paste the columns/head above and I'll wire it.", indicator)
        return []

    flt = cfg.get("filter", {})
    rows = []
    for _, r in df.iterrows():
        # case-insensitive, whitespace-tolerant match on every filter key
        if any(str(r.get(k)).strip().lower() != str(v).strip().lower() for k, v in flt.items()):
            continue
        value = _num(r.get(vc))
        period = _period_from(r, pc)
        if value is None or period is None:
            continue
        rows.append((indicator, period, value, _release_for(indicator, period),
                     cfg.get("base_year"), SOURCES.get(indicator, "MoSPI")))

    # Grain guard: must be exactly one observation per period, or we refuse to load.
    periods = [r[1] for r in rows]
    if not rows:
        log.warning("%s: 0 rows after filter — a label likely mismatches. Distinct values:", indicator)
        _dump_distinct(df)
        return []
    if len(periods) != len(set(periods)):
        log.warning("%s: %d rows but only %d distinct periods — filter too loose (>1 row/month). "
                    "Tighten with these distinct values:", indicator, len(rows), len(set(periods)))
        _dump_distinct(df)
        return []
    log.info("%s: parsed %d rows (one per period).", indicator, len(rows))
    return rows


def repo_rows():
    eff = date.fromisoformat(REPO_RATE["effective_date"])
    return [("RepoRate", date(eff.year, eff.month, 1), float(REPO_RATE["value"]),
             eff, None, REPO_RATE["source"])]


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def main() -> int:
    all_rows = list(repo_rows())  # repo is always available

    for indicator, folder in RAW_DIRS.items():
        path = _newest_file(folder)
        if not path:
            log.warning("%s: no file in %s/ — skipping.", indicator, folder)
            continue
        log.info("%s: reading %s", indicator, path)
        try:
            df = _read(path)
        except Exception as exc:
            log.error("%s: could not read %s: %s", indicator, path, exc)
            continue
        rows = parse_indicator(indicator, df, PARSE_CONFIG[indicator])
        all_rows += rows
        if rows and not DRY_RUN:
            os.makedirs(PROCESSED_DIR, exist_ok=True)
            shutil.copy2(path, os.path.join(PROCESSED_DIR, os.path.basename(path)))

    if DRY_RUN:
        log.info("DRY-RUN: %d total rows parsed (incl. repo). Nothing written.", len(all_rows))
        print(f"DRY-RUN — {len(all_rows)} rows parsed.")
        return 0

    try:
        conn = get_connection()
    except MySQLError as exc:
        log.error("Could not connect to MySQL: %s", exc)
        return 1
    cursor = None
    try:
        cursor = conn.cursor()
        cursor.executemany(UPSERT_SQL, all_rows)
        conn.commit()
        log.info("Upserted %d rows into monthly_indicators.", len(all_rows))
    finally:
        if cursor is not None:
            cursor.close()
        if conn.is_connected():
            conn.close()

    print(f"\u2705 MONTHLY LOAD — {len(all_rows)} rows upserted into monthly_indicators.")
    return 0


if __name__ == "__main__":
    sys.exit(main())