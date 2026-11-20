# Buyer Early Warning Agent — Implementation Plan

> **HACKATHON PROTOTYPE · SYNTHETIC DATA**

**This is the specification the code was built from.** It is the plan as it stood
*after* a gap analysis against the real dataset — the Recovery Challenger retired,
news decay added with a measured half-life, the As-Of Clock dropped, parent
contagion and entity-resolution decoys added to the data, and the harness, case-file
guard and LLM integration specified (D9–D11). Every number in it was measured
against the shipped CSVs before a line of engine code existed.

Built and verified: **8/8 harness gates, 79/79 tests**, on both the rule-based
path and the four agents running on Claude. See *As built* at the end.

**Superseded in one place, deliberately.** The agents described in D1/D4/D11 were
originally fixed prompt calls. They are now **autonomous agents** — each gets read-only
tools over the engine's data, decides what to look at, and ends by calling a `submit_*`
tool the code validates. **D12 records that change and what it was not allowed to
touch.** Every other decision here still describes the code as built.

## Context

Credit insurance hackathon; the best agent wins. No business data: the proof of
concept runs on the supplied synthetic CSV dataset (`files_small_demo.zip`, extracted
into `data/`). The agent watches every covered buyer and flags early signs of
default, before the insurer's own underwriter would notice.

