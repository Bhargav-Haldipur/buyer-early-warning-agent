# Buyer Early Warning Agent — Implementation Plan

> **HACKATHON PROTOTYPE · SYNTHETIC DATA**

**This is the specification the code was built from.** It is the plan as it stood
*after* a gap analysis against the real dataset — the Recovery Challenger retired,
news decay added with a measured half-life, the As-Of Clock dropped, parent
contagion and entity-resolution decoys added to the data, and the harness, case-file
guard and LLM integration specified (D9–D11). Every number in it was measured
against the shipped CSVs before a line of engine code existed.

Built and verified: **9/9 harness gates, 18/18 tests.** See *As built* at the end.

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

20 buyers, 3 insurers (Aldermont Trade Credit, Calderwood Trade Credit, Thornbury),
20 credit-limit lines (**one per buyer** — every buyer has exactly one insurer),
120 invoices (75 Open, 45 Paid), 27 news articles (2024-07 → 2026-06), 4 parent
companies. Snapshot **2026-09-25**; every insurer uses a 30-day overdue reporting
window.

| Class | Count | Buyers |
|---|---|---|
| Defaults (`gradual`) | 4 | Arcline, Suvarna, Girikand, Emberline |
| `wobble_recovered` | 4 | Kalpataru Prime, Bluestone, Mahanadi, Westbridge |
| `healthy` | 12 | includes the 5 demo boundary buyers and Jayanth |

Buyers per insurer: Aldermont 11, Calderwood 6, Thornbury 3.

| File | Role |
|---|---|
| `clients`, `buyers`, `credit_limits`, `invoices`, `news_articles`, `parent_companies` | engine inputs |
| `ground_truth`, `payment_behaviour_monthly` | **harness-only** |
| `demo/demo_articles_to_add.csv` | articles appended one at a time during the demo |
| `demo/invoices_after_payment_demo.csv` | drop-in replacement for `invoices.csv` (Udaan at 40 DPD) |

**Baseline result (measured, with the D5 decay applied):** Arcline 63.3 and Girikand
62.2 in High Risk; Suvarna 42.7 and Emberline 37.2 in Watch; all 16 survivors Healthy.
**4/4 caught, 0 false positives.**

⚠ **Emberline sits 2.2 points above the Watch line.** Decay costs it most (its worst
article is 320 days old), so any change to the half-life, the news ladder or the 65/35
split must be re-checked against Emberline first — it is the binding constraint.

---

## Decisions

### D0 — Architecture

A deterministic spine, LLM at the leaves, one typed Evidence Store.

```
   TIER 1  EVIDENCE   Payment (per insurer line, deterministic)
        │             · News & Parent (per article, LLM; parent news fans out
        │               to subsidiaries via parent_companies)
        │             — evidence producers NEVER score risk
   EVIDENCE STORE     typed, dated, source-cited
        │
   TIER 2  JUDGMENT   Adjudicator — the only component that emits a number;
        │             Risk Score formula (D5) + bands (D8)
   TIER 3  ACTION     Limit recommendations (D6) → Case File Writer (LLM) → dashboard
                      Harness grades every run against the labels (D9)
```

- Orchestrator is **code, not an LLM**.
- **No As-Of Clock.** The dataset is a single snapshot at 2026-09-25 and every row
  precedes it, so date filtering never fired. The loader simply loads. *(Retired —
  it was scaffolding for a replay feature this plan does not have.)*

### D1 — Three agents

| # | Agent | Kind |
|---|---|---|
| 1 | Payment Behaviour | deterministic |
| 2 | News Intelligence (buyer + parent news) | LLM, 2 gated passes, behind `llm.py` |
| 3 | Risk Adjudicator | deterministic |

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

Rupees at risk: `EL = PD × min(max_liability, limit × indemnity × (1 − deductible))`
per line. PD is a credit-risk prior on the Risk Score, **linearly interpolated**
between (0, 1%), (20, 10%), (55, 45%), (80, 85%), (100, 95%). Not fitted.

Dashboard: see **Frontend**, plus a **live-demo panel** (append a demo article, swap
the invoice file, re-run). Every alert states why it fired and what would lift it.

### D4 — News reliability

