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
## Day 6 — Stationary analysis layer & sector sensitivity matrix

**Status:** Complete. Stationary feature layer + HAC-corrected sensitivity matrix in TiDB.

**Decisions**
- `transforms.py`: per-series stationarity transforms — price/index/FX → log returns;
  US10Y yield → first difference; CPI/IIP → MoM %; UR/RepoRate → Δ pp. Monthly changes
  taken at the release step and held constant (state encoding).
- `build_analysis.py`: derives `analysis_daily` from `features_daily`, applies the analysis
  window (rows begin where CPI/IIP/UR changes are all present), idempotent full-refresh.
- `sensitivity_matrix.py`: univariate OLS per (asset, factor); DAILY with Newey-West HAC
  errors (maxlags=21) against the step-function serial correlation; MONTHLY ordinary-OLS
  cross-check on month-end aggregates. Auto-detects assets (_ret/_diff) and factors (_chg);
  long-format results in `sensitivity_results`.

**Friction (STAR material)**
- `MIN_OBS` lowered 30 → 10 so the monthly validation (~13 obs) could run; daily HAC kept
  its larger sample. (Caveat retained: monthly betas are low-power.)
- pandas compatibility: `pd.to_numeric(errors="ignore")` removed in pandas 2.x → replaced
  with explicit per-column coercion.
- `RepoRate_chg` skipped gracefully (single value → zero variance in the window).

**Verification**
- `analysis_daily`: 261 observations (window correctly UR-bound, ~12 months).
- `sensitivity_results`: 48 rows = 8 assets × 3 factors (RepoRate skipped) × 2 frequencies.
- Daily and monthly beta matrices both generated.

**Methodology / caveats**
- Betas = conditional associations under state encoding, HAC-corrected — not causal impact.
- Univariate (not joint) to keep collinear macro factors interpretable.
- Small sample: read betas circumspectly; trust cells where daily HAC and monthly agree.

**Known limitations**
- RepoRate needs more rate-decision history to enter the matrix.
- PLFS UR 2026 Jan/Feb gap persists upstream.
- "Assets" are the 8 daily series; NSE sector indices can be added later (auto-detected).
# Day 6 — Completion Summary

**Objective:** Turn the point-in-time feature store into valid, stationary analysis and
produce the first sector-sensitivity matrix.

**Delivered**
- Stationary analysis layer (`analysis_daily`, 261 obs): returns/diffs for markets,
  release-step changes for macro — removing spurious level-on-level correlation.
- Sector sensitivity matrix (`sensitivity_results`, 48 rows): HAC-corrected daily betas
  plus a monthly cross-check, asset × macro-factor.

**What this demonstrates:** econometric rigor — stationarity transforms, point-in-time
discipline carried through, Newey-West inference for an autocorrelated regressor, and
multi-frequency robustness checks. Analysis built to survive scrutiny.

**Carried forward:** RepoRate sparsity; UR Jan/Feb gap; optional sector-index enrichment.

**Next (Day 7):** Predictive model on the leak-free feature set — walk-forward validated,
benchmarked against naive baselines, interpreted honestly.
## Day 7 — Sector Sensitivity Engine (correlations + serving layer)

**Status:** Complete. Reusable engine operational; serves the Impact Panel, What-if
Simulator, and AI Briefing.

**Decisions**
- `correlation_matrix.py`: Pearson + Spearman correlations, asset × macro-factor, daily +
  monthly, on analysis_daily → long table `correlation_results`. Companion to the betas.
- `sensitivity_engine.py`: a serving layer (no table) that reads `sensitivity_results` +
  `correlation_results` and exposes `sector_view`, `factor_view`, `correlation_matrix`,
  `project_impact`, `top_drivers`.
- `project_impact(shocks)` contract — per-asset response = Σ β·shock over **significant**
  betas (α=0.10) — is the dependency the What-if Simulator and Impact Panel build on.
- Coupling is via table names, not filenames: builders can change; the engine and consumers
  depend only on the `*_results` contracts.

