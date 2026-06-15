"""
fetch_monthly.py — MacroPulse India
Day 3 (Block B): one consolidated, self-discovering monthly fetcher.

Writes CPI, IIP, Unemployment (PLFS UR) and the RBI repo rate into the canonical
`monthly_indicators(indicator, period, value, release_date, base_year, source)`.

Design:
  * CPI + Repo  — shapes known, parsed directly.
  * IIP + PLFS  — the API docs are incomplete, so these AUTO-DISCOVER a working
    parameter combination by sweeping a small grid, then map records ADAPTIVELY
    (trying common field-name variants). The first working combo is logged as
    "WORKING ... PARAMS" — paste it into IIP_PARAMS / PLFS_PARAMS below to skip
    the sweep on future runs.
  * release_date is DERIVED (the API gives none): CPI ~12th of month+1,
    IIP ~12th of month+2, Unemployment ~15th of month+1 — the point-in-time rule.

Run (verify first, write second):
    DRY_RUN=1 python fetch_monthly.py     # discover + map + PRINT, no DB writes
    python fetch_monthly.py               # discover + map + upsert
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import date

import requests
from dotenv import load_dotenv
from mysql.connector import Error as MySQLError

from fetch_daily import get_connection  # single source of truth for the DB connection

load_dotenv()

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
MOSPI_BASE_URL = os.environ.get("MOSPI_BASE_URL", "https://api.mospi.gov.in")
DRY_RUN = os.environ.get("DRY_RUN") == "1"

# MoSPI presents a self-signed / incomplete TLS chain, so verification is OFF by
# default (this is read-only public data). For the SECURE path, pin the server's
# chain: set MOSPI_VERIFY_SSL=1 and MOSPI_CA_BUNDLE=/path/to/mospi_chain.pem.
VERIFY_SSL = os.environ.get("MOSPI_VERIFY_SSL", "0") == "1"
CA_BUNDLE = os.environ.get("MOSPI_CA_BUNDLE")

# MoSPI rejects page sizes above 100 ("Maximum allowed is 100").
PAGE_SIZE = 100

# Repo rate: config constant (changes ~6x/yr, no clean API). Update when MPC moves.
REPO_RATE = {"value": 5.25, "effective_date": "2025-12-05", "source": "RBI"}

# Paste a discovered combo here after the first run to skip the sweep, e.g.
# PLFS_PARAMS = {"indicator_code": 3, "frequency_code": 3, "year": "2025-26", ...}
IIP_PARAMS: dict | None = None
PLFS_PARAMS: dict | None = None

# CPI request params: the endpoint requires base_year AND a "Level" parameter
# (it returned 400 "Missing required parameters: Level" without it). "National"
# is a GUESS — confirm against Swagger / your working call and replace if rejected.
CPI_PARAMS = {"base_year": "2024", "Level": "National"}

# Headline CPI filter (applied client-side).
CPI_STATE, CPI_SECTOR, CPI_DIVISION_KW = "all india", "combined", "general"

# release lag per indicator: (months after the reference month, release day).
RELEASE_LAG = {"CPI": (1, 12), "IIP": (2, 12), "Unemployment": (1, 15)}

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}

# Adaptive field-name candidates (response shapes are undocumented).
VALUE_FIELDS = {
    "IIP": ["index", "index_value", "value", "general_index", "iip"],
    "Unemployment": ["value", "ur", "unemployment_rate", "estimate", "rate", "indicator_value"],
}
YEAR_FIELDS = ["year", "cal_year", "calendar_year", "survey_year", "financial_year"]
MONTH_FIELDS = ["month", "month_name", "month_code"]
DESC_FIELDS = ["category", "category_name", "description", "item", "name", "type"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("macropulse.fetch_monthly")

# One shared session. MoSPI's chain is self-signed, so verification is off by
# default; the warning is silenced after a single transparent note.
SESSION = requests.Session()
if VERIFY_SSL:
    SESSION.verify = CA_BUNDLE or True
else:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    SESSION.verify = False
    log.warning("TLS verification DISABLED for MoSPI (self-signed chain). "
                "For the secure path set MOSPI_VERIFY_SSL=1 + MOSPI_CA_BUNDLE.")

UPSERT_SQL = """
    INSERT INTO monthly_indicators
        (indicator, period, value, release_date, base_year, source)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        value        = VALUES(value),
        release_date = VALUES(release_date),
        base_year    = VALUES(base_year),
        source       = VALUES(source);