**Direct buyer news.** Entity resolution is the primary defence and is **reluctant**:
the brand token must match and every distinguishing token must be part of that
entity's own name; ambiguity refuses. The LLM assigns each surviving article a
severity of **0, 3, 4 or 5**.

**Parent news.** Parent articles resolve to the parent, then fan out to every
subsidiary through the `parent_companies` graph — the lookup is deterministic, the
assessment is the LLM's. A parent story **steps down one rung of the severity ladder**
for each subsidiary:

| Parent severity | Subsidiary severity |
|---|---|
| 5 | 4 |
| 4 | 3 |
| 3 | — (no contribution) |

No new multiplier: a parent in trouble is a *moderate* concern for the subsidiary,
not a severe one, and the step-down says so on the same scale the LLM already uses.

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

**The 365-day half-life is measured, not assumed.** Without decay, Jayanth's
severity-5 wage story from 2024-10-15 is **710 days old** and carries full weight —
the trap survives only because Jayanth has no overdue invoices, and **11 days past
due flips it to Watch**. Sweeping half-lives against the labels:

| Half-life | Defaulters flagged | Survivors clean | Jayanth tolerance |
|---|---|---|---|
| none | 4/4 | 16/16 | 11 DPD |
| 180 d | **3/4** (Emberline missed at 33.2) | 16/16 | — |
| 240 d | **3/4** (Emberline missed at 34.9) | 16/16 | — |
| **365 d** | **4/4** | **16/16** | **32 DPD** |
| 540 d | 4/4 | 16/16 | 29 DPD |

365 days keeps the result and widens the trap's margin threefold. Anything under
270 days breaks Emberline.

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
| False positives | all 16 survivors Healthy (Jayanth and the 4 wobblers named explicitly) |
| Entity resolution — recall | every genuine mention resolves to the right buyer or parent |
| Entity resolution — precision | **every decoy refused** (0 false matches) |
| Severity agreement | LLM severity vs `gt_severity`, exact-match rate + confusion matrix |
| Parent fan-out | each parent story reaches exactly its mapped subsidiaries at the stepped-down severity |
| Determinism | same inputs twice → byte-identical `out/runs/*.json` |
| Leakage | engine import of a harness-only table raises; no `gt_*` column reaches the LLM |
| Formula | D5, D6 and the PD curve unit-tested at their knees (DPD 0/30/60, score 0/20/35/55/80/100) |
| Case File | every figure in the LLM's output matches the numbers it was given (D10) |
| Demo replay | the scripted sequence reproduces the scores in **Demo** below |

### D10 — Case File guard

The Case File is the default tab, so it cannot be allowed to invent a number.

- The writer receives a **facts dict** (score, band, DPD and the invoice behind it,
  severity and the article behind it, limit, owed, revised limit, action, expected
  loss) and is instructed to use only those values.
- Before rendering, every numeric token in the output is extracted and matched
  against the facts dict, allowing formatting variants (`₹1.2M`, `1,200,000`).
- **Any unmatched number → discard the LLM output and render a templated case file
  from the same facts.** The dashboard marks which one it showed.

### D11 — LLM integration

Claude API key is available. `llm.py` exposes one interface with two
implementations, selected by environment variable:

- **Claude client** — `claude-sonnet-5` for entity resolution and severity grading,
  `claude-opus-5` for the Case File. Load the `claude-api` skill before writing this
  client rather than working from memory.
- **Deterministic fallback** — keyword-based severity and strict-token entity
  matching. Always present, used for offline runs and every harness gate.

**Every response is cached to disk by content hash.** The demo runs from cache, so a
network failure in the room cannot break it; a cache miss falls back to the
deterministic grader rather than blocking. ~27 baseline articles ≈ 54 calls, then one
call per demo article.

---

## Dataset changes — **applied and verified**

The supplied data left two specified defences untested. Both changes are additions
plus one field edit; the baseline is re-measured as unchanged at 4/4 and 16/16.

**1. Parent contagion — the dataset had zero parent stories. ✅ done**

- `buyers.csv`: **Chandra Mills (BUY011)** repointed to `PAR03` (Northpoint
  Industrial Holdings), joining Westbridge.