**Verification**
- `correlation_results`: 96 rows = 8 assets × 3 factors (RepoRate skipped) × 2 methods × 2 freqs.
- Engine smoke test: `factor_view('CPI_chg')` ranked exposures; `project_impact({'CPI_chg':0.005})`
  returned projected responses; both result tables consumed correctly.

**Methodology / caveats**
- Betas = response magnitude/direction; correlations = co-movement strength (Pearson linear,
  Spearman monotonic) — complementary signals.
- `project_impact` filters to significant betas by default so noise doesn't drive projections;
  shocks are in each factor's own units. Small-sample caveats from Day 6 carry forward.

**Known limitations**
- RepoRate still excluded (no variance); enters once rate history grows.
- Projections are linear (β·shock); non-linear macro responses out of scope for now.
## Day 8 — Industry Impact Panel & analytics orchestrator

**Status:** Panel mechanism + rebuild orchestrator complete. Sector enrichment pending to
populate true industries (panel currently ranks market-context series).

**Decisions**
- `impact_panel.py`: first consumer of the Sensitivity Engine. Pulls the current macro state
  (latest `*_chg` from `analysis_daily`), runs `engine.project_impact(state)` over significant
  betas, attaches each target's top drivers, and ranks by implied-pressure magnitude. Framed
  as decision support ("given today's macro environment…"), not a forecast.
- `rebuild_analytics.py`: orchestrates the derived layer in dependency order —
  build_features → build_analysis → sensitivity_matrix → correlation_matrix — aborting on
  first failure. Raw ingestion stays upstream in its own workflows.
- `impact_panel_snapshot` table: current-state snapshot (asof_date, freq, asset,
  implied_response, direction, top_drivers), full-refreshed.
- Added `SECTOR_LABELS` display filter so the panel shows industries (Banks, IT, Pharma,
  Auto, FMCG, Realty, Metals, Energy) and sets market-context series aside; falls back
  gracefully (warns, shows all) until sector indices are ingested.

**Friction / key finding (STAR material)**
- Caught that the panel was an "Industry Impact Panel" only nominally — it ranked the 8
  market series (Gold, US10Y, Nifty50, …), of which only BankNifty is a true sector.
  Diagnosed as a DATA gap, not an engine flaw. Fix = sector enrichment + a display filter.
  **No `project_impact()` refactor needed** — the auto-detecting design absorbs new sector
  targets with zero engine change, validating the decoupled architecture.

**Verification**
- `rebuild_analytics.py` runs all four builders in order successfully.
- `impact_panel.py` DRY_RUN: current macro state pulled correctly; ranked output, driver
  attribution, significance filtering, and snapshot logic all work.

**Pending (to realize the true Industry Impact Panel)**
- Add NSE sector tickers to `fetch_daily.py` INDICATORS (NiftyIT `^CNXIT`, NiftyPharma
  `^CNXPHARMA`, NiftyAuto `^CNXAUTO`, NiftyFMCG `^CNXFMCG`, NiftyRealty `^CNXREALTY`,
  NiftyMetal `^CNXMETAL`, NiftyEnergy `^CNXENERGY`) — verify each returns history first.
- Then `backfill_daily.py` → `rebuild_analytics.py` → panel ranks true industries.

**Known limitations**
- Implied responses are directional/ordinal readings (linear projection, small sample),
  not point forecasts.
- RepoRate still excluded (no variance); small-sample caveats from Day 6 carry forward.
## Day 9 — What-if Scenario Simulator

**Status:** Complete. Second consumer of the Sensitivity Engine, validated.

**Decisions**
- `whatif_simulator.py`: applies hypothetical macro shocks via the engine's Σ β·shock
  contract (significant betas), returning ranked per-sector response + direction + dominant
  contributing factor. Linear projection → a scenario's response is its marginal impact, and
  multi-factor scenarios are additive.
- Predefined `SCENARIOS` library (Inflation shock, Disinflation, Growth surge, Industrial
  slowdown, Stagflation, Soft landing) + arbitrary custom shocks.
