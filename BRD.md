# Business Requirements Document (BRD)
## MacroPulse India — Macroeconomic Decision-Intelligence Platform

| | |
|---|---|
| **Document** | Business Requirements Document |
| **Product** | MacroPulse India |
| **Version** | 1.0 |
| **Author** | Garima Nandal |
| **Status** | Baseline (Phase 1 complete) |
| **Audience** | Product stakeholders, analytics reviewers, hiring panels |

---

## 1. Executive summary

MacroPulse India is a self-updating **macroeconomic decision-intelligence platform** that ingests India's live macro and market data, estimates how equity **sectors** respond to macroeconomic conditions, **validates those signals out-of-sample**, and explains every concept in plain language for non-specialists.

The core business problem it addresses is that macroeconomic data is **abundant but illegible**: decision-makers can observe that inflation is rising or industrial output is falling, but translating that into *"which sectors are favoured or exposed, and how confident should we be?"* requires economics fluency, statistical modelling, and continuous manual updating that most teams do not have.

MacroPulse converts that raw data into three decisions a stakeholder actually needs — **where the economy is, what it means for sectors, and what would happen under a different scenario** — and is deliberately bounded as *decision support*, not market-price prediction. This document specifies the business context, users, scope, functional and non-functional requirements, success metrics, and acceptance criteria for Phase 1.

---

## 2. Business background & problem statement

### 2.1 Context
Indian macroeconomic indicators (CPI, IIP, unemployment, policy rates) and market series (the rupee, equity indices, commodities, volatility, global rates) are published continuously but in fragmented, technical forms. Interpreting their *combined* effect on specific industry sectors is a specialist task performed manually by economists and strategy analysts.

### 2.2 Problem statement
There is no accessible tool that (a) continuously aggregates these indicators, (b) maps them to sector-level implications using a transparent, statistically defensible method, (c) states **how trustworthy** each implication is, and (d) communicates the result to a **non-economist**. Existing options are either expensive professional terminals (powerful but opaque and jargon-heavy) or static research notes (readable but not live, not interactive, and not self-validating).

### 2.3 Opportunity
A lightweight, explainable, continuously-updating platform that turns macro data into *trust-rated, plain-language sector intelligence* serves analysts who need speed, managers who need clarity, and learners who need to understand the reasoning — without the cost or opacity of professional terminals.

---

## 3. Objectives & business value

| # | Objective | Business value |
|---|---|---|
| O1 | Continuously translate live macro data into sector-level implications | Reduces time-to-insight from manual analysis (hours) to seconds |
| O2 | Quantify confidence in every signal via out-of-sample validation | Lets users distinguish *trustworthy* calls from *speculative* ones — reduces decision risk |
| O3 | Make every concept understandable to a non-economist | Widens the usable audience from specialists to managers, students, and stakeholders |
| O4 | Support forward-looking "what-if" analysis | Enables scenario planning and stress-testing before events occur |
| O5 | Operate automatically with minimal maintenance | Keeps intelligence current without analyst effort; ensures freshness |

---

## 4. Stakeholders & user personas

### 4.1 Stakeholders
| Stakeholder | Interest |
|---|---|
| Product owner / analyst (builder) | Delivers accurate, defensible, maintainable intelligence |
| End users (below) | Consume sector intelligence to inform decisions |
| Data providers (MoSPI, market sources) | Source-of-record for indicators |
| Reviewers (hiring panels, admissions) | Assess analytical rigour and communication |

### 4.2 User personas
**P1 — Strategy / business analyst.** Needs a fast, defensible read on which sectors the current macro environment favours, with the underlying evidence available on demand. Values the sensitivity engine, the methodology layer, and the validation chips.

**P2 — Non-specialist manager / decision-maker.** Understands business but not econometrics. Needs the *implication* in plain English and a confidence cue, not regression output. Values the AI briefing, the copilot explanations, and the winners/under-pressure cards.

**P3 — Finance student / curious learner.** Wants to understand both the conclusions *and* the reasoning. Values the copilot's concept→meaning→implication explanations and the transparent methodology.

**P4 — Platform maintainer.** Needs the pipeline to run automatically, fail safely, and surface data issues clearly. Values CI automation, idempotent ingestion, and graceful degradation.