"""


# --------------------------------------------------------------------------- #
# Generic helpers
# --------------------------------------------------------------------------- #
def _records(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        lower = {str(k).lower(): v for k, v in payload.items()}
        for key in ("data", "records", "result", "results", "rows"):
            v = lower.get(key)
            if isinstance(v, list):
                return v
    return []


def _get(path: str, params: dict | None = None, debug: bool = False, retries: int = 2):
    """GET an endpoint; return (status_code, records). Never raises.
    Retries transient 5xx (502/503/504) so a blip doesn't truncate pagination.
    When debug=True, logs exactly why a call yielded no usable records."""
    url = f"{MOSPI_BASE_URL}{path}"
    p = dict(params or {})
    p.setdefault("Format", "JSON")
    resp = None
    for attempt in range(retries + 1):
        try:
            resp = SESSION.get(url, params=p, timeout=30)
        except requests.RequestException as exc:
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            log.warning("request error on %s: %s", path, exc)
            return None, []
        if resp.status_code in (502, 503, 504) and attempt < retries:
            time.sleep(1.5 * (attempt + 1))
            continue
        break
    if resp.status_code != 200:
        log.warning("HTTP %s for %s | body: %s", resp.status_code, resp.url, resp.text[:300])
        return resp.status_code, []
    try:
        payload = resp.json()
    except ValueError:
        log.warning("non-JSON for %s | body: %s", resp.url, resp.text[:300])
        return 200, []
    recs = _records(payload)
    if not recs and debug:
        keys = list(payload.keys()) if isinstance(payload, dict) else f"list[{len(payload)}]"
        msg = payload.get("msg") if isinstance(payload, dict) else None
        log.info("0 records from %s | envelope keys=%s | msg=%s", resp.url, keys, msg)
    return 200, recs


def _first(record: dict, candidates: list[str]):
    lower = {str(k).lower(): v for k, v in record.items()}
    for c in candidates:
        v = lower.get(c.lower())
        if v not in (None, "", "NA", "na"):
            return v
    return None


def _num(x):
    if x is None:
        return None
    try:
        return round(float(str(x).replace(",", "").strip()), 4)
    except (ValueError, TypeError):
        return None


def _to_period(year_raw, month_raw) -> date | None:
    """Build the reference-month date from (year, month). Handles calendar years
    ('2025'), financial years ('2025-26'), and month as name or number."""
    if year_raw is None or month_raw is None:
        return None
    mr = str(month_raw).strip()
    month = int(mr) if mr.isdigit() else MONTHS.get(mr.lower())
    if not month or not (1 <= month <= 12):
        return None
    y = str(year_raw).strip()
    if "-" in y:  # financial year e.g. 2025-26 → Apr..Dec = start year, Jan..Mar = start+1
        start = int(y.split("-")[0])
        cal = start if month >= 4 else start + 1
    else:
        cal = int(y)
    try:
        return date(cal, month, 1)
    except ValueError:
        return None


def _release_for(indicator: str, period: date) -> date:
    lag, day = RELEASE_LAG.get(indicator, (1, 15))
    total = (period.month - 1) + lag
    y = period.year + total // 12
    m = total % 12 + 1
    try:
        return date(y, m, day)
    except ValueError:
        return date(y, m, 28)


def _is_all_india(record: dict) -> bool:
    for f in ("state", "state_name"):
        v = _first(record, [f])
        if v is not None:
            return "india" in str(v).lower()
    return True  # no state field → assume already all-India


# --------------------------------------------------------------------------- #
# CPI  (known shape)
# --------------------------------------------------------------------------- #
def fetch_cpi() -> list[tuple]:
    rows, page, seen = [], 1, 0
    sectors_seen, divisions_seen = set(), set()
    while True:
        status, recs = _get("/api/cpi/getCPIData",
                             {**CPI_PARAMS, "limit": PAGE_SIZE, "page": page}, debug=True)
        if status != 200:
            log.warning("CPI stopped at page %d (HTTP %s) — series may be truncated.", page, status)
            break
        if not recs:
            break
        for r in recs:
            seen += 1
            sectors_seen.add(str(_first(r, ["sector"])))
            divisions_seen.add(str(_first(r, ["division"])))
            if str(_first(r, ["state"]) or "").strip().lower() != CPI_STATE:
                continue
            if str(_first(r, ["sector"]) or "").strip().lower() != CPI_SECTOR:
                continue
            if CPI_DIVISION_KW not in str(_first(r, ["division"]) or "").lower():
                continue
            value = _num(_first(r, ["index"]))
            period = _to_period(_first(r, ["year"]), _first(r, ["month"]))
            if value is None or period is None:
                continue
            base_year = str(_first(r, ["base_year"]) or "").strip() or None
            rows.append(("CPI", period, value, _release_for("CPI", period), base_year, "MoSPI"))
        page += 1
        if page % 25 == 0:
            log.info("CPI: paged %d, scanned %d, kept %d so far...", page, seen, len(rows))
        if page > 1000:
            break
    log.info("CPI: scanned %d records over %d pages, kept %d rows.", seen, page - 1, len(rows))
    if seen and len(rows) < 12:
        log.info("CPI sectors seen: %s", sorted(s for s in sectors_seen if s and s != "None")[:12])
        log.info("CPI divisions seen: %s", sorted(d for d in divisions_seen if d and d != "None")[:15])
    return rows


# --------------------------------------------------------------------------- #
# Repo  (config constant)
# --------------------------------------------------------------------------- #
def fetch_repo() -> list[tuple]:
    eff = date.fromisoformat(REPO_RATE["effective_date"])
    period = date(eff.year, eff.month, 1)
    return [("RepoRate", period, float(REPO_RATE["value"]), eff, None, REPO_RATE["source"])]


# --------------------------------------------------------------------------- #
# PLFS unemployment  (auto-discover params, adaptive map)
# --------------------------------------------------------------------------- #
def _discover_plfs() -> dict | None:
    if PLFS_PARAMS:
        return PLFS_PARAMS
    base = {"indicator_code": 3, "frequency_code": 3}  # UR, monthly
    years = ["2025-26", "2024-25", "2025", "2026", "2023-24"]
    sectors, weeklies, genders, states = [3, 1, 2], [2, 1], [3, None], [None, 0]
    tried = 0
    for y in years:
        for s in sectors:
            for w in weeklies:
                for g in genders:
                    for st in states:
                        params = {**base, "year": y, "sector_code": s, "weekly_status_code": w}
                        if g is not None:
                            params["gender_code"] = g
                        if st is not None:
                            params["state_code"] = st
                        _, recs = _get("/api/plfs/getData", {**params, "limit": 10, "page": 1})
                        tried += 1
                        if recs:
                            log.info("WORKING PLFS PARAMS: %s", params)
                            return params
                        time.sleep(0.2)
                        if tried >= 200:
                            log.error("PLFS discovery exhausted %d combos with no data.", tried)
                            return None
    log.error("PLFS discovery found no working combination.")
    return None


def fetch_plfs() -> list[tuple]:
    params = _discover_plfs()
    if not params:
        return []
    all_recs, page = [], 1
    while True:
        _, recs = _get("/api/plfs/getData", {**params, "limit": PAGE_SIZE, "page": page}, debug=True)
        if not recs:
            break
        all_recs += recs
        page += 1
        if page > 100:
            break
    rows = []
    for r in all_recs:
        if not _is_all_india(r):
            continue
        value = _num(_first(r, VALUE_FIELDS["Unemployment"]))
        period = _to_period(_first(r, YEAR_FIELDS), _first(r, MONTH_FIELDS))
        if value is None or period is None:
            continue
        rows.append(("Unemployment", period, value, _release_for("Unemployment", period), None, "MoSPI PLFS"))
    if not rows and all_recs:
        log.warning("PLFS: %d records fetched but 0 mapped. Keys seen: %s",
                    len(all_recs), list(all_recs[0].keys()))
    return rows


# --------------------------------------------------------------------------- #
# IIP  (auto-discover the General-index params, adaptive map)
# --------------------------------------------------------------------------- #
def _discover_iip() -> dict | None:
    if IIP_PARAMS:
        return IIP_PARAMS
    for mpath in ("/api/iip/getMetadata", "/api/iip/getMetaData", "/api/iip/metadata"):
        _, recs = _get(mpath)
        if recs:
            log.info("IIP metadata at %s, keys: %s", mpath, list(recs[0].keys()))
    base = {"frequency": 2, "base_year": "2022-23"}
    fallback = None
    for t in (1, 2, 3, 4):
        for c in range(1, 21):
            params = {**base, "type": t, "category_code": c}
            _, recs = _get("/api/iip/getIIPData", {**params, "limit": 5, "page": 1})
            if recs:
                desc = str(_first(recs[0], DESC_FIELDS) or "").lower()
                if "general" in desc:
                    log.info("WORKING IIP PARAMS (General): %s", params)
                    return params
                if fallback is None:
                    fallback = params
                    log.info("IIP working combo (not General): %s desc=%r", params, desc)
            time.sleep(0.2)
    if fallback:
        log.warning("IIP: no 'General' match; using fallback (VERIFY): %s", fallback)
    else:
        log.error("IIP discovery found nothing — may need subcategory_code.")
    return fallback


def fetch_iip() -> list[tuple]:
    params = _discover_iip()
    if not params:
        return []
    all_recs, page = [], 1
    while True:
        _, recs = _get("/api/iip/getIIPData", {**params, "limit": PAGE_SIZE, "page": page}, debug=True)
        if not recs:
            break
        all_recs += recs
        page += 1
        if page > 100:
            break
    rows = []
    for r in all_recs:
        value = _num(_first(r, VALUE_FIELDS["IIP"]))
        period = _to_period(_first(r, YEAR_FIELDS), _first(r, MONTH_FIELDS))
        if value is None or period is None:
            continue
        base_year = str(_first(r, ["base_year"]) or "2022-23").strip()
        rows.append(("IIP", period, value, _release_for("IIP", period), base_year, "MoSPI"))
    if not rows and all_recs:
        log.warning("IIP: %d records fetched but 0 mapped. Keys seen: %s",
                    len(all_recs), list(all_recs[0].keys()))
    return rows


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def main() -> int:
    try:
        conn = get_connection()
    except MySQLError as exc:
        log.error("Could not connect to MySQL: %s", exc)
        return 1

    written = 0
    cursor = None
    sources = [("CPI", fetch_cpi), ("IIP", fetch_iip),
               ("Unemployment", fetch_plfs), ("Repo", fetch_repo)]
    try:
        cursor = conn.cursor()
        for name, fetch_fn in sources:
            try:
                rows = fetch_fn()
                if DRY_RUN:
                    log.info("%s: %d rows (DRY-RUN). sample=%s", name, len(rows), rows[:2])
                    written += len(rows)
                    continue
                if rows:
                    cursor.executemany(UPSERT_SQL, rows)
                    conn.commit()
                    written += len(rows)
                    log.info("%s: %d rows upserted.", name, len(rows))
                else:
                    log.warning("%s: 0 rows.", name)
            except Exception as exc:
                if not DRY_RUN:
                    conn.rollback()
                log.error("%s failed: %s", name, exc)
                continue
    finally:
        if cursor is not None:
            cursor.close()
        if conn.is_connected():
            conn.close()

    log.info("Monthly run complete: %d rows.", written)
    print(f"\u2705 MONTHLY {'DRY-RUN' if DRY_RUN else 'FETCH'} — {written} rows.")
    return 0 if (written or DRY_RUN) else 1


if __name__ == "__main__":
    sys.exit(main())