- `compare(scenarios)` → asset/sector × scenario matrix.
- `significant_only` toggle + `confidence` label (high/low): default projects only significant
  betas; labeled mode exposes fuller coverage without mistaking noise for signal.
- Reuses `SECTOR_LABELS` for industry display, with graceful fallback.

**Friction / key finding (STAR material)**
- Sparse output (NaNs) investigated, not assumed. Diagnostic SQL on `sensitivity_results`
  disaggregated the two possible causes — missing ingestion vs significance filtering — and
  confirmed **all 8 sectors are ingested**. Significance coverage: IT 3/3; FMCG/Metal/Nifty50
  1/3; Banks/Auto/Energy/Pharma 0/3. Conclusion: NaN = "present but no significant beta at
  α=0.10", not a bug. Day-8 sector enrichment thereby confirmed complete.

**Verification**
- No runtime/import/DB/schema errors; Stagflation scenario, comparison matrix, dominant-factor
  attribution, and confidence labels all function.

**Known limitations / usability**
- Sparse significance reflects limited power (~261-day / ~13-month window, gated by the UR
  start) + collinear factors — not a defect. Levers: longer window (gate on CPI/IIP only),
  more history.
- NaN in the matrix is not self-explaining; in this system it always means "no significant
  exposure" (all sectors present) — to be narrated explicitly by the Day-10 briefing layer.

  # Day 10: AI Briefing Engine

**Goal:** Turn the three decision-intelligence consumers into a written analyst briefing
— deterministic by default, optionally narrated by an LLM — without ever letting the
language layer touch the numbers.

## What shipped
- `brief_facts.py` — deterministic facts/payload assembler. Pulls current macro state
  (`ImpactPanel.current_state`), decomposes each sector's implied move into per-factor
  **contributions** (β×shock) and **shares**, attaches significance stars + an evidence
  tier, flags **outsized** macro inputs (>2σ vs `analysis_daily` history), builds a factual
  **headline**, and orders sectors by **evidence, then magnitude**. Pure data out.
- `ai_briefing.py` — narration layer. `render_template` (no API, always works,
  fully reproducible) and `render_llm` (optional Anthropic/Claude under a strict grounding
  prompt; graceful fallback to template if SDK/key missing or call fails).

## Decisions
- **Hard compute-vs-generate boundary.** The engine owns every number; the LLM owns only
  language. The grounding prompt forbids inventing/altering values and forbids implying
  missing data. This is what makes the briefing trustworthy rather than a confident fabrication.
- **Evidence-then-magnitude ordering** (not magnitude alone). Magnitude was promoting the
  least-robust readings (IT, Realty) to the top; ranking by evidence tier first demotes noise.
- **Evidence tier from the *dominant* driver**, not the best p-value across drivers — so a
  sector with a weak main driver and a tiny significant side-driver can't masquerade as robust.
- **Show contributions + shares, not raw betas**, in the panel — an analyst needs how much
  each factor moved the sector *this time*, not the coefficient.
- **Outsized-input flag** is a z-score (>2σ) against the factor's own history, not a hardcoded
  threshold — principled and self-calibrating.
- Default `BRIEFING_MODEL=claude-sonnet-4-6`; `USE_LLM=1` opt-in; `BRIEF_SCENARIO` optional.

## Friction (STAR)
- **S/T:** First template draft was internally correct but analyst-hostile: it printed raw
  betas as "drivers," ranked by magnitude, and used tiny unlabeled decimals — so its most
  prominent reading (IT, up) was also its least trustworthy (β=+0.71 to CPI, p=0.048).
- **A:** Reviewed economic correctness separately from arithmetic. Math verified (IT sum =
  +0.0076 ✓). Found FMCG (defensive, p=0.000) and Metals (cyclical, p=0.023) coherent and
  significant; IT and Realty resting on marginal, counterintuitive betas. Rebuilt the facts
  layer to disaggregate contributions, surface significance, order by evidence, label units
  as %, collapse no-exposure sectors, and flag the outsized IIP input (−9% MoM, ~−3σ).
