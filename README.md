# Buyer Early Warning Agent

> **HACKATHON PROTOTYPE · SYNTHETIC DATA**
> Every buyer, insurer, invoice and news article in this repository is fabricated.
> No real counterparty, client or portfolio appears anywhere in it. Not reviewed by
> Risk or Compliance, and not a product.

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
| `harness.evaluate` | grades that run against the labels — 9 gates |
| `unittest discover -s tests` | leakage, determinism, formulae, resolver, guard, theme, agent loop, agent definitions, settings — 40 tests |
| `dashboard.server` | serves the dashboard on http://localhost:8000 (Ctrl-C to stop) |

**No install, no API key, no network.** Everything above runs on the Python 3 standard
library. Run them from the repository root.

The dashboard blocks the terminal, so give it its own window. The live demo is at
http://localhost:8000/demo (linked from the home page): press **Publish article** eight times to walk the whole story.
[`docs/DEMO_GUIDE.md`](docs/DEMO_GUIDE.md) says what each step is meant to prove.

### Switching the agents on

The four agents (Payment Behaviour, News Intelligence, Risk Adjudicator, Case File)
are autonomous Claude agents: each gets read-only tools over the engine's data,
decides what to look at and when it has seen enough, and ends by calling a `submit_*`
tool whose input code checks. Without Claude, each falls back to its rule-based path,
so the demo, harness and tests always work offline. To use Claude:

```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...
python3 -m ews.run
```

Claude is picked up automatically once both are in place. To force the rule-based
path back on:

```bash
EWS_LLM=fallback python3 -m ews.run
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
| Case File | the write-up | must call `get_verdict` and `get_limits` first; `verify_figures`; `figure_tolerance`; `run_for_bands` | template when the agent cannot produce a clean draft |

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
Risk Score = 0.65 × Payment Score + 0.35 × News Score      Healthy 0–34 · Watch 35–59 · High Risk 60–100
```

**Payment** is the worst open invoice: linear to 40 points at 30 days past due — which
is every insurer's overdue reporting window — then two points a day, capped at 100 at
60 days.

**News** takes the buyer's strongest article, scores it 0 / 20 / 45 / 75 by severity,
and decays it on a **365-day half-life**. That number is measured, not chosen: a
180-day half-life drops Emberline below the Watch line, and no decay at all lets a
two-year-old story carry full weight.

News alone tops out at 0.35 × 75 = **26.25**, below the Watch line at 35. **Only
payment behaviour can flag a buyer.** That single constraint is what keeps the
severity-5 trap in Healthy.

### What it guards against

**Wrong company.** The article names *Arcline Media Pvt Ltd*; the covered buyer is
*Arcline Fabricators Limited*. Resolution is deliberately reluctant — the brand token
must match exactly one entity, and every remaining distinguishing word in the mention
must appear in that entity's own registered name. It accepts `Arcline`, `Arcline Inds.`
and `ARCLINE FABRICATORS LIMITED`; it refuses `Arcline Media Pvt Ltd`. Measured at
**33/33 genuine mentions resolved, 5/5 decoys refused.**

**Trouble upstream.** A parent-company story fans out to every subsidiary one rung down
the severity ladder — severe for the parent is moderate for the subsidiary. One story
about Northpoint reaches both its subsidiaries; Westbridge absorbs it and stays Healthy
because it pays on time, Chandra crosses into Watch because it is already 25 days
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
awaits an underwriter.

### The dashboard

Home → Client → Buyer, using TCS-Frontend's design tokens verbatim. Aldermont renders in
its real theme variation; insurers without a published variation fall back to the
default. No colour appears outside `theme.css`, and a test enforces it. Each insurer
sees only its own buyers — and no rival is named anywhere on the page, including in the
footer.

The buyer page has five tabs: the **Case File** is the story, and **Score**, **Limit**,
**Payments** and **News** are the evidence behind it, so every figure can be traced
back to a row in a CSV.

---

## Results

| Gate | Result |
|---|---|
| Defaulters flagged | **4/4** |
| Survivors left Healthy | **16/16** |
| Wobblers and the severity-5 trap | all Healthy |
| Entity resolution — recall / decoys refused | **33/33** / **5/5** |
| Severity agreement with labels | **32/32 exact** |
| Demo replay, steps 1–8 | reproduces the planned scores |
| Tests | **18/18** |

Baseline: Arcline **63.3** and Girikand **62.2** High Risk; Suvarna **42.7** and
Emberline **37.2** Watch; 16 Healthy; 4 decoys refused.

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
| `data/` | the synthetic dataset; `data/demo/` drives the live demo |
| `docs/PLAN.md` | the specification this was built from, with every decision and its evidence |
| `docs/DEMO_GUIDE.md` | the live demo script |
