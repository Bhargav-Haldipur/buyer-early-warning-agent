# Buyer Early Warning Agent

> **TINUBU PRODUCT PROTOTYPE**
> The main dataset under `data/` is sample data: no real counterparty, client or
> portfolio appears in it. The SBI book under `data/sbi/` names real US companies with
> real public news, and an **illustrative** payment ledger - see below.

A credit insurer finds out a buyer is in trouble when the claim arrives. This watches
every covered buyer across every insurer and flags the early signs first — from two
signals only: **payment behaviour** (internal) and **news** (external, including news
about a buyer's parent company).

On the supplied dataset it flags **all four buyers that go on to default, with no false
positives** — including the four that deteriorate and recover, and a buyer with a
severity-5 wage-strike story that never defaults.

---

## Run it

```bash
python3 -m ews.run
python3 -m harness.evaluate
python3 -m unittest discover -s tests
python3 -m dashboard.server
```

| Command | What it does |
|---|---|
| `ews.run` | scores every buyer, writes `out/runs/<date>.json` |
| `harness.evaluate` | grades that run against the labels — 8 gates |
| `unittest discover -s tests` | leakage, determinism, formulae, resolver, guard, theme, agent loop, agent definitions, settings, SBI book — 128 tests |
| `dashboard.server` | serves the dashboard on http://localhost:8000 (Ctrl-C to stop) |

**No install, no API key, no network.** Everything above runs on the Python 3 standard
library. Run them from the repository root.

The dashboard blocks the terminal, so give it its own window. The live input sandbox
is at http://localhost:8000/live: type a story nobody prepared or age an invoice by hand,
and the engine re-runs on it. [`docs/PRESENTATION.md`](docs/PRESENTATION.md) walks
through it.

### Switching the agents on

The four agents (Payment Behaviour, News Intelligence, Risk Adjudicator, Case File)
are autonomous Claude agents: each gets read-only tools over the engine's data,
decides what to look at and when it has seen enough, and ends by calling a `submit_*`
tool whose input code checks. Without Claude, each falls back to its rule-based path,
so the demo, harness and tests always work offline. To use Claude:

```bash
cp .env.example .env            # then paste your key after ANTHROPIC_API_KEY= in .env
python3 -m venv .venv
.venv/bin/pip install anthropic
.venv/bin/python -m ews.run
```

**The API key goes in `.env`** at the project root. It is git-ignored, so the key never
reaches the repository, and it is loaded automatically by every entry point - the
dashboard, `ews.run`, `ews.fetch_news`. `.env.example` lists every variable it accepts.
A variable already exported in your shell takes precedence over the file.

A venv is needed because Homebrew's Python is externally managed (PEP 668). Only the
Claude path needs it &mdash; everything above runs on the system `python3`.

Claude is picked up automatically once both are in place. To force the rule-based
path back on:

```bash
EWS_LLM=fallback python3 -m ews.run
```

### Controlling what it spends

Nothing calls the API unless you ask it to, and three controls bound what happens when
you do. All of them work on `ews.run` and `harness.evaluate` alike, and as env vars:

```bash
.venv/bin/python -m ews.run --agents news --max-calls 60
EWS_AGENTS=news EWS_MAX_CALLS=60 .venv/bin/python -m harness.evaluate
```

| Control | Where | What it does |
|---|---|---|
| `--agents` / `EWS_AGENTS` | CLI or env | only these agents use Claude; the rest use rules |
| `--max-calls` / `EWS_MAX_CALLS` | CLI or env | caps model calls for the run |
| `MAX_MODEL_CALLS` | `ews/settings.py` | default call ceiling (400) |
| `MAX_MODEL_TOKENS` | `ews/settings.py` | default token ceiling (4M) — a call cap is a crude proxy, since one call with 80k input costs fifty times one with 1.5k |
| `max_turns` | `ews/settings.py` | model calls per agent run (12) |

When either budget is reached the client switches itself off and everything remaining
falls back to rules — the run completes, it just stops spending.

Every run reports what it actually used, priced per model. Not an estimate:

```
spend (measured, not estimated):
  claude-sonnet-5       4 calls      6,846 in       619 out  $0.02
  TOTAL                  7,465 tokens                    $0.02
```

Every agent run is cached to `out/.llm_cache/` by content hash, so re-runs cost nothing
and need no network. A refusal, a run that never submits, or any API failure degrades
that one item to its rule-based answer rather than taking the demo down. Each buyer's
**Agents** tab on the dashboard shows which path ran and every tool call the agent made.

Each agent is defined in its own Markdown file under [`agents/`](agents/):
`payment.md`, `news.md`, `adjudicator.md`, `casefile.md`. The frontmatter lists which
tools the agent may use, with the descriptions it reads; the body is its instructions.

How each agent runs lives in [`ews/settings.py`](ews/settings.py): `model`, `effort`
(`low` to `max`), `max_turns`, `max_tokens`, `enabled`, and its **guardrails** - the
tools it must call before it may submit, and the checks its submission must pass.
Every value is validated when the agent loads, so a typo stops the run instead of
being ignored.

Edit either file and the next run uses it. Both are part of the cache key, so a changed
agent re-runs rather than replaying an old answer. Tool implementations stay in code.

The guardrails, with their defaults in `ews/settings.py`:

| Agent | Decides | Guardrails (settings.py) | Always, in code |
|---|---|---|---|
| Payment Behaviour | settlement trend, concerns | must call `get_open_invoices` first; `must_match_ledger`; `max_concerns` | the score uses the ledger, never the agent |
| News Intelligence | which entity an article is about, severity | must call `search_entities` first; `entity_must_be_looked_up`; `allowed_severities` | entity must be in the registry; parent fan-out |
| Risk Adjudicator | agree / caveats / challenge, with cited evidence | must call `get_evidence` first; `require_real_citations`; `verify_figures`; `max_concerns` | cannot change the score |
| Case File | a draft for the risk underwriter to review and approve: structured fields (bottom line, driver notes, lift/worsen triggers) + a four-paragraph narrative; header, limits, trace and evidence are filled by code | must call `get_verdict` and `get_limits` first; `verify_figures` over every field; `figure_tolerance`; `max_list_items`; `run_for_bands` | template when the agent cannot produce a clean draft |

### The SBI Trade Credit book (real companies, live news)

A second dataset under `data/sbi/`: one insurer, **SBI Trade Credit**, covering ten real
US companies (Nvidia, Microsoft, Apple, Walmart, Caterpillar, Intel, Boeing, Ford, Nike,
Starbucks). The companies, SEC CIKs and headquarters are real; **the credit limits,
invoices and payments are illustrative** - everyone pays on or near time, so what moves
a score is real news, never an invented payment problem at a real company. Every page
says so.

```bash
EWS_DATASET=sbi python3 -m ews.fetch_news            # fetch the last 180 days of news
EWS_DATASET=sbi python3 -m ews.run                   # score it
EWS_DATASET=sbi python3 -m dashboard.server 8001     # http://localhost:8001
python3 -m ews.sbi_seed                              # re-date the ledger to today
```

News comes from the sources in `data/sbi/trusted_sources.csv` - edit it to change them:

| Source | What | Notes |
|---|---|---|
| SEC EDGAR Form 8-K | what the company itself reported (bankruptcy, debt acceleration, restatement, restructuring, officer changes...) | free, official, no key; set `SEC_USER_AGENT` to your organisation and email |
| Google News RSS | press coverage, **kept only from the listed publishers** (Reuters, AP, Bloomberg, WSJ, FT, CNBC...) | headline only - the feed carries no article body |

Fetching writes `data/sbi/news_articles.csv`; the engine reads that file, so runs stay
reproducible and the agent cache still works. The dashboard's **Fetch latest news**
button does the same and re-scores.

**Auto refresh** is an on/off switch next to that button. Off by default. While on, the
dashboard fetches and re-scores every 15 minutes in the background, shows when the next
fetch is due, and the open home page reloads itself each minute. Switching it on fetches
straight away. The switch lives in **`settings.json`** at the project root:

```json
{ "news": { "auto_refresh": false, "refresh_minutes": 15,
            "lookback_days": 180, "stories_per_company": 12 } }
```

Edit it and the dashboard follows within seconds, no restart; the button writes the same
file. A typo is reported on the page and the previous settings stay in force. Fetching is
free (no API key); a failed fetch keeps the previous news, and two fetches never run at
once. On this book a story typed on the Live input page is
labelled **HYPOTHETICAL** everywhere it appears. The harness grades the synthetic
dataset only - there are no labels for real companies.

---

## What was built

A deterministic spine with autonomous Claude agents at the leaves, joined by one typed
Evidence Store. Evidence producers never score risk; a single Adjudicator emits the only number;
the case-file writer can explain a verdict but never change one.

```
  EVIDENCE   Payment Behaviour   agent over a deterministic ledger, per insurer line
             News Intelligence   agent, one run per article, incl. parent contagion
                      │
  EVIDENCE STORE      │          typed, dated, source-cited
                      │
  JUDGMENT   Risk Adjudicator    formula emits the only number; agent reviews it
                      │
  ACTION     Limit recommendations → Case File agent → dashboard
             Harness grades every run against the labels
```

### The score

```
Risk Score = 0.65 × Payment Score + 0.35 × News Score      Healthy 0–19 · Watch 20–49 · High Risk 50–100
```

**Payment** is the worst open invoice: linear to 40 points at 30 days past due — which
is every insurer's overdue reporting window — then two points a day, capped at 100 at
60 days.

**News** takes the buyer's strongest article, scores it by severity -
0 / **20 / 40 / 60 / 80 / 100** for severity 0 / 1 / 2 / 3 / 4 / 5 -
and decays it on a **365-day half-life**. That number is measured, not chosen: a
180-day half-life drops Emberline below the Watch line, and no decay at all lets a
two-year-old story carry full weight.

| Severity | Meaning | Points | Weight | Adds on day 0 |
|---|---|---|---|---|
| 0 | neutral or positive - appointments, results, expansion | 0 | - | 0 |
| 1 | minor negative - analyst stock downgrade, short outage, minor lawsuit | 20 | 0.35 | 7 |
| 2 | notable negative - guidance cut, profit warning, layoffs, store closures | 40 | 0.35 | 14 |
| 3 | mild credit negative - capacity cut, legal notice, contract loss, major lawsuit or probe, sudden CEO/CFO exit, scandal | 60 | 0.35 | 21 |
| 4 | moderate - unpaid vendors, lenders reviewing exposure, credit downgrade, restatement, CEO/CFO exit, mass layoffs | 80 | 0.35 | 28 |
| 5 | severe - unpaid wages, debt restructuring or default, insolvency | 100 | 0.35 | 35 |

Every severity is weighted at 35%, so news alone adds at most **35** (a severity 5
story published today). With the Watch line at 20, a fresh severity 3, 4 or 5 story
moves a buyer that pays on time to **Watch** on its own - a CEO exit (severity 4)
scores 28 - and it returns to Healthy as the story decays. News alone never reaches
High Risk at 50; that takes the ledger too. Risk appetite (`PD_TARGET_SCORE`) stays at
score 35, so a Watch buyer below 35 is watched but its limit is maintained.

**The cost of the lower Watch line:** payment alone reaches it at 23 days past due. On
the sample data that puts five buyers that never default (one invoice 25 days late, no
news) on Watch, and the harness reports it - 17/22 survivors clean.

Vandermeer, the severity-5 trap in the baseline, stays Healthy: its story is 710 days
old and has decayed to about 3 points.

### What it guards against

**Wrong company.** The article names *Arcline Media BV*; the covered buyer is
*Arcline Fabrications NV*. Resolution is deliberately reluctant — the brand token
must match exactly one entity, and every remaining distinguishing word in the mention
must appear in that entity's own registered name. It accepts `Arcline`, `Arcline Inds.`
and `ARCLINE FABRICATIONS NV`; it refuses `Arcline Media BV`. Measured at
**33/33 genuine mentions resolved, 5/5 decoys refused.**

**Trouble upstream.** A parent-company story fans out to every subsidiary one rung down
the severity ladder — severe for the parent is moderate for the subsidiary. One story
about Northpoint reaches both its subsidiaries; Westbridge absorbs it and stays Healthy
because it pays on time, Marchetti crosses into Watch because it is already 25 days
behind. Same article, different outcomes, decided by the books.

**Invented numbers.** The case-file writer receives a facts dict and may use only those
values. Every numeric token it writes back is checked against them, and one unmatched
figure discards the whole text for a template built from the same facts.

**Reading the answers.** `ground_truth.csv` and `payment_behaviour_monthly.csv` hold
labels. `loader.py` raises `LeakageError` if engine code opens them and strips the
`gt_*` columns from news before an article can reach the LLM. A test asserts that no
file under `ews/` or `dashboard/` even names them.

### What it recommends

Every alert names a lever with a number on it. Per insurer line, from expected loss —
`EL = PD × min(max_liability, limit × indemnity × (1 − deductible))` — against a fixed
risk appetite of 25%:

| Action | When |
|---|---|
| **FREEZE** | above appetite and already owed at or above the limit |
| **REDUCE** | above appetite — cut to the limit where expected loss meets appetite |
| **MAINTAIN** | within appetite |

Limits are never raised and never cut below what is already owed. Every recommendation
awaits a risk underwriter.

### The dashboard

Home → Client → Buyer, using TCS-Frontend's design tokens verbatim. Adlerhof renders in
its real theme variation; insurers without a published variation fall back to the
default. No colour appears outside `theme.css`, and a test enforces it. Each insurer
sees only its own buyers — and no rival is named anywhere on the page, including in the
footer.

The buyer page has five tabs: the **Case File** is the story, and **Score**, **Limit**,
**Payments** and **News** are the evidence behind it, so every figure can be traced
back to a row in a CSV.

The Case File is a draft for a risk underwriter, not a decision. They review it
and approves, amends or rejects the recommended limit action; nothing changes on an
insurer's book until they do. The dashboard shows the file but does not yet record the
risk underwriter's decision.

---

## Results

Measured on both paths — the rule-based fallback, and the four agents on Claude.

| Gate | Rules | Claude |
|---|---|---|
| Defaulters flagged | **4/4** | **4/4** |
| Survivors left Healthy | **22/22** | **22/22** |
| Wobblers and the three severity-5 traps | all Healthy | all Healthy |
| Entity resolution — recall | **33/33** | **33/33** |
| Entity resolution — **decoys refused** | **5/5** | **5/5** |
| Severity agreement with labels | 32/32 | 29/32 — see below |
| Parent fan-out | pass | pass |
| Case file figures traced to the engine | 26 templated | **4 model-written, 0 discarded** |
| Tests | **132/132** | — |

**The decoys held against a real model.** Given search tools and free rein to
investigate, Claude still refused all five — including `Halberg Jewellers GmbH`
against `Halberg Textiles GmbH`. That was the defence most likely to break.

**The case-file guard passed its first real test.** Four Opus 5 drafts, every figure
checked against the engine's own numbers, none discarded.

**The three severity disagreements look like the labels being coarse, not the model
being wrong.** The labels map `capacity_cut → 3` mechanically; Claude read *"cut from
three shifts to one, halted contract worker recall, slowed material procurement"* and
called it 4. That is what moves Maasland from 62.2 to 66.9 on the Claude path.

Baseline on the rules path: Arcline **63.3** and Maasland **62.2** High Risk; Halberg
**42.7** and Emberline **37.2** Watch; 22 Healthy; 4 decoys refused. On Claude the
same four are flagged, with Maasland at **66.9**.

Emberline sits **2.2 points** above the Watch line and is the binding constraint — any
change to the half-life, the news ladder or the 65/35 split must be re-checked against
it first.

---

## Layout

| Path | What |
|---|---|
| `ews/config.py` | every fixed constant — weights, bands, decay, PD curve |
| `ews/loader.py` | CSV access and the leakage boundary |
| `agents/` | the four agent definitions, one `.md` each |
| `ews/settings.py` | model, effort, limits and guardrails for each agent |
| `ews/agents/` | their tools and checks, `definition.py` (reads the `.md` files) and `runtime.py` (the agent loop) |
| `ews/limits.py` · `ews/casefile.py` · `ews/run.py` | recommendations, case file + guard, orchestrator |
| `ews/llm.py` | Claude client, deterministic fallback, disk cache |
| `harness/evaluate.py` | the only module permitted to read the labels |
| `dashboard/` | local multi-page app and the TCS design tokens |
| `tests/test_gates.py` | leakage, determinism, formulae, resolver, guard, theme |
| `data/` | the synthetic dataset; `harness_articles.csv` holds labelled stories only the harness reads |
| `docs/PLAN.md` | the specification this was built from, with every decision and its evidence |
| `docs/WALKTHROUGH.md` | what every file does, and where each number on screen comes from |
| `docs/PRESENTATION.md` | the five minutes: the video script, the live demo, and the Q&A |