- `demo/`: `NWSDEMO07` — *Northpoint Industrial Holdings in restructuring talks with
  lenders*, severity 5, `gt_is_parent_story=Y`, dated 2026-09-20.
- Measured effect — one story, two buyers, **different outcomes**: Westbridge
  13.0 → 28.6 (Healthy, it is paying on time) and Chandra 21.7 → 37.3 (**Watch**, it
  is already 25 days behind). The fusion argument in a single beat.

**2. Entity resolution — the dataset had zero decoys. ✅ done**

Four decoys added to `news_articles.csv` (now 31 articles) and one to the demo set.
Each is a real company in an unrelated line of business sharing a brand token with a
covered buyer. **None carries a "not affiliated" disclaimer** — the earlier dataset's
decoys announced themselves, which made resolution a keyword match rather than a
test. These are separable only by the distinguishing token and by sector/city context:

| ID | Decoy entity | Business / city | Must NOT match |
|---|---|---|---|
| NWS0042 | Arcline Media Pvt Ltd | advertising, Mumbai | Arcline Fabricators Limited (steel fabrication, Nagpur) |
| NWS0043 | Suvarna Jewellers Pvt Ltd | jewellery retail, Coimbatore | Suvarna Textiles Pvt Ltd (textiles, Surat) |
| NWS0044 | Chandra Hospitals Pvt Ltd | healthcare, Nashik | Chandra Mills Pvt Ltd (textiles, Ichalkaranji) |
| NWS0045 | Oakhurst Realty LLP | property, Gurugram | Oakhurst Components Pvt Ltd (auto components, Aurangabad) |
| NWSDEMO05 | Udaan Logistics Pvt Ltd | 3PL, Pune | Udaan Traders Pvt Ltd (steel trading, Ludhiana) |

Chandra, Oakhurst and Udaan are deliberate: all three are boundary buyers at 21.7, and
their decoys are severity-5 wage or lender stories — **a wrong match pushes them to
Watch in front of the room.** Silent failure is not available.

All decoys carry `gt_category=decoy`, `gt_severity=0`, empty `gt_buyer_id`, so the D9
precision gate is simply: every `decoy` row must resolve to nothing.

**3. `gt_severity` on demo articles — not needed.** They already carry `gt_severity`,
`gt_category` and `gt_is_parent_story`; my earlier gap report was wrong.

---

## Demo

Five boundary buyers all sit at **DPD 25 → score 21.7, Healthy**. Articles are
appended one at a time and the engine re-run.

All scores below are **measured against the shipped data**, not estimated.

| Step | Article | Sev | Buyer | Score | Band |
|---|---|---|---|---|---|
| 1 | Chandra Mills appoints new plant head | 0 | Chandra | 21.7 → 21.7 | Healthy — *news that means nothing* |
| 2 | Indus Crest scales back operations | 3 | Indus Crest | 21.7 → 28.6 | Healthy |
| 3 | Vendors say Lakshya has fallen behind on payments | 4 | Lakshya | 21.7 → 37.3 | **Watch** |
| 4 | Workers at Oakhurst protest delayed wages | 5 | Oakhurst | 21.7 → 47.7 | **Watch** |
| 5 | Udaan **Logistics** wage protest — decoy | — | *(none)* | no change | **refused** — wrong company |
| 6 | Workers at Udaan **Traders** protest delayed wages | 5 | Udaan | 21.7 → 47.7 | **Watch** |
| 7 | Northpoint parent in restructuring talks | 5→4 | Chandra | 21.7 → 37.3 | **Watch** |
| 7 | *…same article, second subsidiary* | 5→4 | Westbridge | 13.0 → 28.6 | Healthy |
| 8 | swap `invoices.csv` → Udaan DPD 25 → 40 | — | Udaan | 47.7 → **65.0** | **High Risk** |

Steps 5 and 6 are the pair that sells entity resolution: the same wage-protest story,
one refused and one accepted, on names differing by a single token.

Step 5 is the refusal, step 7 is contagion with two different outcomes, step 8 is the
two signals compounding.

---

## Repo layout

