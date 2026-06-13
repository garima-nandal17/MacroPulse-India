# MacroPulse India — Run Log & Decision Journal

## Purpose
Operational log of pipeline runs + a record of design decisions and bugs.
Source material for interview STAR stories and the Day-14 BRD.

---

## Manual fields to maintain
| Field | Current value | Last checked | Next review |
|---|---|---|---|
| RBI Repo Rate | 5.25% (neutral stance) | 2026-06-13 | MPC meeting 3–5 Aug 2026 |

---

## Decisions & rationale (the "why this, not that")
- **DECIMAL(12,4) over FLOAT for `value`** — float rounding is unacceptable
  for financial data; DECIMAL keeps exact precision. [your date]
- **UNIQUE(indicator, date) + ON DUPLICATE KEY UPDATE** — makes re-runs
  idempotent so the daily cron and backfill can't create duplicate rows. [date]
- **% change vs last two *trading* days, not calendar days** — yfinance returns
  no row on weekends/holidays, so calendar logic would break. [date]
- **Secrets in .env (gitignored), not in fetch.py** — required for safe
  GitHub Actions automation on Day 4. [date]

---

## Friction & fixes (raw STAR material)
| Date | What broke | Root cause | How I fixed it | What I'd do differently |
|---|---|---|---|---|
| [Day 1 date] | [e.g. duplicate rows on 2nd run] | [no unique key] | [added constraint + upsert] | [design schema constraints first] |

---

## Daily run log
| Date (IST) | Indicators inserted | Rows | Failures | Notes |
|---|---|---|---|---|
| [date] | USD/INR | 1 | 0 | Walking skeleton verified end-to-end |

## Decisions — Day 2
- Config-driven loop over INDICATORS (DRY) — add an indicator = one line.
- Per-indicator try/except (fault isolation) + per-indicator commit (durable partials).
- Backfill via executemany (batched writes); earliest day's pct_change = NULL (honest, not 0).
- monthly_indicators designed empty: period = reference month, release_date = when public
  (point-in-time / lookahead-bias defence). base_year nullable; column standardised to `indicator`.
- Logs to stdout (CI captures it) + a local file handler.

## Friction — Day 2
| Date | What broke | Fix |
|---|---|---|
| [date] | [e.g. ^TNX value 10x off] | [noted scale quirk, divide/flag] |

## Daily run log
| Date | Indicators | Rows | Failures | Notes |
|---|---|---|---|---|
| [date] | 8 daily | [n] | 0 | 2y backfill + monthly schema live |