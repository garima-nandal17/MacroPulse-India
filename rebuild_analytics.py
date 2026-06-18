"""
rebuild_analytics.py — MacroPulse India

Rebuilds the DERIVED analytics layer in dependency order, from the already-ingested
daily_indicators and monthly_indicators tables. Aborts on the first failure so a broken
upstream step never corrupts a downstream one.

  build_features.py   -> features_daily      (point-in-time levels)
  build_analysis.py   -> analysis_daily      (stationary transforms)
  sensitivity_matrix.py -> sensitivity_results (HAC betas)
  correlation_matrix.py -> correlation_results (correlations)

Raw ingestion (fetch_daily / backfill_daily / load_monthly) is UPSTREAM and runs in its
own workflows — this orchestrator assumes the base tables are current.

Run:  python rebuild_analytics.py        (set DRY_RUN=1 to pass through to each step)
"""
from __future__ import annotations

import logging
import subprocess
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("rebuild_analytics")

STEPS = [
    "build_features.py",
    "build_analysis.py",
    "sensitivity_matrix.py",
    "correlation_matrix.py",
]


def main() -> int:
    for step in STEPS:
        log.info("=== %s ===", step)
        result = subprocess.run([sys.executable, step])
        if result.returncode != 0:
            log.error("%s failed (exit %d) — aborting rebuild.", step, result.returncode)
            return result.returncode
    log.info("Analytics layer rebuilt successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())