Two signals: **payment behaviour** (internal) and **news** (external, including news
about a buyer's parent company).

Intended outcome: a reproducible, auditable engine plus a dashboard that tells the
story live in a room — the audience watches a score move as news and payment data
change.

## The dataset in one screen

20 buyers, 3 insurers (Adlerhof Trade Credit, Solvenza Trade Credit, Nordhaven),
20 credit-limit lines (**one per buyer** — every buyer has exactly one insurer),
120 invoices (75 Open, 45 Paid), 27 news articles (2024-07 → 2026-06), 4 parent
companies. Snapshot **2026-09-25**; every insurer uses a 30-day overdue reporting
window.

| Class | Count | Buyers |
|---|---|---|
| Defaults (`gradual`) | 4 | Arcline, Halberg, Maasland, Emberline |
| `wobble_recovered` | 4 | Prevost Prime, Bluestone, Rheinfels, Westbridge |
| `healthy` | 12 | includes the 5 boundary buyers and Vandermeer |

Buyers per insurer: Adlerhof 11, Solvenza 6, Nordhaven 3.

| File | Role |
|---|---|
| `clients`, `buyers`, `credit_limits`, `invoices`, `news_articles`, `parent_companies` | engine inputs |
| `ground_truth`, `payment_behaviour_monthly` | **harness-only** |
| `harness_articles` | **harness-only** — labelled stories the shipped news lacks (the parent story, two decoys), handed to the engine label-stripped |

**Baseline result (measured, with the D5 decay applied):** Arcline 63.3 and Maasland
62.2 in High Risk; Halberg 42.7 and Emberline 37.2 in Watch; all 22 survivors Healthy.
**4/4 caught, 0 false positives.** On Claude the same four are flagged, Maasland at
66.9 — see *As built*.

⚠ **Emberline sits 2.2 points above the Watch line.** Decay costs it most (its worst
article is 320 days old), so any change to the half-life, the news ladder or the 65/35
split must be re-checked against Emberline first — it is the binding constraint.

---

## Decisions

### D0 — Architecture

A deterministic spine, agents at the leaves, one typed Evidence Store.

```
   TIER 1  EVIDENCE   Payment  (ledger in code; agent reviews the trend)
        │             News & Parent  (agent per article; parent news fans out
        │               to subsidiaries via parent_companies)
        │             — evidence producers NEVER score risk
   EVIDENCE STORE     typed, dated, source-cited
        │
   TIER 2  JUDGMENT   Risk Score formula (D5) + bands (D8) — in code, the only
        │             number in the system; Adjudicator agent reviews, cannot change
   TIER 3  ACTION     Limit recommendations (D6) → Case File agent → dashboard
                      Harness grades every run against the labels (D9)
```

- Orchestrator is **code, not an LLM** — it runs the agents in a fixed order.
- **No As-Of Clock.** The dataset is a single snapshot at 2026-09-25 and every row
  precedes it, so date filtering never fired. The loader simply loads. *(Retired —
  it was scaffolding for a replay feature this plan does not have.)*

### D1 — Four agents  *(revised by D12)*

| # | Agent | Decides | What stays in code |
|---|---|---|---|
| 1 | Payment Behaviour | settlement trend and concerns | the ledger: the worst Open invoice is the score input, never the model's |
| 2 | News Intelligence | which entity an article is about, and its severity | the entity registry and the parent fan-out |
| 3 | Risk Adjudicator | agree / caveats / challenge, with cited evidence | the score formula and the bands — the agent cannot change either |
| 4 | Case File | the draft case file an underwriter reviews and approves | every figure it writes is checked; a bad draft is sent back, then templated |

*Originally three, each a fixed prompt call. See D12.*

**Retired: Recovery Challenger.** It asks "is this a wobble?", which needs history.
There is one snapshot and D8 has no persistence, and all four wobblers score Healthy
so it would never be invoked on them — its only possible task was arguing against
four correct flags.

Not agents: Case File Writer (LLM call), dashboard, harness.

### D2 — Payment agent is deterministic

Reads the supplied `days_past_due` on the buyer's **Open** invoices and takes the
highest. Per-insurer findings are kept as evidence; the buyer's payment input is the
**worst line**. A buyer with no Open invoices scores DPD 0.

### D3 — The warning product

Money at risk: `EL = PD × min(max_liability, limit × indemnity × (1 − deductible))`
per line. PD is a credit-risk prior on the Risk Score, **linearly interpolated**
between (0, 1%), (20, 10%), (55, 45%), (80, 85%), (100, 95%). Not fitted.

Dashboard: see **Frontend**, plus a **live input sandbox** (type a story, age an
invoice, re-run). Every alert states why it fired and what would lift it.

### D4 — News reliability

**Direct buyer news.** Entity resolution is the primary defence and is **reluctant**:
the brand token must match and every distinguishing token must be part of that
entity's own name; ambiguity refuses. Each accepted article gets a severity of
**0, 3, 4 or 5**.

*(D12: resolution and grading are now one agent run per article rather than two fixed
prompts. The reluctance rule is unchanged — it is written into `agents/news.md`, and
the `entity_must_be_looked_up` guardrail means a submitted id must have come back from
a tool call in that same run, so an id cannot be invented. The rule-based resolver
remains the offline path and is what the harness measures.)*

**Parent news.** Parent articles resolve to the parent, then fan out to every
subsidiary through the `parent_companies` graph — the lookup is deterministic, the
assessment is the agent's. A parent story **steps down one rung of the severity ladder**
for each subsidiary:

| Parent severity | Subsidiary severity |
|---|---|
| 5 | 4 |
| 4 | 3 |
| 3 | — (no contribution) |

No new multiplier: a parent in trouble is a *moderate* concern for the subsidiary,
not a severe one, and the step-down says so on the same scale the agent already uses.

**News alone never leaves Healthy** — max contribution is 0.35 × 75 = 26.25.

### D5 — Risk Score formula (65 / 35), with news decay

```
Risk Score = (0.65 × Payment Score) + (0.35 × News Score)

Payment Score (DPD = highest days_past_due on the buyer's Open invoices):
  DPD ≤ 30:  (DPD / 30) × 40
  DPD > 30:  40 + min(60, (DPD − 30) × 2)

News Score = max over the buyer's articles (own news and stepped-down parent news) of:
      base(severity) × 0.5 ^ (age_in_days / 365)

  base:  0 Neutral / Positive  →  0
         3 Mild Negative       → 20
         4 Moderate Negative   → 45
         5 Severe Negative     → 75
```

The 30-day knee matches every insurer's overdue reporting window. Payment reaches its
cap of 100 at 60 DPD.

**The 365-day half-life is measured, not assumed.** Without decay, Vandermeer's
severity-5 wage story from 2024-10-15 is **710 days old** and carries full weight —
the trap survives only because Vandermeer has no overdue invoices, and **11 days past
due flips it to Watch**. Sweeping half-lives against the labels:

Re-measured on the current 26-buyer dataset (4 defaults, 22 survivors); the choice is
unchanged from when it was first swept at 20 buyers.

| Half-life | Defaulters flagged | Survivors clean | Trap tolerance |
|---|---|---|---|
| none | 4/4 | 22/22 | 11 DPD |
| 180 d | **3/4** (Emberline missed at 33.2) | 22/22 | — |
| 240 d | **3/4** (Emberline missed at 34.9) | 22/22 | — |
| 270 d | 4/4 | 22/22 | 35 DPD |
| **365 d** | **4/4** | **22/22** | **32 DPD** |
| 540 d | 4/4 | 22/22 | 29 DPD |

365 days keeps the result and widens the trap's margin threefold. Anything under
270 days breaks Emberline.

**A relevance horizon on top of the decay.** Decay alone never reaches zero: a
four-year-old severity-5 story still carries **1.64 points**, and that is enough to
push a buyer sitting at 58.5 (Watch, on payment alone at 55 DPD) to 60.1 — into High
Risk on a story from 2022. An underwriter would not weigh that story at all, so:

- **Nothing older than `NEWS_MAX_AGE_DAYS = 730` is read.**
- It **fades** over its final `NEWS_FADE_DAYS = 180` rather than dropping off a
  cliff, so no buyer improves overnight because an article crossed the horizon.
  A severity-5 story is worth 9.2 points at 550 days, 3.4 at 650, 0.04 at 729.
- **News dated after the run scores zero.** The As-Of Clock was retired (D0) because
  the dataset never needed it, which left nothing to stop a future-dated article
  scoring at full weight — the live-ingest panel accepts a typed date. `decay()`
  now refuses a negative age.

### D6 — Limit recommendations (expected-loss based)

One recommendation per insurer line, from the D3 expected-loss formula — no bands.
Deterministic, no LLM. Every recommendation awaits an underwriter and is carried into
the Case File.

```
PD_target      = PD at Risk Score 35 = 25%        (risk appetite; one setting)
Formula limit  = current limit × PD_target / PD(score)
Owed           = sum of the line's Open invoice amounts
Revised limit  = min(current limit, max(owed, formula limit))
```

The formula limit is the limit at which the line's expected loss equals
`PD_target × insured exposure` — the D3 formula solved for the limit (indemnity and
deductible cancel). Where `max_liability` binds, the insured exposure is already
capped and the limit cannot reduce it, so the line is left at its current limit and
the Case File says the cap is binding. Limits are never raised, never cut below owed.

| Action (first match wins) | When | Effect |
|---|---|---|
| **FREEZE** | PD > PD_target **and** owed ≥ current limit | stop insuring new invoices; the limit cannot usefully be cut |
| **REDUCE** | PD > PD_target **and** owed < current limit | cut to the revised limit |
| **MAINTAIN** | PD ≤ PD_target | no change |

### D7 — Leakage boundary

`ground_truth` and `payment_behaviour_monthly` are **harness-only** and raise
`LeakageError` if any engine module opens them. `news_articles.csv` loses its `gt_*`
columns before an article reaches the LLM.

### D8 — Three bands

| Band | Risk Score |
|---|---|
| **Healthy** | 0 – 34 |
| **Watch** | 35 – 59 |
| **High Risk** | 60 – 100 |

Pure thresholds on the score — no persistence, no override rules.

### D9 — Harness

Runs against the labels; the sole reader of `ground_truth.csv`. Reports:

| Check | Pass condition |
|---|---|
| Detection | all 4 defaulters non-Healthy |
| False positives | all 22 survivors Healthy; the wobblers and every severity-5 survivor are derived from the labels, never named in code |
| Entity resolution — recall | every genuine mention resolves to the right buyer or parent |
| Entity resolution — precision | **every decoy refused** (0 false matches) |
| Severity agreement | LLM severity vs `gt_severity`, exact-match rate + confusion matrix |
| Parent fan-out | each parent story reaches exactly its mapped subsidiaries at the stepped-down severity |
| Determinism | same inputs twice → byte-identical `out/runs/*.json` |
| Leakage | engine import of a harness-only table raises; no `gt_*` column reaches the LLM |
| Formula | D5, D6 and the PD curve unit-tested at their knees (DPD 0/30/60, score 0/20/35/55/80/100) |
| Case File | every figure in the LLM's output matches the numbers it was given (D10) |

### D10 — Case File guard

The Case File is the default tab, so it cannot be allowed to invent a number.

- The writer receives a **facts dict** (score, band, DPD and the invoice behind it,
  severity and the article behind it, limit, owed, revised limit, action, expected
  loss) and is instructed to use only those values.
- Before rendering, every numeric token in the output is extracted and matched
  against the facts dict, allowing formatting variants (`€1.2M`, `1,200,000`).
- **Any unmatched number → discard the LLM output and render a templated case file
  from the same facts.** The dashboard marks which one it showed.

### D11 — LLM integration  *(revised by D12)*

`llm.py` exposes one interface with two implementations, selected by `EWS_LLM`:

- **Claude client** — transport for the agent loop. Per-agent model and effort live in
  `ews/settings.py`, not here.
- **Rule-based fallback** — keyword severity and strict-token entity matching. Always
  present; used for offline runs, the harness and every test.

**Every response is cached to disk by content hash.** The demo runs from cache, so a
network failure in the room cannot break it; a cache miss falls back to the
deterministic grader rather than blocking. ~27 baseline articles ≈ 54 calls, then one
call per new article.

### D12 — Autonomous agent runtime  *(added after the first build)*

The four agents were fixed prompt calls: one prompt in, one answer out. They are now
**autonomous agents**. Each is handed read-only tools over the engine's own data,
decides for itself what to look at and when it has seen enough, and ends the run by
calling a `submit_*` tool whose input the code validates. The News agent, for example,
can search the entity registry, pull a candidate's full record, and read other coverage
of the same company before deciding what an article is about — rather than matching on
a single line of text.

**Definitions moved out of code.** Each agent is `agents/<name>.md`: frontmatter lists
the tools it may use *with the descriptions it reads*, and the body is its system
prompt. Thresholds are injected from `config.py` as placeholders, so the 65/35 split is
still written once. Tool implementations stay in code.

**How an agent runs lives in `ews/settings.py`** — `model`, `effort`, `max_turns`,
`max_tokens`, `enabled`, and per-agent **guardrails**: which tools it must call before
it may submit, and what its submission has to satisfy. Every value is validated when
the agent loads, so a typo stops the run instead of being silently ignored. Both the
`.md` and the settings are part of the cache key, so editing either re-runs the agent
rather than replaying a stale answer.

**What the change was not allowed to touch.** This is the part worth defending:

| Invariant | Still true |
|---|---|
| One component emits the number | The score is computed by the D5 formula in code. The Adjudicator agent **reviews** it — agree / caveats / challenge, citing evidence ids — and cannot change it. |
| The score input is not the model's | The payment ledger is code. The agent must state the same worst invoice the ledger found; a submission that disagrees is rejected and it is told to look again. |
| Entity ids cannot be invented | `entity_must_be_looked_up` — a submitted id must have come back from a tool call in that same run. |
| The case file cannot invent figures | Every numeric token is checked against what its tools returned. A bad draft goes back to the agent; if it still cannot produce a clean one, the template renders. |
| The demo cannot break | A refusal, a run that never submits, a turn-limit overrun or any API error raises `AgentError` and that one item falls back to its rule-based path. Offline, every agent is rule-based and the harness and tests are unaffected. |

Each buyer's **Agents** tab shows which path ran and every tool call the agent made.


---

## Dataset changes — **applied and verified**

The supplied data left two specified defences untested. Both changes are additions
plus one field edit; the baseline is re-measured as unchanged at 4/4 and 22/22.

**1. Parent contagion — the dataset had zero parent stories. ✅ done**

- `buyers.csv`: **Marchetti Mills (BUY011)** repointed to `PAR03` (Northpoint
  Industrial Holdings), joining Westbridge.
- `harness_articles.csv`: `NWSDEMO07` — *Northpoint Industrial Holdings in restructuring talks with
  lenders*, severity 5, `gt_is_parent_story=Y`, dated 2026-09-20.
- Measured effect — one story, two buyers, **different outcomes**: Westbridge
  13.0 → 28.6 (Healthy, it is paying on time) and Marchetti 21.7 → 37.3 (**Watch**, it
  is already 25 days behind). The fusion argument in a single beat.

**2. Entity resolution — the dataset had zero decoys. ✅ done**

Four decoys added to `news_articles.csv` (now 31 articles) and one to the harness articles.
Each is a real company in an unrelated line of business sharing a brand token with a
covered buyer. **None carries a "not affiliated" disclaimer** — the earlier dataset's
decoys announced themselves, which made resolution a keyword match rather than a
test. These are separable only by the distinguishing token and by sector/city context:

| ID | Decoy entity | Business / city | Must NOT match |
|---|---|---|---|
| NWS0042 | Arcline Media BV | advertising, Frankfurt | Arcline Fabrications NV (steel fabrication, Antwerp) |
| NWS0043 | Halberg Jewellers GmbH | jewellery retail, Coventry | Halberg Textiles GmbH (textiles, Bielefeld) |
| NWS0044 | Marchetti Clinics SpA | healthcare, Turin | Marchetti Mills SpA (textiles, Biella) |
| NWS0045 | Oakhurst Realty LLP | property, Utrecht | Oakhurst Components Ltd (auto components, Birmingham) |
| NWSDEMO05 | Kessler Logistics GmbH | 3PL, Dortmund | Kessler Traders GmbH (steel trading, Essen) |

Marchetti, Oakhurst and Kessler are deliberate: all three are boundary buyers at 21.7, and
their decoys are severity-5 wage or lender stories — **a wrong match pushes them to
Watch in front of the room.** Silent failure is not available.

All decoys carry `gt_category=decoy`, `gt_severity=0`, empty `gt_buyer_id`, so the D9
precision gate is simply: every `decoy` row must resolve to nothing.

**3. `gt_severity` on the harness articles — not needed.** They already carry `gt_severity`,
`gt_category` and `gt_is_parent_story`; my earlier gap report was wrong.

---

## Repo layout

```
~/Projects/buyer-early-warning-agent/
├── README.md                 # opens with HACKATHON PROTOTYPE · SYNTHETIC DATA
├── data/                     # dataset CSVs (labels, monthly table, harness_articles: harness-only)
├── agents/                   # D12: one .md per agent - tools + system prompt
│   └── payment.md  news.md  adjudicator.md  casefile.md
├── docs/  PLAN.md (this file)  WALKTHROUGH.md  PRESENTATION.md
├── ews/
│   ├── config.py             # every constant the plan fixes, in one place
│   ├── settings.py           # D12: per-agent model, effort, limits, guardrails
│   ├── loader.py             # CSV access + the D7 leakage boundary
│   ├── evidence.py  llm.py   # evidence store; Claude transport + fallback + cache
│   ├── agents/
│   │   ├── definition.py     # D12: reads agents/*.md into an AgentSpec
│   │   ├── runtime.py        # D12: the shared tool loop; AgentError -> rules
│   │   └── payment.py  news.py  adjudicator.py
│   ├── limits.py             # D6
│   ├── casefile.py           # case file writer + D10 guard
│   └── run.py                # orchestrator
├── harness/evaluate.py       # sole reader of the labels (D9)
├── dashboard/  server.py  theme.css
├── tests/  test_gates.py  test_agents.py
├── requirements.txt          # `anthropic` only — nothing else is needed
└── out/                      # runs/<date>.json, eval.json, .llm_cache/  (gitignored)
```

Python 3 + stdlib, plus the Claude client behind `llm.py`. The dashboard is a
multi-page app served locally by `dashboard/server.py`; it reads `out/runs/` and
re-runs the engine on live input.

The loader **allow-lists** engine tables, so no engine file ever names the labels.

---

## Frontend

Breadcrumb on every page: **Home › Client › Buyer**.

**1. Home** — one card per client (Adlerhof 11 buyers, Solvenza 6, Nordhaven 3), each
showing band counts, total expected loss, and actions pending (FREEZE + REDUCE).

**2. Client dashboard** — sortable table of that client's buyers only:

| Buyer | Risk Score | Band | DPD | Worst news | Expected loss | Recommended action |
|---|---|---|---|---|---|---|

Default sort: expected loss, highest first. Filter chips: All / High Risk / Watch /
Healthy.

**3. Buyer page** — tabs:

| Tab | Shows |
|---|---|
| **Case File** (default) | LLM-written draft for the underwriter to review and approve: how the buyer is doing, why it is flagged, what would lift it — every figure guarded by D10 |
| **Score** | Payment × 0.65 + News × 0.35, the invoice and the article behind each, and the decay applied |
| **Limit** | current limit, owed, revised limit, action, expected loss before and after |
| **Payments** | every invoice, oldest unpaid highlighted |
| **News** | each article with severity, age, decayed contribution, and the entity it matched — including refusals |

---

## Design system and labelling

**Tinubu frontend tokens only. Nothing is invented.** Source of truth:
`packages/ui-components/src/ThemeVariations/cssVariables.ts` and
`ThemeProvider/{commonTheme,defaultLightTheme}.ts`.

- CSS variable contract copied exactly as `generateCSSVariables()` emits it:
  `--theme-accent`, `--theme-neutral-0 … --theme-neutral-1000` (12 steps), and the
  semantic colours `--theme-red-{50,500,600}`, `--theme-orange-{200,700,900}`,
  `--theme-green-{200,900}`, `--theme-blue-500`.
- Bands map onto existing semantics — **High Risk** `red-500` on `red-50`, **Watch**
  `orange-700` on `orange-200`, **Healthy** `green-900` on `green-200`.
- Typography from `commonTheme`: Roboto; h1 2rem/800, h2 1.5rem/600, h3 1.125rem/600,
  h4 1rem/600, body1 1rem/400 lh 1.75, body2 0.875rem/400 lh 1.5. Background
  `#f8f8f8`. Google Fonts link with a system-stack fallback so it renders offline.
- **Only the platform's own default variation is used** (accent `#05BBD2`). Every
  insurer renders in the same theme.
- **No third-party branding of any kind.** The three insurers in this dataset are
  invented, so dressing one of them in a real insurer's brand colour would put a real
  company's identity on fabricated risk data. An earlier draft re-skinned each insurer
  from its platform theme variation; that was dropped, along with the real insurer names, for
  exactly this reason.
- Cost of the decision: the per-insurer re-skin is gone. Confidentiality is unaffected
  — each insurer still sees only its own buyers and no rival is named anywhere,
  including the footer. The `[data-theme]` hook stays in the markup for whoever wants
  variations later.
- No logos; brand names render as text.

Labelling: fixed non-dismissible banner on every view reading **HACKATHON PROTOTYPE ·
SYNTHETIC DATA**, the same in the page title and footer, footer adds "not reviewed by
Risk or Compliance".

---

## As built

The engine follows this plan. One decision was revised after the first build — D12,
the autonomous agent runtime — and is written up above rather than left implicit.
Three smaller deviations, recorded here rather than left for someone to discover:

| Planned | Built | Why |
|---|---|---|
| `dashboard/pages/` directory | page functions inside `server.py` | three pages did not justify a package |
| `docs/DECISIONS.md`, `docs/PITCH.md` | not written | this file already carries the decisions; the pitch is `PRESENTATION.md` |
| — | `ews/config.py` added | every fixed constant in one file, so a threshold cannot drift between agent and harness |
| three agents, fixed prompts | four autonomous agents over tools | D12 — the invariants it had to preserve are tabled there |

**Measured, `python3 -m harness.evaluate`:**

| Gate | Result |
|---|---|
| Detection — every defaulter leaves Healthy | **4/4** |
| False positives — every survivor stays Healthy | **22/22** |
| Named traps — 4 wobblers + Vandermeer stay Healthy | all clean |
| Entity resolution — recall on genuine mentions | **33/33** |
| Entity resolution — every decoy refused | **5/5** |
| Severity agreement with labels | **32/32** rules · **29/32** Claude |
| Parent fan-out — exact subsidiaries, stepped-down severity | pass |
| Case file — every figure traced to the engine | none discarded (4 model-written on Claude) |

Baseline scores: Arcline **63.3** and Maasland **62.2** High Risk; Halberg **42.7**
and Emberline **37.2** Watch; 22 Healthy; 4 decoys refused.

`python3 -m unittest discover -s tests` — **79/79**, covering the leakage boundary
(including a grep asserting no engine file so much as names the label tables),
determinism, the D5/D6/D8 formulae at their knees, the reluctant resolver against
every genuine variant and every decoy, the case-file guard, and the rule that no
colour appears outside `theme.css` — plus, since D12, the agent loop, the `.md`
definitions and the settings validator (`tests/test_agents.py`).

The gate results above are unchanged by D12: the same 4/4, 22/22 and 33/33, because
the rule-based path the harness measures is the one that was there before.

---

### D13 — Spend controls and measured usage  *(added after the first real Claude run)*

Running the agents against Claude for the first time exposed three things no test had.

**A call budget is not a spend budget.** `MAX_MODEL_CALLS` counts requests, and one
request with 80k input tokens costs fifty times one with 1.5k. `MAX_MODEL_TOKENS`
(4M default) now caps tokens as well. Either ceiling switches the client off and lets
the run finish on rules rather than aborting.

**An override that only one entry point honours is worse than none.** `--agents news`
was implemented inside `ews.run.main()`. The harness calls `engine.run()` directly, so
it never saw the flag and ran **all four agents, including both Opus ones**, on default
settings. Both CLIs now go through one `settings.apply_overrides()`, which also reads
`EWS_AGENTS` / `EWS_MAX_CALLS`; a test asserts neither re-implements the switch.

**The budget reset on every engine run.** The harness built one client and never passed
it down, so each of its nine `engine.run()` calls constructed its own with a fresh
counter — worst case 3,600 calls, not 400. One client now threads through every run.

**Spend is measured, not estimated.** Per-model input/output/cache-read tokens are
recorded at `create()` — the single choke point — priced from a published-rate table,
and reported at the end of every run and in `out/runs/*.json`. An unlisted model prices
at the most expensive row, so nothing is ever reported cheaper than it is.

```
spend (measured, not estimated):
  claude-sonnet-5       4 calls      6,846 in       619 out  $0.02
  TOTAL                  7,465 tokens                    $0.02
```

**What the first full Claude run showed.** All four agents, ~230 calls, roughly $2-4.
Detection, false positives, entity-resolution recall and **decoy refusal all matched
the rules path exactly** — a model with search tools and freedom to investigate still
refused all five decoys. The case-file guard passed its first real test: four Opus 5
drafts, every figure traced, none discarded. The only divergence was severity, 29/32,
and on inspection **the model was reading the article while the label was applying a
category template** — `capacity_cut` is always 3 in the labels, but "cut from three
shifts to one, halted contract worker recall, slowed material procurement" is not a
mild trim. Reported as a finding about the labels, not tuned away.
