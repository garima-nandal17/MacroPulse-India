"""
download_monthly.py — MacroPulse India
Day 3: download the latest CPI / IIP / PLFS data files into data/monthly_raw/.

Fill SOURCES with the direct download links from the MoSPI / esankhyiki download
pages (open the download page, right-click the download button -> "Copy link").
  * If a link is a stable direct file URL -> this runs fully unattended.
  * If a source is session-gated -> leave its URL "" and drop the file into the
    folder manually each month. load_monthly.py processes whatever is present.

This keeps the UNRELIABLE step (download) isolated from the RELIABLE step
(parse + load): a failed download can never corrupt already-loaded data.

Run:
    python download_monthly.py
"""

from __future__ import annotations

import logging
import os
from datetime import date

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# indicator key -> (download_url, raw_folder). Leave url "" to skip (manual drop).
#
# AUTOMATION VERDICT (see chat):
#   CPI : leave "" — fully automated via the esankhyiki API in fetch_monthly.py
#         (fetch_cpi). Does NOT need a file download.
#   IIP : a STABLE auto URL exists via data.gov.in, but only for the OLD
#         base-2011-12 series. To use it, paste your resource_id + key:
#         https://api.data.gov.in/resource/<RESOURCE_ID>?api-key=<KEY>&format=csv&limit=100&offset=0
#         The CURRENT base-2022-23 series has no verifiable stable URL -> manual drop.
#   PLFS: new monthly series (2025); no verifiable automated source -> manual drop.
SOURCES = {
    "cpi":  ("", "data/monthly_raw/cpi"),   # handled by API; leave blank
    "iip":  ("", "data/monthly_raw/iip"),   # data.gov.in URL (old base) or manual
    "plfs": ("", "data/monthly_raw/plfs"),  # manual drop
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("macropulse.download_monthly")


def _ext(url: str, resp: requests.Response) -> str:
    ct = resp.headers.get("content-type", "").lower()
    if "csv" in ct or url.lower().endswith(".csv"):
        return "csv"
    if "sheet" in ct or "excel" in ct or url.lower().endswith((".xlsx", ".xls")):
        return "xlsx"
    return "dat"


def download(name: str, url: str, folder: str) -> None:
    if not url:
        log.info("%s: no URL set — skipping (drop the file manually into %s/).", name, folder)
        return
    os.makedirs(folder, exist_ok=True)
    try:
        resp = requests.get(url, timeout=60, verify=False, stream=True)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.error("%s: download failed: %s", name, exc)
        return
    path = os.path.join(folder, f"{name}_{date.today().isoformat()}.{_ext(url, resp)}")
    with open(path, "wb") as fh:
        for chunk in resp.iter_content(8192):
            fh.write(chunk)
    log.info("%s -> %s (%d bytes)", name, path, os.path.getsize(path))


def main() -> int:
    for name, (url, folder) in SOURCES.items():
        download(name, url, folder)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())