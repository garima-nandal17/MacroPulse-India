"""
validate_signals.py — MacroPulse India, Day 12 (out-of-sample signal validation)

Answers the question the rest of the platform has not yet answered: do the sensitivity
signals hold OUT OF SAMPLE, or are they in-sample artifacts?

Design — honest by construction:
  * MONTHLY frequency. The macro *_chg factors are month-level step functions broadcast
    across ~21 daily rows, so a daily train/test split would (a) leak the same constant
    factor value into both sides and (b) pseudo-replicate ~21x, inflating any OOS score.
    Validating on month-end aggregates — reusing sensitivity_matrix.to_monthly so the prep
    is byte-identical to production — gives genuinely independent observations.
  * SAME MODEL. Univariate OLS  r_i = a + b*m_j , matching sensitivity_matrix (monthly path
    uses ordinary OLS; HAC affects only standard errors, not the beta point estimate, so the
    coefficient we validate is the same one production ships).
  * POINT-IN-TIME. Temporal splits only, never shuffled. Train = earlier months, test = later.
  * TWO TESTS per (asset, factor):
      1) Holdout      — fit on the first ~70% of months, score the last ~30%.
      2) Walk-forward — expanding window; one-step out-of-sample at each step from MIN_TRAIN on.
  * METRICS:
      - OOS R^2 vs a naive train-mean benchmark (Campbell-Thompson). Negative => the signal
        predicts WORSE than just guessing the average. This is the honest bar.
      - Directional hit-rate on demeaned factor moves (does the signal call up/down better than
        a coin?).
      - Beta sign-stability across walk-forward windows (does the relationship keep its sign?).
    A signal is VALIDATED only if it beats the naive mean (R^2_oos > 0) AND calls direction
    better than chance (hit >= 0.55) AND is sign-stable (>= 0.60).

Honest limits: with ~12-13 monthly observations this is a robustness PROBE, not proof — the
metrics are directional evidence and will sharpen as history accrues. The betas are
contemporaneous sensitivities, not lead-lag forecasts; this validates their stability/
generalization, not market-timing skill.

Env:
  DB_* via fetch_daily.get_connection
  DRY_RUN=1   -> compute and print, write nothing
  SELFTEST=1  -> run a synthetic correctness check (no DB needed) and exit
"""
from __future__ import annotations

import logging
import os
import sys

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("validate_signals")

RESULT_TABLE = "signal_validation"
MIN_TRAIN = 6            # smallest training window for walk-forward (small-sample reality)
HOLDOUT_FRAC = 0.30      # last 30% of months held out
HIT_BAR = 0.55           # directional accuracy bar (above a coin)
R2_BAR = 0.0             # must beat the naive train-mean benchmark
SIGN_BAR = 0.60          # fraction of walk-forward windows that keep the full-sample beta sign
ALPHA = 0.10             # production significance threshold (which signals the product ships)
DRY_RUN = os.getenv("DRY_RUN") == "1"


# --------------------------------------------------------------------------- #
# Core stats (numpy OLS — point estimates match statsmodels OLS exactly)
# --------------------------------------------------------------------------- #
def _fit(x, y):
    """Univariate OLS y = a + b*x. Returns (a, b) or None if degenerate."""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    if len(x) < 3 or x.std() == 0:
        return None
    b, a = np.polyfit(x, y, 1)   # slope, intercept
    return a, b


def _oos_r2(y_true, y_pred, y_bench):
    """Campbell-Thompson out-of-sample R^2 vs a benchmark prediction.
    > 0  => beats the benchmark; < 0 => worse than just predicting y_bench."""
    y_true, y_pred, y_bench = map(lambda v: np.asarray(v, float), (y_true, y_pred, y_bench))
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - y_bench) ** 2)
    if ss_tot == 0:
        return np.nan
    return 1.0 - ss_res / ss_tot


def _hit_rate(pred_dir, act_dir):
    """Fraction of non-zero calls where predicted and actual directions agree."""
    pred_dir, act_dir = np.asarray(pred_dir), np.asarray(act_dir)
    mask = (pred_dir != 0) & (act_dir != 0)
    return float(np.mean(pred_dir[mask] == act_dir[mask])) if mask.any() else np.nan


