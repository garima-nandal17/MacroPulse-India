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
## Day 3 — Monthly ingestion (CPI, IIP, Unemployment, RepoRate)

**Status:** Complete. 4 indicators in `monthly_indicators` via one pipeline
(`download_monthly → load_monthly`). 66 rows loaded (CPI 17, IIP 37, UR 11, Repo 1).

**Decisions**
- File-based monthly ingestion; retired the MoSPI API path (`fetch_monthly.py`).
  One loader ingests CPI/IIP/UR from files; RepoRate is a config constant.
- Grain guard: refuse to load unless exactly one row per (indicator, period).
- Column normalization on read: canonicalise headers (lower/trim, space→underscore)
  and coalesce duplicate variants — tolerates inconsistent/merged files.
- `release_date` derived: CPI +1mo/12th, IIP +2mo/12th, UR +1mo/15th.
- `base_year` tags: CPI=2024, IIP=2022-23, UR/Repo=NULL.
- Filter parsimony: filter only on columns that discriminate the headline series.

**Friction (STAR material)**
- MoSPI esankhyiki API abandoned after: TLS self-signed chain, `limit≤100`, CPI's
  `Level` param + 52k-row pagination (headline ~1 in 52k), undocumented IIP
  subcategory codes, PLFS calendar-vs-financial-year param → pivoted to files.
- PLFS dashboard export truncated to 2026 twice despite both years selected →
  manually consolidated two yearly exports into `plfs_master_manual.xlsx`.
- Merge introduced duplicate/variant headers, a stray header row, mixed types →
  hardened loader to normalize/coalesce.
- `year_type="Calendar Year"` filter silently deleted all 2025 rows (null in the
  2025 export; null ≠ "Calendar Year") → bisected the filter chain, removed the
  extraneous predicate. Classic AND-filter / NULL trap.
- `"rural + urban"` required exact spacing (vs guessed `"Rural+Urban"`).

**Known limitations**
- Monthly files = manual download (no stable automated source for current series).
- PLFS UR: 2026 Jan/Feb missing from source — backfillable (idempotent).
- CPI/IIP series cross base-year breaks.

**Data dictionary — `monthly_indicators`** (feeds Day-14 BRD)
- `indicator` — series name (CPI / IIP / Unemployment / RepoRate)
- `period` — reference month (DATE, 1st of month)
- `value` — indicator value (DECIMAL)
- `release_date` — date value became public (point-in-time key)
- `base_year` — index base (CPI 2024, IIP 2022-23; NULL for rate series)
- `source` — provenance (MoSPI / RBI)
- `fetched_at` — load timestamp
## Day 4 — Cloud migration & CI automation

**Status:** Complete. End-to-end pipeline runs unattended:
GitHub Actions → Python ETL → TiDB Cloud. No local-machine dependency.

**Decisions**
- Migrated the database from localhost MySQL to **TiDB Cloud** (`macropulse_india`):
  network-reachable + TLS, which unblocked runner-based automation.
- Runner = **GitHub Actions**.
  - `daily.yml`:   schedule `30 12 * * 1-5` (18:00 IST, Mon–Fri) + `workflow_dispatch`.
  - `monthly.yml`: `push` on `data/monthly_raw/**` + `0 8 13 * *` backstop + `workflow_dispatch`.
  - `concurrency` guards prevent overlapping runs; loads remain idempotent.
- **Committed monthly raw files** to the repo (reversed the earlier gitignore):
  the runner sees only committed state, and committed sources double as provenance.
- DB credentials via **repository secrets**; `requirements.txt` pinned (incl. `openpyxl`).

**Friction (STAR material)**
- First monthly run failed: `load_monthly.py` and the monthly raw files were untracked
  locally and never pushed, so the runner's checkout had nothing to load. Diagnosed via
  VS Code's untracked-files view, committed + synced, re-ran green.
  Lesson: "works locally" ≠ "works in CI" — the runner sees only committed state.
- TiDB's mandatory TLS flagged as a cross-environment risk: a hardcoded local CA path
  would fail on the Ubuntu runner; `ssl_ca` made env-configurable (`DB_SSL_CA`, default
  system bundle).

**Verification**
- `daily.yml` succeeded via `workflow_dispatch`; `daily_indicators` holds the 8 canonical
  indicators (9 rows incl. a legitimate earlier US10Y obs on 2026-06-12; `UNIQUE(date,
  indicator)` confirmed working).
- `monthly.yml` green after sync; `monthly_indicators` = 66 rows.
- TiDB queries confirm writes originated from GitHub Actions. Both workflows green.

**Known limitations**
- PLFS UR: 2026 Jan/Feb gap (source) — backfillable, idempotent.
- Monthly file download remains manual (commit-to-trigger ritual).
## Day 5 — Point-in-time feature layer

**Status:** Complete. Materialized `features_daily` in TiDB — a point-in-time feature
store with a built-in lookahead guardrail.

**Decisions**
- Built `build_features.py`: loads daily + monthly from TiDB, joins each monthly
  indicator onto the daily date spine via `pandas.merge_asof(direction="backward")`
  keyed on **`release_date`, not `period`** — each date sees only macro values public
  on or before it (no lookahead bias).
- Materialized as wide table `features_daily` (date PK + 8 daily + 4 monthly cols),
  full-refreshed each run (derived table → idempotent).
- Added a **lookahead audit** (first-known date vs earliest release per indicator),
  printed every run as an automated guardrail.

**Prerequisite resolved**
- Cloud `daily_indicators` held only 9 rows (history lived on the retired localhost DB).
  Re-ran `backfill_daily.py` → upserted ~4,000 rows; count 9 → 4,004.

**Verification**
- DRY_RUN: 521 rows × 13 cols, 2024-06-17 → 2026-06-16; lookahead audit OK for
  CPI, IIP, Unemployment, RepoRate.
- Materialized: `features_daily` = 521 rows × 13 cols; `COUNT(*)` confirmed.

**Known limitations**
- Feature store holds **levels**; monthly columns are forward-filled step functions,
  NaN before each indicator's first release (UR starts mid-2025; RepoRate is a single
  value). Returns/changes transform deferred to the analysis layer (Day 6).
- PLFS UR 2026 Jan/Feb gap persists upstream.