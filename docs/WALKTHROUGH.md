# Walkthrough — what every file does, and where every number on screen comes from

> **HACKATHON PROTOTYPE · SYNTHETIC DATA**

`README.md` says how to run it. `docs/PLAN.md` says why each decision was made.
**This file is the map**: read it once and you can open any page in the dashboard,
point at any number, and say which function produced it and which CSV row it rests on.

---

## 1. The mental model in one paragraph

A trade credit insurer covers a supplier against its *buyers* not paying. The insurer
grants each buyer a **credit limit**. If a buyer is quietly heading for default, the
insurer wants to cut that limit *before* the loss, not after. This system watches two
signals — **how late the buyer pays** (internal, from the invoice ledger) and **what the
news says about it** (external, including news about its parent company) — fuses them
into one 0–100 **risk score**, and turns that score into a **recommended limit action**
with a euro figure attached. Four Claude agents do the reading and judging. **Code does
all the arithmetic**, so no score is ever a model's opinion.

**The one rule that holds the whole thing together:** agents produce *evidence and
judgement*; code produces *numbers*. Every guardrail in the codebase exists to keep that
line from being crossed.

---

## 2. The flow, end to end

One "run" is `ews.run.run()`. It is plain Python, not an LLM — nothing decides the order
but the code. Everything downstream is a pure function of what it returns.

```
data/*.csv
    │
    ▼
Loader ─────────────────── refuses ground_truth.csv + payment_behaviour_monthly.csv
(ews/loader.py)            strips gt_* columns out of news before anything reads it
    │                      validate(): duplicate ids, orphan refs, uncovered buyers
    ▼
┌──────────────────────── Agent 1 · Payment  (once per buyer, 26 runs)
│   ledger in code: worst Open invoice → DPD
│   agent reads open/settled/limits → trend + summary + concerns
│   ⛔ its submitted worst invoice must equal the ledger's, or it is sent back
│
├──────────────────────── Agent 2 · News  (once per article, 31 runs)
│   agent searches the entity registry → which company, if any → severity 0/3/4/5
│   ⛔ the id must have come back from its own tool call this run
│   parent story? → fan out to every subsidiary, one severity rung down
│
▼
EvidenceStore  (ews/evidence.py) — typed, dated, id-cited items:
    payment · payment_review · news · parent · resolution(refusal)
    │
    ▼
adjudicate()  ← THE ONLY PLACE A SCORE IS PRODUCED  (ews/agents/adjudicator.py:23)
    score = 0.65 × payment_score(DPD) + 0.35 × news_score
    band  = Healthy <35 · Watch 35–59 · High Risk 60+
    pd    = interpolated from the score
    │
    ├───────────────────── Agent 3 · Adjudicator  (once per buyer, 26 runs)
    │   reads the evidence behind the score → agree / caveats / challenge
    │   ⛔ cannot change the score. ⛔ every concern must cite a real evidence id
    │   ⛔ every number it writes must already exist in the data
    ▼
recommend()  (ews/limits.py) — FREEZE / REDUCE / MAINTAIN + revised limit + expected loss
    │
    ├───────────────────── Agent 4 · Case File  (Watch + High Risk only, 4 runs)
    │   writes the bottom line, the two notes, lifts_it / worsens_it, the narrative
    │   ⛔ every numeric token is checked against the facts; a bad draft is sent back,
    │      and if it still fails, the template renders from the same facts
    ▼
one JSON dict  →  dashboard renders it  ·  out/runs/*.json  ·  harness grades it
```

A baseline pass is **87 agent runs**: 26 payment + 31 news + 26 adjudicator + 4 case file.

---

## 3. The formula, in full

```
Risk Score = 0.65 × PaymentScore + 0.35 × NewsScore
```

**PaymentScore** — from DPD, the worst **Open** invoice on the buyer's ledger:

```
DPD ≤ 30 :  (DPD / 30) × 40            gentle — 1.33 points a day
DPD > 30 :  40 + min(60, (DPD−30) × 2) steep  — 2 points a day, caps at 100 (60 DPD)
```

The knee sits at 30 because that is every insurer's `overdue_reporting_window_days`.
Inside the window lateness is friction; past it the policyholder is contractually obliged
to report it, so the score treats it as a different kind of event. Only Open invoices
count — settled ones go to the agent as history for the trend, never into the score. It
is the **worst single invoice**, not an average, and the amount does not enter: size
belongs in the exposure calculation, not the risk score.