- **R:** The fragile readings are now explicitly tagged `[Weak/Moderate evidence]` and sit
  below the `[Strong]` reading; the headline leads with the strongest-evidence sector.

## Verification
- `python -m py_compile brief_facts.py ai_briefing.py` → clean.
- Rendered the enriched template against the live run numbers: headline + outsized ⚠ line +
  per-driver contribution/share/β/p/stars + collapsed no-exposure line all correct.
- Confirmed graceful fallback: with `ANTHROPIC_API_KEY` unset, `USE_LLM=1` logs a warning
  and falls back to the deterministic template (identical numbers).

## Known limitations
- Readings are implied **daily** returns — directional/ordinal, not point forecasts.
- Linear projection (β×shock); non-linear macro responses not captured.
- Small sample (~261 daily / ~13 monthly obs); evidence ordering mitigates but doesn't remove
  the noise risk. Several sector betas remain economically counterintuitive — flagged, not fixed.
- The outsized-IIP flag is a data-quality prompt, not a correction; the −9% MoM input still
  needs a base/seasonal sanity-check upstream.

**Status: Day 10 complete.** Three consumers (Impact Panel, What-if Simulator, AI Briefing)
are all serving from the engine. Next: surface them in an interactive dashboard.
# RUNLOG — Day 11: Decision-Intelligence Command Center (Streamlit)

**Goal:** Surface the three serving-layer consumers (Impact Panel, What-if Simulator,
AI Briefing) as a premium, decision-first product — not a research notebook — without
touching the engine, schema, payload contracts, or identifiers.

## What shipped
- `streamlit_app.py` — single-scroll dark command center. Hierarchy: live market ribbon →
  hero regime → release-stamped KPI cards → daily Morning Brief → signal-quality panel →
  winners/losers → scenario intelligence → business interpretation → methodology.
- `.streamlit/config.toml` — dark theme (page background was the "unfinished" culprit).
- `brief_facts.py` — backward-compatible payload ADDITIONS only: `regime`, `regime_badge`,
  `confidence`, `macro_cards` (level/base/period/release_date/computed YoY), `market_ribbon`,
  `market_asof`. No renames, no schema or engine change.

## Decisions
- **Hard presentation/engine separation.** Every number rendered comes from the same
  `assemble()` payload the CLI uses; the dashboard recomputes nothing.
- **Two-clock design.** A live daily market ribbon (fast clock) sits above the release-stamped
  monthly regime (slow clock); each carries its own as-of so neither masquerades as live.
- **One source of truth.** The command center always pulls the daily payload (the validated
  path); the frequency control affects only research/sim.
- **Release-context KPIs.** CPI/IIP as computed YoY over index + base + release period + MoM
  model input; unemployment as the rate. Level vs change vs daily vs monthly never ambiguous.
- **Evidence-weighted everywhere.** Ordering, confidence badges, and the brief's
  "highest-conviction" lead use the dominant-driver evidence tier, not magnitude — so the
  loudest reading never outranks the best-evidenced one (FMCG leads, not the larger IT move).
- **Decision-first hierarchy.** p-values, betas, R², correlations, and the α/frequency controls
  live only in a collapsed "Methodology & validation" section and the collapsed sidebar.
- **Daily-led Morning Brief.** Rebuilt from a static monthly restatement into a synthesized
  daily note: market lede → regime backdrop → the model's read → daily-tone tilt → watch item
  → confidence-with-basis. This is the "not-Gemini" surface — it reads the live tape and the
  proprietary sensitivity signal, not public headlines.
- **Show, don't tell.** Briefing detail and business interpretation carry Plotly charts
  (sector-pressure diverging bars; per-factor contribution decomposition) that re-render with
  the data, replacing regression-text dumps.

## Friction (STAR)
- **S/T — silent CLI/dashboard divergence.** The dashboard read "no significant exposure" while
  the CLI showed FMCG/IT/Metals/Realty.