def holdout(x, y, frac=HOLDOUT_FRAC):
    """Fit on the first (1-frac) months, score the last frac. Direction uses demeaned moves."""
    n = len(x)
    n_test = max(2, int(round(n * frac)))
    if n - n_test < 3:
        return None
    xtr, ytr = x[:-n_test], y[:-n_test]
    xte, yte = x[-n_test:], y[-n_test:]
    fit = _fit(xtr, ytr)
    if fit is None:
        return None
    a, b = fit
    xbar, ybar = np.mean(xtr), np.mean(ytr)
    yhat = a + b * xte
    r2 = _oos_r2(yte, yhat, np.full(len(yte), ybar))
    hit = _hit_rate(np.sign(b * (xte - xbar)), np.sign(yte - ybar))
    return {"holdout_r2": r2, "holdout_hit": hit, "n_test": int(n_test)}


def walk_forward(x, y, min_train=MIN_TRAIN):
    """Expanding-window one-step OOS. Returns OOS R^2, hit-rate, and beta sign-stability."""
    n = len(x)
    if n < min_train + 2:
        return None
    full = _fit(x, y)
    if full is None:
        return None
    full_sign = np.sign(full[1])
    preds, acts, benches, pdir, adir, signs = [], [], [], [], [], []
    for t in range(min_train, n):
        fit = _fit(x[:t], y[:t])
        if fit is None:
            continue
        a, b = fit
        xbar, ybar = np.mean(x[:t]), np.mean(y[:t])
        preds.append(a + b * x[t]); acts.append(y[t]); benches.append(ybar)
        pdir.append(np.sign(b * (x[t] - xbar))); adir.append(np.sign(y[t] - ybar))
        signs.append(1.0 if np.sign(b) == full_sign and full_sign != 0 else 0.0)
    if len(preds) < 2:
        return None
    return {"wf_r2": _oos_r2(acts, preds, benches), "wf_hit": _hit_rate(pdir, adir),
            "sign_stable": float(np.mean(signs)), "n_wf": len(preds)}


def _verdict(r):
    """Validated only if it beats the naive mean AND a coin AND keeps its sign (walk-forward)."""
    if any(r.get(k) is None or (isinstance(r.get(k), float) and np.isnan(r.get(k)))
           for k in ("wf_r2", "wf_hit", "sign_stable")):
        return "insufficient data"
    if r["wf_r2"] > R2_BAR and r["wf_hit"] >= HIT_BAR and r["sign_stable"] >= SIGN_BAR:
        return "validated"
    if r["wf_r2"] > R2_BAR or r["wf_hit"] >= HIT_BAR:
        return "partial"
    return "in-sample only"


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def validate(monthly: pd.DataFrame, assets, factors, prod_sig: set) -> pd.DataFrame:
    """Run both tests for every (asset, factor); flag whether the product ships it."""
    rows = []
    for a in assets:
        for f in factors:
            x, y = monthly[f].to_numpy(float), monthly[a].to_numpy(float)
            ok = np.isfinite(x) & np.isfinite(y)
            x, y = x[ok], y[ok]
            if len(x) < MIN_TRAIN + 2 or x.std() == 0 or y.std() == 0:
                continue
            r = {"asset": a, "factor": f, "n_months": int(len(x)),
                 "prod_significant": (a, f) in prod_sig}
            ho, wf = holdout(x, y), walk_forward(x, y)
            r.update(ho or {"holdout_r2": np.nan, "holdout_hit": np.nan, "n_test": 0})
            r.update(wf or {"wf_r2": np.nan, "wf_hit": np.nan, "sign_stable": np.nan, "n_wf": 0})
            r["verdict"] = _verdict(r)
            rows.append(r)
    cols = ["asset", "factor", "prod_significant", "n_months", "n_test", "n_wf",
            "holdout_r2", "holdout_hit", "wf_r2", "wf_hit", "sign_stable", "verdict"]
    return pd.DataFrame(rows)[cols] if rows else pd.DataFrame(columns=cols)