**NewsScore** — the **maximum** over the buyer's articles, never a sum:

```
base(severity) × 0.5 ^ (age_days / 365)

base:  sev 0 → 0     sev 3 → 20     sev 4 → 45     sev 5 → 75
```

…multiplied by a linear fade `(730 − age) / 180` once age > 550, and **0** when age ≥ 730
(past the relevance horizon) or age < 0 (dated after the run). Ten mild stories never add
up to one severe one.

**Bands:**

```
0 – 34.9  Healthy        35 – 59.9  Watch        60+  High Risk
```

**Worked example — Arcline Fabrications NV**

```
worst Open invoice  INV000075, 45 days past due
payment             40 + (45−30) × 2 = 70.0    × 0.65 = 45.5
news                sev 5, 204d old: 75 × 0.5^(204/365) = 50.9    × 0.35 = 17.8
                                                           45.5 + 17.8 = 63.3  High Risk
```

That last line is what the Score tab prints verbatim as `verdict.trace`.

**Ceiling worth knowing:** the largest news contribution possible is `75 × 0.35 = 26.25`,
and Watch starts at 35 — so **news alone can never move a buyer out of Healthy**. Only
payment behaviour crosses a band line. That is what keeps Vandermeer, a buyer carrying a
severity-5 unpaid-wages story who never defaults, sitting in Healthy.

### Who decides what, in the news half

| | Decided by |
|---|---|
| Which company the article is about, or none | **the agent** |
| How severe it is — 0 / 3 / 4 / 5 | **the agent** |
| That the id exists, matches the declared kind, and was looked up this run | code |
| That the severity is on the ladder | code |
| base lookup, decay, the fade, the horizon | code |
| parent step-down and fan-out to subsidiaries | code |
| taking the max across the buyer's articles | code |

Resolution and grading are **one submission, one agent run** — `submit_assessment(kind,
entity_id, severity, category, reason)`. Offline, the same two decisions come from
`strict_resolve()` and `keyword_grade()` as separate deterministic passes.

### Expected loss, and the limit recommendation

Everything below the score is deterministic — no LLM touches any of it (`ews/limits.py`).

**Step 1 — turn the score into a probability of default.** Linear interpolation across
five anchors. Not fitted to anything; it is a stated risk appetite, not a model.

```
(0, 1%)   (20, 10%)   (55, 45%)   (80, 85%)   (100, 95%)
```

**Step 2 — work out what the insurer actually carries.** A credit insurer never covers
the whole limit: it pays a percentage (indemnity), the policyholder eats a slice first
(deductible), and the policy caps total liability.

```
InsuredExposure = min(max_liability, limit × indemnity × (1 − deductible))
```

**Step 3 — expected loss is the two multiplied.**

```
ExpectedLoss = PD × InsuredExposure
```

**Step 4 — recommend an action.** `PD_target` is the PD at the Watch line, score 35,
which works out at **25%**. One setting, and it is the only risk-appetite number in the
system.

| Action | When | Effect |
|---|---|---|
| **MAINTAIN** | PD ≤ 25% | no change |
| **FREEZE** | PD > 25% **and** owed ≥ limit, or the liability cap already binds | stop insuring new invoices; there is nothing useful left to cut |
| **REDUCE** | PD > 25% **and** owed < limit | cut to the revised limit |

```
FormulaLimit = limit × PD_target / PD          the limit at which EL meets appetite
RevisedLimit = min(limit, max(owed, FormulaLimit))
```

Limits are **never raised** and **never cut below what is already owed** — you cannot
un-insure invoices that have already been issued.

**Worked example — Arcline Fabrications NV, insured by Nordhaven**

```
score 63.3  →  PD 58.3%                        interpolated between (55,45%) and (80,85%)

policy:  indemnity 85%   deductible 10%   max liability €6,000,000
limit:   €820,000        owed: €559,900

InsuredExposure = min(6,000,000, 820,000 × 0.85 × 0.90) = €627,300
ExpectedLoss    = 0.583 × 627,300                       = €365,779

PD 58.3% > 25%, the cap does not bind, owed < limit     → REDUCE
FormulaLimit  = 820,000 × 0.25 / 0.583                  = €351,570
RevisedLimit  = min(820,000, max(559,900, 351,570))     = €559,900   ← the owed floor binds
ExpectedLoss after = 0.583 × (559,900 × 0.85 × 0.90)    = €249,755
```