- **A.** Traced it: identical `assemble()` call, so the cause was environmental — an empty
  `analysis_daily` read returns `({}, None)` from `current_state()`, which `_decompose` turns
  into all-no-exposure, rendered identically to a real null. Three failure modes isolated:
  stale `@st.cache_data`, `freq="monthly"`, and the silent-empty itself.
- **R.** Pinned the command center to daily, added a self-healing cache clear on empty reads,
  and split the empty state into an explicit data/connection error vs a genuine
  "no significant exposure." One source of truth restored.
- **Second loop — describe vs reason.** Review feedback: the brief restated monthly facts a
  generic LLM could produce, and the "full briefing" expander dumped β/p-value text. Rebuilt the
  brief to lead with the daily tape and surface the proprietary read; replaced text with
  data-driven charts; corrected the IIP card ("momentum rolling over" from MoM, not the
  contradictory YoY "positive"); fixed light-on-dark dropdowns and expander headers.

## Verification
- `py_compile` clean across `streamlit_app.py`, `brief_facts.py`, `ai_briefing.py` at every step.
- **Cross-surface reconciliation:** brief, KPI cards, sector-pressure chart, contribution
  decomposition, and signal-quality panel all tie out — e.g., IT +0.76% = CPI(+0.54) + IIP(+0.26)
  − Unemployment(0.04); "6 significant relationships / 261 observations" identical brief↔panel;
  IIP −9.03% MoM consistent card↔brief.
- Every presentation helper unit-checked in isolation against live-shaped payloads (regime pills,
  KPI interpretations, morning-brief synthesis, signal counts, both chart builders, empty guards).

## Known limitations
- **No out-of-sample validation yet.** Sensitivities are in-sample; a hold-out/backtest of whether
  they actually predict is the single highest-value next analytical step.
- **Two narrative-vs-driver gaps, flagged via low confidence (not hidden):** Realty's generic
  "financial conditions ease" story doesn't match its actual driver (a negative IIP beta) this
  regime; IT's headline magnitude rests largely on a marginal CPI beta (p≈0.05). Both are
  de-emphasized by the evidence ordering and confidence badges; the decomposition chart shows
  IT's CPI dependence explicitly.
- **Streamlit styling ceiling** (~85–90% of a bespoke React build); the final chrome slice would
  need Path B (React + FastAPI), parked as a post-offer stretch.

**Status: Day 11 ✅ complete.** The platform presents as a decision-intelligence command center,
internally consistent and analytically honest. Next: out-of-sample signal validation, then the
narrative layer (README, BRD, demo script) that makes the rigor legible to a two-minute reviewer.
# RUNLOG — Day 12: Out-of-Sample Validation + AI Copilot Explanation Layer

**Two goals this day.** (1) Answer the question the platform had dodged — *do the signals hold
out of sample, or are they in-sample artifacts?* (2) Close the usability gap so a non-economist
(student, recruiter, manager) can understand every concept without leaving the page.

## What shipped
- `validate_signals.py` — monthly, point-in-time, walk-forward + holdout out-of-sample validation;
  writes the `signal_validation` table; ships a synthetic self-test.
- `streamlit_app.py` — (a) AI copilot explanation layer: ten section popovers with a custom glyph
  and plain-English *concept → meaning → business implication* panels; (b) validation integration:
  verdict chips on winner/loser cards, a Signal-Quality headline, a Methodology validation table,
  and copilot notes.

## Decisions
### Out-of-sample validation
- **Monthly, not daily.** The `*_chg` factors are month-level step functions broadcast across ~21
  daily rows; a daily split would leak the same constant factor value into train and test and
  pseudo-replicate ~21x, faking a good OOS score. Validating on month-end aggregates — reusing
  `sensitivity_matrix.to_monthly` verbatim — gives genuinely independent observations.
- **Same model as production.** Univariate OLS `r_i = a + b*m_j`; HAC affects only standard errors,
  not the beta point estimate, so the coefficient validated is the one the product ships.
