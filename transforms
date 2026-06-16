"""
transforms.py — MacroPulse India, Day 6 analysis layer (stationarity transforms)

Turns the LEVELS feature store (features_daily) into STATIONARY series, so that
correlation / sector-sensitivity work measures genuine co-movement, not the shared
time trend that confounds level-on-level correlations (spurious regression).

Transform rules (deliberately not one-size-fits-all):
  - price / index / FX  -> log return        ln(x_t / x_{t-1})
  - yield (US10Y)       -> first difference   x_t - x_{t-1}   (a return on a yield is meaningless)
  - CPI, IIP (indices)  -> MoM % change at each release, held constant until next release
  - Unemployment, Repo  -> Δ (pp) at each release, held constant until next release

Monthly changes are inferred from the forward-filled level: the day before a release
holds the old level and the release day holds the new one, so a non-zero change appears
exactly on release days; we keep those and forward-fill to hold the latest change.
(Assumption: a release that leaves the level unchanged is treated as "no new change".)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# series name -> transform kind
DAILY_TRANSFORM = {
    "USDINR": "ret", "Nifty50": "ret", "BankNifty": "ret",
    "BrentCrude": "ret", "Gold": "ret", "DXY": "ret",
    "IndiaVIX": "ret",   # log-change; ΔVIX is a defensible alternative
    "US10Y": "diff",     # yield -> first difference (Δ pp), NOT a return
}
MONTHLY_TRANSFORM = {"CPI": "pct", "IIP": "pct", "Unemployment": "diff", "RepoRate": "diff"}

# macro columns that must be present for a row to enter the analysis window
# (RepoRate excluded: single value, too sparse to gate the window)
WINDOW_REQUIRES = ("CPI_chg", "IIP_chg", "Unemployment_chg")


def _step_change(level: pd.Series, kind: str) -> pd.Series:
    """Change at each release step (pct or diff), held constant until the next release."""
    raw = level.pct_change() if kind == "pct" else level.diff()
    return raw.where(raw != 0).ffill()   # keep release-day changes, hold them constant


def build_analysis_frame(feat: pd.DataFrame) -> pd.DataFrame:
    """features_daily (levels) -> stationary analysis frame (returns / diffs / changes)."""
    feat = feat.copy()
    feat["date"] = pd.to_datetime(feat["date"])
    feat = feat.sort_values("date").reset_index(drop=True)
    out = feat[["date"]].copy()

    for ind, kind in DAILY_TRANSFORM.items():
        if ind not in feat.columns:
            continue
        s = pd.to_numeric(feat[ind], errors="coerce")
        out[f"{ind}_ret" if kind == "ret" else f"{ind}_diff"] = (
            np.log(s / s.shift()) if kind == "ret" else s.diff()
        )

    for ind, kind in MONTHLY_TRANSFORM.items():
        if ind not in feat.columns:
            continue
        s = pd.to_numeric(feat[ind], errors="coerce")
        out[f"{ind}_chg"] = _step_change(s, kind)

    return out.replace([np.inf, -np.inf], np.nan)


def apply_window(out: pd.DataFrame, requires=WINDOW_REQUIRES) -> pd.DataFrame:
    """Trim the leading region until the gating macro change features are all present."""
    cols = [c for c in requires if c in out.columns]
    if not cols:
        return out.reset_index(drop=True)
    mask = out[cols].notna().all(axis=1)
    if not mask.any():
        return out.reset_index(drop=True)
    first = out.loc[mask, "date"].min()
    return out[out["date"] >= first].reset_index(drop=True)