---

## 5. Scope

### 5.1 In scope (Phase 1)
- Automated daily and monthly ingestion of defined macro/market indicators.
- Point-in-time feature engineering and a stationary analysis layer.
- Sector-sensitivity estimation (macro→sector) with significance testing.
- Out-of-sample validation of sensitivity signals with trust ratings.
- What-if scenario simulation.
- AI-generated plain-language analyst briefing.
- AI copilot explanation layer across the dashboard.
- A deployed, single-page decision-intelligence dashboard.

### 5.2 Out of scope (Phase 1)
- Market-price or return **forecasting** as a product (predictive components are bounded rigor demonstrations only).
- Individual-stock recommendations or any buy/sell advice.
- Real-time intraday tick data.
- User accounts, personalisation, or portfolio tracking.
- Mobile-native application.

---

## 6. Functional requirements

> Priority uses MoSCoW: **M**ust / **S**hould / **C**ould.

| ID | Requirement | Priority | Acceptance criteria |
|---|---|---|---|
| FR-1 | Ingest defined **daily** market & macro series and persist them | M | Scheduled job writes the day's values to the database; reruns are idempotent (no duplicates) |
| FR-2 | Ingest defined **monthly** official releases (CPI, IIP, unemployment, repo rate) | M | Monthly job upserts each release; missing-source handled without crashing |
| FR-3 | Align monthly releases by **actual release date** (point-in-time) | M | Features never include a release before its public availability date (lookahead-audited) |
| FR-4 | Produce a **stationary** analysis layer (returns / diffs / changes) | M | Analysis table contains transformed series; no level-on-level modelling |
| FR-5 | Estimate **macro→sector sensitivities** with significance | M | Per (sector, factor) beta, p-value, R², n produced; HAC errors on daily frequency |
| FR-6 | Classify the **current macro regime** | M | Dashboard shows a regime label derived from current factor signs |
| FR-7 | Identify **beneficiary** and **under-pressure** sectors with a confidence tier | M | Each active sector shown with direction + evidence tier; non-significant sectors shown as "no exposure" |
| FR-8 | **Validate signals out-of-sample** and assign a verdict | M | Each signal labelled Validated / Partial / In-sample-only via walk-forward + holdout |
| FR-9 | Surface validation verdicts in the dashboard | M | Trust chips appear on sector cards; a summary appears in the signal-quality panel |
| FR-10 | Provide a **what-if** scenario simulator | S | User selects macro shocks in plain language; projected sector responses returned |
| FR-11 | Generate a plain-language **analyst briefing** | S | A daily note synthesises market tape + regime + model read with an explicit confidence statement |
| FR-12 | Provide an **AI copilot** explanation for every major section | S | Each section exposes a concept→meaning→implication explanation panel |
| FR-13 | Expose a **methodology / audit** view | S | Betas, p-values, R², correlations, and the validation table available on demand |
| FR-14 | **Auto-refresh** via scheduled automation | S | CI jobs run on schedule and update the stack without manual intervention |
| FR-15 | Allow a custom macro-shock builder | C | User defines arbitrary factor changes and sees projected impacts |

---

## 7. Non-functional requirements

| ID | Category | Requirement |
|---|---|---|
| NFR-1 | **Reliability** | Ingestion is idempotent and self-healing; a transient source failure degrades gracefully rather than corrupting the store |
| NFR-2 | **Data integrity** | No lookahead: point-in-time alignment is auditable; stationarity enforced before modelling |
| NFR-3 | **Performance** | Dashboard renders the full decision view within a few seconds on cached data |
| NFR-4 | **Usability** | Core conclusions are intelligible to a non-economist without leaving the page |
| NFR-5 | **Transparency** | Every surfaced claim is traceable to its evidence (significance, validation verdict) |
| NFR-6 | **Maintainability** | Layered, independently-testable modules; presentation isolated from the analytical engine |
| NFR-7 | **Graceful degradation** | Optional layers (e.g. validation, AI narration) absent → product still functions |
| NFR-8 | **Security** | Database credentials supplied via environment configuration, never hard-coded; TLS in transit |
| NFR-9 | **Honesty** | Statistical limitations (e.g. small sample) are stated in-product, not hidden |

---

## 8. Data requirements