The formula wanted to cut to €352k; it stops at €559,900 because that much is already
owed. **That gap is the cost of being late to the signal** — and it is the argument for
watching daily rather than at review.

**The other two shapes, from the same data**

```
Halberg   PD 32.7% > 25%, but owed €527,100 ≥ limit €440,000   → FREEZE, nothing to cut
Oakhurst  PD 11.7% ≤ 25%                                       → MAINTAIN
```

**If someone asks why expected-loss-after is often the same figure across scenarios:** it
is the formula working. The cut targets whatever limit brings expected loss to appetite,
so the after value converges by construction. What changes is how far it has to cut to
get there.

---

## 4. Every file

### `data/` — the synthetic dataset (26 buyers, 3 insurers, snapshot 2026-09-25)

| File | Rows | What it is |
|---|---|---|
| `clients.csv` | 3 | The **insurers**. Carries the policy terms the money maths needs: `indemnity_pct`, `deductible_pct`, `max_liability_eur`, `overdue_reporting_window_days`. |
| `buyers.csv` | 26 | The companies being watched. `parent_id` is what makes contagion possible. |
| `credit_limits.csv` | 26 | One line per buyer per insurer — here exactly one each. The limit that may be cut. |
| `invoices.csv` | 156 | 93 Open, 63 Paid. `days_past_due` on the Open rows is **the entire payment signal**. |
| `news_articles.csv` | 31 | Headline + body + `mentioned_entity_as_written`. Includes 4 decoys. |
| `parent_companies.csv` | 4 | The holding companies news can arrive through. |
| `ground_truth.csv` | 26 | **Answers. Harness only.** Who actually defaulted. `loader.py` raises if engine code opens it. |
| `payment_behaviour_monthly.csv` | 451 | **Harness only.** Monthly aggregates — would hand the engine the trend it is meant to infer. |
| `harness_articles.csv` | 7 | **Harness only.** Labelled stories the shipped news lacks — the only parent-company story and two decoys. The harness hands them to the engine label-stripped, as extra articles. |

### `ews/` — the engine