def _write(conn, df):
    cur = conn.cursor()
    cur.execute(f"""CREATE TABLE IF NOT EXISTS `{RESULT_TABLE}` (
        asset VARCHAR(48), factor VARCHAR(48), prod_significant TINYINT, n_months INT,
        n_test INT, n_wf INT, holdout_r2 DOUBLE, holdout_hit DOUBLE, wf_r2 DOUBLE,
        wf_hit DOUBLE, sign_stable DOUBLE, verdict VARCHAR(20),
        PRIMARY KEY (asset, factor))""")
    cur.execute(f"TRUNCATE TABLE `{RESULT_TABLE}`")

    def _n(v):
        return None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)

    cur.executemany(
        f"""INSERT INTO `{RESULT_TABLE}` (asset, factor, prod_significant, n_months, n_test,
            n_wf, holdout_r2, holdout_hit, wf_r2, wf_hit, sign_stable, verdict)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        [(r.asset, r.factor, int(bool(r.prod_significant)), int(r.n_months), int(r.n_test),
          int(r.n_wf), _n(r.holdout_r2), _n(r.holdout_hit), _n(r.wf_r2), _n(r.wf_hit),
          _n(r.sign_stable), r.verdict) for r in df.itertuples()])
    conn.commit()
    cur.close()
    log.info("Wrote %d rows to %s.", len(df), RESULT_TABLE)


def _summarize(df):
    shipped = df[df.prod_significant]
    log.info("\n--- Out-of-sample validation (monthly, point-in-time) ---\n%s",
             df.to_string(index=False, float_format=lambda v: f"{v:+.3f}"))
    if not shipped.empty:
        v = (shipped.verdict == "validated").sum()
        p = (shipped.verdict == "partial").sum()
        log.info("\nOf %d signals the product ships (daily, p<=%.2f): "
                 "%d validated, %d partial, %d in-sample only / insufficient.",
                 len(shipped), ALPHA, v, p, len(shipped) - v - p)


def main() -> int:
    if os.getenv("SELFTEST") == "1":
        return selftest()

    from fetch_daily import get_connection                 # lazy: DB only needed for the real run
    from sensitivity_matrix import to_monthly               # reuse production monthly prep verbatim
    from mysql.connector import Error as MySQLError

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM analysis_daily")
        cols = [c[0] for c in cur.description]
        df = pd.DataFrame(cur.fetchall(), columns=cols)
        cur.close()
        if df.empty:
            log.error("analysis_daily is empty — run build_analysis.py first.")
            return 1
        df = df.apply(lambda c: pd.to_numeric(c, errors="ignore"))

        assets = [c for c in df.columns if c.endswith(("_ret", "_diff"))]
        factors = [c for c in df.columns if c.endswith("_chg")]
        monthly = to_monthly(df, assets, factors)
        log.info("monthly analysis frame: %d months x %d series", len(monthly), monthly.shape[1])

        # which (asset, factor) the dashboard actually ships: daily, significant
        cur = conn.cursor()
        cur.execute("SELECT asset, factor FROM sensitivity_results "
                    "WHERE freq='daily' AND pvalue <= %s", (ALPHA,))
        prod_sig = {(a, f) for a, f in cur.fetchall()}
        cur.close()

        result = validate(monthly, assets, factors, prod_sig)
        _summarize(result)
        if DRY_RUN:
            log.info("DRY_RUN — nothing written.")
            return 0
        _write(conn, result)
        return 0
    except MySQLError as e:
        log.error("DB error: %s", e)
        return 1
    finally:
        if conn is not None:
            conn.close()


# --------------------------------------------------------------------------- #
# Synthetic correctness check (no DB): a true signal must validate, a null must not.
# --------------------------------------------------------------------------- #
def selftest() -> int:
    rng = np.random.default_rng(7)
    T = 14
    x = rng.normal(0, 1, T)                       # a macro factor's monthly change
    months = pd.DataFrame({
        "Real_ret": 0.4 + 2.0 * x + rng.normal(0, 0.3, T),   # genuine beta ~ 2.0
        "Noise_ret": rng.normal(0, 1, T),                    # no relationship
        "SOME_chg": x,
    })
    res = validate(months, ["Real_ret", "Noise_ret"], ["SOME_chg"], prod_sig=set())
    log.info("SELFTEST result:\n%s", res.to_string(index=False, float_format=lambda v: f"{v:+.3f}"))
    real = res[res.asset == "Real_ret"].iloc[0]
    noise = res[res.asset == "Noise_ret"].iloc[0]
    ok = (real.verdict == "validated" and real.wf_r2 > 0 and real.wf_hit >= HIT_BAR
          and noise.verdict in ("in-sample only", "partial", "insufficient data")
          and (np.isnan(noise.wf_r2) or noise.wf_r2 < real.wf_r2))
    log.info("SELFTEST %s — true signal validated=%s (R2_oos=%+.3f), "
             "null not validated=%s (R2_oos=%+.3f)",
             "PASS" if ok else "FAIL", real.verdict == "validated", real.wf_r2,
             noise.verdict != "validated", noise.wf_r2)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())