- **Two tests:** holdout (first ~70% of months vs last ~30%) and expanding-window walk-forward
  (one-step out-of-sample at each step).
- **Honest metric.** Campbell-Thompson OOS R² vs a naive train-mean benchmark (can go negative =>
  worse than guessing the average), directional hit-rate on demeaned moves, and beta sign-stability.
  A signal is "validated" only if it clears all three bars; tiers are validated / partial /
  in-sample only / insufficient.

### AI copilot explanation layer
- **Curated knowledge layer, not live LLM.** Concept definitions are stable, so curated text is
  instant, vetted, hallucination-free, and needs no API key for a recruiter to try every panel. The
  live-generation hook remains in `ai_briefing.py`.
- **Native `st.popover`, not raw HTML.** The first implementation used HTML `<details>` + inline
  `<svg>`; Streamlit's sanitizer strips both, so nothing rendered. Rebuilt on `st.popover`
  (sanitizer-proof), with the custom glyph delivered via a CSS background-SVG (also sanitizer-proof)
  and a version-proof fallback to `st.expander`.
- Every panel follows *concept → plain-English meaning → business implication*; the regime panel is
  generated dynamically so it always matches the live pills.

### Validation → dashboard integration
- **Chips on the cards**, keyed to each sector's dominant driver's verdict — putting the two
  witnesses (in-sample confidence + out-of-sample robustness) side by side where the call is made.
- Signal-Quality headline ("N of M validated out-of-sample"), Methodology table, copilot notes.
- **Graceful degradation:** if `signal_validation` isn't built, chips silently omit and the
  dashboard is unaffected.

## Friction (STAR)
- **AI layer rendered no icons at all.** *A:* diagnosed Streamlit's `st.markdown` sanitizer stripping
  `<details>`/`<summary>`/`<svg>` (the rest of the dashboard survives because it's `<div>`/`<span>`).
  *R:* rebuilt on `st.popover`, moved the glyph to a CSS background-SVG, added an `st.expander`
  fallback. Icons now render and open glowing panels.
- **Validation first run broke on data prep.** Deprecated `pd.to_numeric(..., errors="ignore")` under
  current pandas, plus a `date`→NaT coercion that broke monthly aggregation. *R:* preserved the
  `date` column during numeric coercion; validation then ran clean on the real data through the
  production `to_monthly`.

## Verification
- **Self-test (no DB):** a true signal (β≈2) validates (OOS R²≈+0.96, hit 0.88); pure noise does not
  (OOS R²≈−0.62, hit 0.25). The negative OOS R² on noise confirms the metric exposes in-sample-only
  signals.
- **Real run (11 shipped signals):** 3 validated, 8 partial, 0 in-sample only. **FMCG×IIP — the
  dominant driver behind the headline call — validated.** Nifty50×IIP validated (wf_r² +0.107, 86%
  hit). **IT×IIP holdout R²≈−24 with stable sign and decent direction => IT's direction is
  trustworthy but its magnitude is not** — evidence-backed confirmation of the IT caution previously
  only suspected.
- **Dashboard:** `py_compile` clean; asset→sector mapping and chip rendering unit-tested
  (FMCG→validated chip, IT→partial chip, unknown sector→no chip, empty table→graceful).

## Known limitations
- **n ≈ 13 monthly observations** — an early robustness read, not proof. "0 in-sample-only" is partly
  an artifact of the small sample plus the lenient "partial" bucket; the metrics will sharpen as
  history accrues. The defensible claim is "no shipped signal failed outright, and the most-relied-on
  signal validated," not "everything is proven."
- Validation is of **contemporaneous sensitivities** (stability / generalization), not lead-lag
  forecasting skill.
- Streamlit popover *surface* styling is best-effort across versions; the panel *content* is
  high-contrast regardless.

**Status: Day 12 ✅ complete.** The platform now validates its own signals out-of-sample and explains
every concept in plain English. Next (roadmap): Power BI; the Day-14 BRD; README + demo script +
portfolio storytelling.