| File | What it owns |
|---|---|
| `config.py` | **Every scoring constant, once.** Weights 0.65/0.35, the 30-day knee, the 365-day half-life, the 730-day horizon and 180-day fade, the severity ladder, the band lines, the PD curve. Plus `payment_score()`, `decay()`, `band()`, `pd_for()`. `_validate()` runs at import: a fade longer than the horizon, weights that don't sum to 1, unsorted PD anchors — each stops the process instead of quietly changing every score. `_finite()` refuses NaN, because `band(nan)` returning "Healthy" is the worst possible bug here. |
| `loader.py` | CSV access **and the leakage boundary**. `ENGINE_TABLES` / `HARNESS_ONLY` — asking for a label table without `harness=True` raises `LeakageError`. `news()` strips the five `gt_*` columns unless the harness is asking. `validate()` catches the five kinds of referential rot that otherwise fail silently. |
| `evidence.py` | The `Evidence` record — `kind, buyer_id, detail, source, date, data`. `source` is always an invoice id or article id, so **every claim on screen is clickable back to a row**. `evidence_view()` is the redacted form agents see (other agents' traces stripped out). |
| `llm.py` | Two implementations behind one interface. `ClaudeLLM` holds the SDK client, the per-model token accounting and the spend table. `FallbackLLM` is the deterministic path: `strict_resolve()` (the reluctant entity rule) and `keyword_grade()` (regex severity). Also `_Cache` — SHA-256 of the content, atomic writes, a corrupt entry is a miss not a crash. |
| `settings.py` | **How** each agent runs: model, effort, `max_turns`, `max_tokens`, `enabled`, and its guardrails. Plus the spend controls: `MAX_MODEL_CALLS=400`, `MAX_MODEL_TOKENS=4M`, `MAX_RETRIES=2`, the `PRICING` table. `apply_overrides()` is shared by both CLIs — a flag that only one entry point honoured is worse than none. Every value is type-checked at load. |
| `limits.py` | D6. Expected loss → `FREEZE` / `REDUCE` / `MAINTAIN`, the revised limit, and expected loss before/after. Deterministic, no LLM. Limits are never raised and never cut below what is already owed. |
| `casefile.py` | The D10 guard (`verify()`, `allowed_numbers()`), the `outlook()` arithmetic the agent is given so it never has to calculate, the template fallback, and the Case File agent itself. |
| `run.py` | The orchestrator. Runs the four agents in order, assembles per-buyer records and per-insurer rollups, reports agent modes and measured spend, writes `out/runs/*.json`. |
| `agents/definition.py` | Reads `agents/*.md` into an `AgentSpec`: frontmatter (name, title, description, tools) + body (the system prompt), with `{w_payment}`-style placeholders filled from `config.py`. Rejects a file with no prompt, with zero or two `submit_*` tools, or that sets something belonging in `settings.py`. |
| `agents/runtime.py` | **The shared tool loop.** Sends the prompt + tool specs, feeds tool results back, ends when the agent calls its `submit_*` tool. A rejected submission goes back as an error the agent can read and correct. Cached by content hash — the definition and settings are part of the key, so editing a prompt re-runs the agent. `attempt()` is the safety net: any failure → that one item falls back to rules. |
| `agents/payment.py` | The `Ledger` (code) + the agent's three read tools + `submit()`, which rejects a worst invoice that isn't the ledger's. |
| `agents/news.py` | `NewsDesk` — the entity registry, `search_entities` / `get_entity` / `find_articles`, and `submit()` which enforces the registry, the severity ladder and the looked-up-id rule. `assess()` does the parent fan-out and keeps the **highest decayed value** per buyer. |
| `agents/adjudicator.py` | `adjudicate()` — the formula, the only number source. `review()` — the agent that reviews it and cannot change it. |

### `agents/` — the four agent definitions

`payment.md`, `news.md`, `adjudicator.md`, `casefile.md`. Frontmatter lists the tools
**with the descriptions the model actually reads**; the body is the system prompt.
Thresholds are placeholders filled from `config.py`, so 0.65/0.35 is written in exactly
one place and reaches the prompt from there. Editing one of these files changes the
cache key, so the next run re-runs that agent rather than replaying a stale answer.

### `harness/evaluate.py`

The **only** module allowed to read the labels. Eight gates: detection, false positives,
named traps, entity-resolution recall, decoy refusal, severity agreement, parent
fan-out, case-file figure tracing. The traps are **derived from the labels**
(any severity-5 story on a buyer that never defaults), not named in code — naming them
would let a rename silently delete the check.

### `dashboard/`

`server.py` — stdlib `ThreadingHTTPServer`, no framework, no build step. `theme.css` —
TCS-Frontend tokens copied verbatim; a test asserts no colour appears anywhere else.

### `tests/` — 96 tests

`test_gates.py` (leakage, integrity, determinism, formulae at their knees, the reluctant
resolver against every decoy, the case-file guard, routing, secrets) and `test_agents.py`
(the loop, the definitions, the settings validator, every guardrail, the call and token
budgets, usage accounting).

---

## 5. Click-path traces — where each number on screen comes from

Everything rendered comes from **one dict**, built once per live-input state by
`snapshot()` (`dashboard/server.py:38`) and memoised in `_CACHE`. You can see the whole
thing at **`http://localhost:8000/api/run`** — that is the single source for every page.

### `/` — Home

| On screen | Comes from |
|---|---|
| "Buyers watched / High risk / Watch" tiles | `home()` counting `data["buyers"][*].verdict.band` |
| One card per insurer | `data["clients"]`, built in `run.py:66-81` |
| The band dots on a card | `client["bands"]` — buyers counted by band, filtered to lines belonging to that insurer |

### `/client/CL01` — one insurer's book

`client_page()`. The table is **only that insurer's buyers** — `r["limits"]` filtered by
`client_id`. Sorted by expected loss, highest first.

| Column | Source |
|---|---|
| Buyer | `buyers.csv` → `short_name`, `sector` |
| Risk Score (dial) | `verdict.score` ← `adjudicator.adjudicate()` |
| Payment Score | `verdict.payment.raw` ← `config.payment_score(dpd)` |
| News Score | `verdict.news.raw` ← `NEWS_BASE[severity] × decay(age)` |
| DPD | `verdict.payment.dpd` ← worst Open invoice in `invoices.csv` |
| Worst news | `verdict.news` — severity badge, category, "via parent" flag |
| Expected loss | `line.expected_loss_before` ← `pd × min(max_liability, limit × indemnity × (1−deductible))` |
| Recommended action | `line.action` ← `ews/limits.py` |

Sorting and the filter chips are ~20 lines of inline JS over `data-v` attributes — no
request, no re-run.

### `/buyer/BUY002` — the six tabs

**Case File** (default) — `case_tab()`. Header, limit table, score trace and evidence
list are **filled in by code** (`casefile._fields()`). The bottom line, the two driver
notes, lifts/worsens and the narrative are **the agent's words**. The line at the
bottom says which produced it. If the agent had written an unverifiable figure, this
would say *"model output discarded"* and you would be reading the template.

**Score** — the dial, then the arithmetic: DPD → payment score → ×0.65; article →
severity → base → ×decay → ×0.35; sum; PD. The adjudicator's review sits underneath
with its assessment pill. `verdict.trace` is the literal sum, printed.

**Limit** — one row per insurer: current limit, owed, revised, action, reason, and
expected loss before → after. All from `ews/limits.py`.

**Payments** — `evidence` rows of kind `payment`, one per insurer line: open count,
owed, worst DPD, and the invoice id behind it.

**News** — `evidence` of kind `news` and `parent`: date, headline, publication, the
entity matched, severity, age in days, and **base → decayed** so you can see the
half-life doing its work. Refused articles naming this buyer's brand appear underneath
with a `refused` pill.

**Agents** — `agents_tab()`. One card per agent: its title and description **read live
from `agents/*.md`**, its model and effort **read live from `settings.py`**, a pill
saying whether it ran as an agent / from rules / fell back / replayed from cache, and
**every tool call it made, in order, with the arguments and a preview of what came
back** — including calls the guardrails rejected. This is the tab that proves the
agents are real.

---

## 6. What the code refuses to let the agents do

This is the part worth being able to recite. Each of these is enforced in code, has a
test, and is visible on the Agents tab when it fires.

| Agent | It may | It may **not** |
|---|---|---|
| Payment | judge the trend, raise concerns | report any worst invoice but the ledger's — `payment.py:76` rejects it and tells it to look again |
| News | decide which company, and how severe | submit an id it never looked up (`entity_must_be_looked_up`), an id not in the registry, or a severity off the 0/3/4/5 ladder |
| Adjudicator | agree, caveat, or **challenge** the verdict | change the score; cite an evidence id that isn't this buyer's; write a figure that isn't in the data |
| Case File | write the judgement and the narrative | write any number that doesn't trace to the facts — the draft is returned, and a second failure falls to the template |

Plus two that apply to all four: a refusal, a truncation, a turn-limit overrun or any
API error raises `AgentError` and **that one item** falls back to rules — the run never
dies. And `MAX_MODEL_CALLS` / `MAX_MODEL_TOKENS` switch Claude off mid-run rather than
letting a loop run up a bill.

---

## 7. Rules, Claude, or cache?

Three ways any given agent run can resolve, shown honestly on every buyer's Agents tab:

- **cache** — a JSON file in `out/.llm_cache/` keyed by a hash of the prompt, the tools,
  the settings and the data. 117 entries ship with the repo, so a fresh clone runs the
  full Claude path **for free and offline**.
- **Claude** — `EWS_LLM=auto` (the default) uses it when credentials exist.
- **rules** — no key, or that item failed. `strict_resolve()` + `keyword_grade()`.
  This is the path the harness measures, which is why the gates are reproducible
  by anyone.

---

## 8. The three questions to expect

**"Can the news alone put a healthy company on a watchlist?"**
No. Maximum news contribution is `0.35 × 75 = 26.25`, and Watch starts at 35. Only
payment behaviour can carry a buyer over a band line. That is by design, and it is what
keeps Vandermeer — a severity-5 unpaid-wages story on a company that never defaults —
in Healthy.

**"Is the model inventing numbers?"**
It cannot. Every numeric token in what it writes is extracted and matched against the
facts its tools returned, allowing formatting variants (`€1.2M`, `1,200,000`). One
unmatched figure and the draft goes back; a second failure renders the template. The
harness reports how many were discarded — on the last full Claude run, zero of four.

**"Did you tune this on the answers?"**
No. `ground_truth.csv` raises `LeakageError` if engine code opens it, `gt_*` columns are
stripped before an article reaches a model, and a test greps every engine file to assert
none of them so much as names the label tables.
