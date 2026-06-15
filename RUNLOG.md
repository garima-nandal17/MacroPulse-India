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