```
~/Projects/buyer-early-warning-agent/
├── README.md                 # opens with HACKATHON PROTOTYPE · SYNTHETIC DATA
├── data/                     # dataset CSVs (labels + monthly table harness-only)
│   └── demo/                 # demo_articles_to_add.csv, invoices_after_payment_demo.csv
├── docs/  PLAN.md (this file)  DEMO_GUIDE.md
├── ews/
│   ├── config.py             # every constant the plan fixes, in one place
│   ├── loader.py             # CSV access + the D7 leakage boundary
│   ├── evidence.py  llm.py   # evidence store; Claude client + fallback + cache
│   ├── agents/  payment.py  news.py  adjudicator.py
│   ├── limits.py             # D6
│   ├── casefile.py           # case file writer + D10 guard
│   └── run.py                # orchestrator
├── harness/evaluate.py       # sole reader of the labels (D9)
├── dashboard/  server.py  theme.css
├── tests/test_gates.py
├── requirements.txt          # `anthropic` only — nothing else is needed
└── out/                      # runs/<date>.json, eval.json, .llm_cache/  (gitignored)
```

Python 3 + stdlib, plus the Claude client behind `llm.py`. The dashboard is a
multi-page app served locally by `dashboard/server.py`; it reads `out/runs/` and
re-runs the engine for the live demo.

The loader **allow-lists** engine tables, so no engine file ever names the labels.

---

## Frontend

Breadcrumb on every page: **Home › Client › Buyer**.

**1. Home** — one card per client (Aldermont 11 buyers, Calderwood 6, Thornbury 3), each
showing band counts, total expected loss, and actions pending (FREEZE + REDUCE).

**2. Client dashboard** — sortable table of that client's buyers only:

| Buyer | Risk Score | Band | DPD | Worst news | Expected loss | Recommended action |
|---|---|---|---|---|---|---|

Default sort: expected loss, highest first. Filter chips: All / High Risk / Watch /
Healthy.

**3. Buyer page** — tabs:

| Tab | Shows |
|---|---|
| **Case File** (default) | LLM-written summary: how the buyer is doing, why it is flagged, what would lift it — every figure guarded by D10 |
| **Score** | Payment × 0.65 + News × 0.35, the invoice and the article behind each, and the decay applied |
| **Limit** | current limit, owed, revised limit, action, expected loss before and after |
| **Payments** | every invoice, oldest unpaid highlighted |
| **News** | each article with severity, age, decayed contribution, and the entity it matched — including refusals |

---

## Design system and labelling

**TCS-Frontend tokens only. Nothing is invented.** Source of truth:
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
  from its TCS variation; that was dropped, along with the real insurer names, for
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

The engine follows this plan exactly. Three deviations, all recorded here rather
than left for someone to discover:

| Planned | Built | Why |
|---|---|---|
| `dashboard/pages/` directory | page functions inside `server.py` | three pages did not justify a package |
| `docs/DECISIONS.md`, `docs/PITCH.md` | not written | this file already carries the decisions; the pitch is `DEMO_GUIDE.md` |
| — | `ews/config.py` added | every fixed constant in one file, so a threshold cannot drift between agent and harness |

**Measured, `python3 -m harness.evaluate`:**

| Gate | Result |
|---|---|
| Detection — every defaulter leaves Healthy | **4/4** |
| False positives — every survivor stays Healthy | **16/16** |
| Named traps — 4 wobblers + Jayanth stay Healthy | all clean |
| Entity resolution — recall on genuine mentions | **33/33** |
| Entity resolution — every decoy refused | **5/5** |
| Severity agreement with labels | **32/32 exact** |
| Parent fan-out — exact subsidiaries, stepped-down severity | pass |
| Demo replay — steps 1–8 reproduce the planned scores | pass |
| Case file — every figure traced to the engine | none discarded |

Baseline scores: Arcline **63.3** and Girikand **62.2** High Risk; Suvarna **42.7**
and Emberline **37.2** Watch; 16 Healthy; 4 decoys refused.

`python3 -m unittest discover -s tests` — **18/18**, covering the leakage boundary
(including a grep asserting no engine file so much as names the label tables),
determinism, the D5/D6/D8 formulae at their knees, the reluctant resolver against
every genuine variant and every decoy, the case-file guard, and the rule that no
colour appears outside `theme.css`.