| Domain | Series | Frequency | Source |
|---|---|---|---|
| Currency / rates | Rupee (USDINR), US Dollar Index, US 10Y | Daily | Market data |
| Equity | Nifty 50, Bank Nifty, 7 NSE sector indices | Daily | Market data |
| Commodities / risk | Brent crude, gold, India VIX | Daily | Market data |
| Macro releases | CPI, IIP, Unemployment (PLFS) | Monthly | MoSPI |
| Policy | RBI repo rate | On change | RBI |

**Data quality rules:** releases aligned by public release date; values upserted (no duplicates); stationarity transforms applied before analysis; minimum-observation thresholds enforced before a relationship is reported.

---

## 9. Assumptions & constraints

**Assumptions**
- Public macro/market sources remain available at their stated cadences.
- Historical relationships carry *some* informational value for sector positioning (the platform measures and validates this rather than assuming it).

**Constraints**
- Macro history is short (≈13 monthly observations), bounding the strength of out-of-sample claims.
- Monthly macro factors are step-functions across daily rows, constraining valid daily-frequency inference (addressed via HAC errors and monthly-level validation).
- Single-maintainer project; scope intentionally bounded to ensure depth over breadth.

---

## 10. Success metrics (KPIs)

| Metric | Definition | Target / intent |
|---|---|---|
| **Time-to-insight** | Time for a user to read the current macro regime + favoured/exposed sectors | Seconds (vs hours of manual analysis) |
| **Signal trust coverage** | Share of shipped signals carrying an out-of-sample verdict | 100% of production signals validated and labelled |
| **Validated-signal ratio** | Share of shipped signals rated Validated / Partial vs failing | No shipped signal fails outright; headline driver validated |
| **Comprehension** | A non-economist can state what the regime means after using the copilot | Achievable without external help (qualitative) |
| **Data freshness** | Lag between source release and dashboard reflection | ≤ one scheduled cycle |
| **Pipeline reliability** | Successful automated refreshes | No silent corruption; failures surfaced |

---

## 11. Acceptance criteria (Phase 1 done-definition)

Phase 1 is accepted when: the pipeline ingests and refreshes the defined series automatically (FR-1, FR-2, FR-14); features are point-in-time and stationary (FR-3, FR-4); the sensitivity engine produces significance-tested betas (FR-5); the dashboard shows the regime, beneficiary/under-pressure sectors with confidence, and validation chips (FR-6–FR-9); the what-if simulator, analyst briefing, and copilot are live (FR-10–FR-12); every signal carries an out-of-sample verdict (FR-8); and the product degrades gracefully when optional layers are absent (NFR-7). **All criteria are met as of Version 1.0.**

---

## 12. Risks & mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Short macro history weakens validation | Over-claiming robustness | State the limitation in-product; treat as a probe; framework sharpens as data accrues |
| Source API changes / outages | Stale or missing data | Idempotent, self-healing ingestion; auto-discovery of API parameters; graceful failure |
| Users misread it as buy/sell advice | Misuse | Explicit "decision support, not advice" framing throughout |
| Spurious correlation | Misleading signals | Stationarity, significance-as-abstention, and out-of-sample validation as three independent checks |
| Jargon excludes non-specialists | Limited adoption | AI copilot translation layer on every section |

---

## 13. Future considerations

- Macro-regime classifier (label the environment directly from factors).
- Macro-surprise modelling (actual vs consensus reactions).
- Expanded macro history to strengthen out-of-sample evidence.
- Additional sector and factor coverage as data permits.

---

## 14. Glossary

| Term | Plain-language meaning |
|---|---|
| Macro regime | The current economic environment (e.g. slowing growth + rising prices) |
| Sensitivity (beta) | How strongly a sector has historically moved with a macro factor |
| Point-in-time | Using only information that was publicly available at the time — no hindsight |
| Stationary | Data transformed (changes, not levels) so relationships aren't spurious |
| Out-of-sample validation | Testing a signal on data the model never trained on |
| Defensive sector | Businesses whose demand is stable through downturns (e.g. food, essentials) |
| Cyclical sector | Businesses whose demand rises and falls with the economy (e.g. metals) |

---

*End of Business Requirements Document — MacroPulse India v1.0.*