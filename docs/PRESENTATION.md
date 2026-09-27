# The 5 minutes — video (2:00) + live (2:30)

> **Hard cap 5:00. Overrun is negatively marked.**
> **B = Bhargav**, **S = Sarvagya**. Both speak in both halves.
>
> Submitted as: *a 2-minute video followed by a 2½-minute live demo.*
> Budget: **2:10 video + 0:05 changeover + 2:34 live = 4:49**, eleven seconds under the
> cap. Have the browser already open on `/live` so the changeover is one keystroke. The
> live half is the part that can slip, so the slack belongs to it. Say that when you
> submit, so nobody is surprised when the video stops.

## Why this split

The rubric rewards two different things, and one format cannot carry both.

| | Carries | Why that format |
|---|---|---|
| **Video 2:10** | Business Value (20%), Technical Execution (15%), *"show it calling tools"* | Narration and cached screens. Nothing can go wrong, pacing is exact, and it buys back the 45 seconds you'd lose fumbling live. |
| **Live 2:30** | **Working Demo (30%)**, *"show guardrails / what it does when unsure"* (part of 25%) | A judge types the input. That is the one thing a video cannot earn, and the rubric asks for it by name. |

**Do not demo the scripted 8-step `/demo` page.** The live sandbox supersedes it. Keep it
loaded in a tab purely as the wifi-failure fallback.

---

# PART 1 — Video (aim 2:10)

Record tonight. Screen recording, both voices. Every screen is cache-warm, so nothing
waits on the network.

**343 spoken words.** That is **2:05** at 165 words a minute and **2:13** at 155 — so the
number is your delivery, not the script. Time your first take; it is a recording, and you
can hit any figure you want by pacing. If a take lands past 2:15, speak a touch faster
rather than cutting a section — nothing below is padding.

The section clocks below assume a brisk read with normal pauses.

### 0:00 – 0:54 · Today, and what's missing — **B** *(137 words)*

> *Home page.*

"A credit insurer pays the supplier when its customer doesn't. So its exposure sits on
companies it has no relationship with.

How much cover each one gets is the **risk underwriter's** call — not the one who prices
the policy, the one who sets a single buyer's limit.

That job is already automated: grading runs off company filings, limits get set on request
or when something trips a review.

What nobody does is look at **every buyer, every day**. Payment sits in the policy
system, news sits elsewhere, and the case for a cut is assembled by hand.

On this book the median limit was last looked at **six hundred and ninety-one days ago**,
and all four buyers that fail began deteriorating *after* their last review.

Nobody was asleep. The cycle is just slower than the risk."

> **Say "risk underwriter", not "underwriter".** The policy underwriter prices the
> seller's contract; the risk underwriter sets limits on individual buyers. This tool
> serves the second one only, and in a Tinubu room the loose term invites a clarifying
> question you have no clock for.
>
> **Do not say "they do this manually."** Grading is automated, most limit requests are
> auto-decided, and carriers pool overdue reports across policyholders — someone in that
> room does this for a living and will correct you in the first thirty seconds. *Periodic,
> siloed, and assembled by hand* is all true and all defensible.
>
> | Checkable on screen, from `credit_limits.csv` + `ground_truth.csv` | |
> |---|---|
> | Limit lines not reviewed in over a year | **20 of 26** |
> | Median days since last review | **691** |
> | Arcline | reviewed 2024-10-23 · deterioration began 2025-07-15 |
> | Halberg | reviewed 2024-11-14 · deterioration began 2025-11-05 |
> | Maasland | reviewed 2024-07-07 · deterioration began 2025-04-27 |
> | Emberline | reviewed 2024-11-13 · deterioration began 2025-05-25 |

### 0:54 – 1:15 · What we built — **S** *(54 words)*

> *Click into Adlerhof — the book, sorted by expected loss.*

"Two signals. **How the buyer pays us** — our invoice ledger, sixty-five percent.
**What the world says** — news, thirty-five, and it decays with age.

Four agents read; out comes one score, one band, and a limit action with a euro figure.

One rule holds it together: **agents produce judgement, code produces every number.**"

### 1:15 – 1:34 · The agents are real — **S** *(47 words)*

> *Arcline → **Agents** tab. Scroll through the four cards.*

"Every tool call each agent made is here. News searched our registry and checked the
company's sector and city against the story. The Adjudicator
reviewed the verdict — it can challenge a score, it cannot change one. When a guardrail
sends one back, that shows here too."

### 1:34 – 1:44 · What lands on their desk — **S** *(26 words)*

> *Same buyer → **Case File** tab. Don't scroll far; the top half is the point.*

"And this is what the risk underwriter gets — a draft they approve or amend, with every
claim cited back to an invoice or an article."

### 1:44 – 2:09 · Why you should believe it — **B** *(61 words)*

> *Terminal: `python3 -m harness.evaluate`, 9/9 green.*

"We know which four of these buyers actually failed. That answer key is a file the engine
is **physically forbidden to open** — it raises if you try.

Four of four caught, and **not one false alarm in twenty-two**. Both at once is the point
— flag everyone and you catch all four; flag nobody and you have no false alarms."

> **What this section is for — read this before you record it.**
>
> The most damaging question anyone can ask is *"you built the data and the system, so of
> course it works — you tuned it until it did."* This is the answer to that question, and
> it is the only reason the section exists. **One idea: the marking scheme is a file the
> thing being marked cannot open.**
>
> Deliver that idea, not a list of scores. An earlier draft read out five numbers and it
> washed over people — if you can't say why a number is there, cut it.
>
> **The insight that makes the numbers mean anything:** detection and false positives are
> in tension. Flag all 26 and you score 4/4. Flag none and you score 22/22. Either number
> alone is trivially gameable — passing both at once is the whole claim. Say that, or the
> two figures land as trivia.
>
> **What each of the nine gates defends against, for Q&A:**
>
> | If a judge says | Point at |
> |---|---|
> | "You tuned the weights until it worked" | The answer key raises `LeakageError` if engine code opens it, and a test greps every engine file to prove none of them names it. Code, not policy — see the three layers below. |
> | "You flagged everyone" | 22 of 22 survivors stayed Healthy |
> | "You flagged nobody" | 4 of 4 defaulters left Healthy |
> | "Your entity matching is keyword soup" | 33/33 genuine mentions resolved **and** 5/5 decoys refused — precision and recall together |
> | "It would flag anyone with a scary headline" | The trap gate: three buyers carry a severity-5 story and never default — Vandermeer, Oakhurst, Kessler — and all three stay Healthy |
> | "An LLM makes this unreproducible" | Determinism gate, and the whole suite passes with **no API key at all** |
> | "You cherry-picked the demo" | Demo replay reproduces the exact scores |
>
> The trap gate is the one worth knowing if anyone digs: those three buyers are **not named
> in the code**. They are derived at runtime as "any buyer carrying a severity-5 article who
> never defaults", because hardcoding the names would let a rename silently delete the
> check. It was written expecting one trap; deriving it found three.
>
> **If they push on "physically forbidden" — it is three layers, not one.**
>
> **1. Two files the engine cannot open.** `Loader.table()` raises `LeakageError` for
> `ground_truth.csv` and `payment_behaviour_monthly.csv` unless built with `harness=True`,
> which only `harness/evaluate.py` does. No flag, no env var, no accident.
>
> The second file is the one that shows judgement. It is not answers — it is monthly
> aggregates (`avg_days_past_due`, `max_days_past_due`, `pct_paid_late`). It is banned
> because it **hands the engine the trend it is supposed to infer**, and because a real
> deployment would not have that table at all. The engine only touches data production
> would actually have. That is also your answer to "what changes for production".
>
> **2. Columns stripped inside a file the engine does read.** `news_articles.csv` must be
> readable — it is the news signal — but it carries five `gt_*` answer columns, and the
> engine gets a redacted row. **The News agent cannot see that an article is labelled a
> decoy.** When it refuses a near-miss name live, it is refusing on sector and name, not
> because a column told it to. This is the layer that makes the live refusal mean something.
>
> **3. A test that greps your own source.** Layers 1 and 2 only hold if everything goes
> through the Loader, so a test greps every `.py`, `.html` and `.css` in `ews/` and
> `dashboard/` and fails if any of them so much as *names* the label tables. `loader.py` is
> the one exemption — it names them in order to refuse them.
>
> The word doing the work in the script is **physically**. Escalate in that order only if
> asked; do not volunteer all three in the video.

### 2:09 – 2:16 · Handoff — **B** *(18 words)*

"Everything so far was prepared. Now we'd like one of you to give us something we haven't
seen."

> **Cut. Stop the video. Switch to the browser, `/live` tab.**

---

# PART 2 — Live (2:30)

One tab: **`/live`**. A second tab on `/demo` as the fallback. Do not switch tabs otherwise.

**Only 81 seconds of this is talking.** The rest is typing, three ~8-second agent runs,
and the judge deciding. Realistically:

| | Speech | Action | Total |
|---|---|---|---|
| Ask the judge | 8s | ~12s for them to answer | 20s |
| Story 1: click the name chip, type headline + one line of body, submit | 8s | ~22s typing + 8s run | 30s |
| Read the result | 5s | ~15s pointing | 20s |
| Story 2: change **only** the company field, submit | 24s | ~8s typing + 6s run | 38s |
| Ledger: pick the buyer, type 45, submit | 22s | ~8s + 11s run | 41s |
| Close | 2s | — | 5s |
| | | | **~2:34** |

That is over budget before anything goes wrong, so: **click the name chip rather than
typing it, keep the headline to six words, and keep the body to one short sentence** —
"Staff protested over delayed wages" is enough for the agent to grade. Leave the headline
and body untouched for story 2; only the company changes.

**If you are running long, cut the ledger beat** and say the line instead: *"and when the
payment data catches up, this buyer goes to High Risk at forty-five days instead of
fifty-seven."* You lose the demo but keep the argument. Never cut the refusal — it is
what the rubric asks for by name.

### 0:00 – 0:20 · Hand over the keyboard — **S**

> *`/live`, already open, reset to the shipped dataset.*

"Nothing from here is prepared. There's the book — **pick any company on it**, and give me
a headline. Anything you like."

> *Click their company in the row of name chips under the field — it fills exactly as
> registered — then type their headline and one line of body. Submit.*

### 0:20 – 0:50 · Narrate the wait — **S**

> *~8 seconds. Do not go quiet.*

"It's searching our registry now, pulling that company's record, checking its line of
business and its city against what the story says, and grading how bad it is for their
ability to pay. This story did not exist thirty seconds ago — there's nothing cached."

### 0:50 – 1:10 · The result — **S**

> *Point at the band crossing, then the tool list.*

"Healthy to Watch. And there are the tool calls it made to get there."

### 1:10 – 1:50 · What it does when it isn't sure — **B**

> *Same headline. Change only the company to a near-miss — keep the first word, change
> the business. The hint under the field gives you one.*

"Same story, same day. One word different in the name — and it's **refused.** Nothing
scored, and it says why.

That's the defence that matters most. A wrong match freezes a healthy customer's credit
line, so when the agent can't place a name it says so instead of guessing. Five of the
articles in this dataset exist purely to try to trip that."

### 1:50 – 2:20 · The two signals together — **B**

> *Age that same buyer's worst invoice to **45** days. Submit.*

"Now the payment side. Forty-five days late — **High Risk**, and the recommendation flips
to a cut.

Here's the number worth keeping: on payment alone this buyer doesn't reach High Risk until
**fifty-seven** days. With the news signal it gets there at **forty-five**. That's **twelve
days of lead time** — twelve days where there's still limit left to cut."

### 2:20 – 2:30 · Close — **B**

"That's the product. Thank you."

> **Stop. Do not add anything.** If you're early, that's a win.

---

# Q&A — keep this even if they don't schedule it

The new brief doesn't mention Q&A; the earlier one gave it five minutes. Assume it may
happen. **One sentence, then stop.** Whoever built it takes it.

| Question | Who | Answer |
|---|---|---|
| **"Is any of that hardcoded?"** | B | "You chose the company and the headline. Same code path as everything else — the loader doesn't know where a story came from." |
| **"What if the agent gets it wrong?"** | S | "Three layers: it can only submit an entity it actually looked up, the Adjudicator can challenge a score but not change it, and every figure in the write-up is checked against the data — fail twice and a template renders and says so on the page." |
| **"What if Claude is down?"** | S | "Every agent has a deterministic fallback; any failure drops that one item to rules and the run finishes. All nine gates pass with no API key." |
| **"691 days? We review annually."** | B | "It's a synthetic book, built so the gap is visible on one screen. The mechanism doesn't depend on the number — at any cadence, deterioration that starts between reviews is invisible until someone looks, and on this book all four failures began deteriorating after their last review." |
| **"Doesn't the insurer already monitor buyers?"** | B | "Yes — grading and overdue reporting both exist. What doesn't exist is the two fused into one daily queue ranked by money with the limit action already drafted. We're not replacing the monitoring; we're deciding what the underwriter opens first." |
| **"Who uses this on Monday?"** | B | "The **risk underwriter** — the one who sets limits on individual buyers, not the policy underwriter who prices the seller's contract. Today they work a queue driven by limit requests and triggers; this is a daily one ranked by money, with the file already drafted." |
| **"How do you know it isn't tuned on the answers?"** | B | "The labels are unreadable to the engine — the loader raises, and a test greps every file to prove none of them even names them." |
| **"Biggest trade-off?"** | B | "The model never produces a number. Costs some fluency in the write-up; buys an auditable score, which a regulated insurer can't do without." |
| **"Why not just watch payment data?"** | S | "You already do, and it's late. Fifty-seven days versus forty-five is the whole argument." |
| **"Could news alone flag someone?"** | S | "No, by design — news tops out at 26 points and Watch starts at 35. Only money crosses a line." |
| **"What does it cost to run?"** | B | "Measured, not estimated — printed every run. A full pass over 26 buyers is 87 agent runs, a couple of dollars; roughly eight cents per buyer per day." |
| **"You know we pool overdue data across all policyholders?"** | B | "Yes, and that's a stronger signal than anything here — we see one insurer's view of one buyer. Pooled, the payment side gets better and nothing about the design changes; the news side and the drafted case file are what we're adding." |
| **"What breaks at 10,000 buyers?"** | S | "Entity resolution against a real company master, and news volume — 87 runs a day becomes 30,000. It fans out fine; cost is the constraint, not the design." |
| **"What would you change for production?"** | B | "A real news feed instead of a CSV, entity resolution against LEI or Orbis, the risk underwriter's approve/amend/reject written back, and weights backtested on a real book rather than reasoned about." |
| **"Did you both build it?"** | both | B: engine, scoring, dataset, leakage boundary, harness, spend controls. S: agent runtime, markdown agent definitions, guardrails, case file, dashboard. `git shortlog -sne` if they want it. |

---

# Before you submit

```bash
cd ~/Projects/buyer-early-warning-agent
export ANTHROPIC_API_KEY=$(cat ~/.anthropic-key)
python3 -m unittest discover -s tests -q      # 111 OK, ~2s, no network
python3 -m harness.evaluate                   # 9/9
.venv/bin/python -m dashboard.server
```

- **Rehearse the live half three times**, timed, with someone else choosing the company.
  It is the only part that can go wrong and it is 30% of the marks.
- **Record a 60-second backup clip of the live half working.** If the room's network dies
  you play it and say so. Cheap insurance; you will probably not need it.
- **Reset `/live` before you present.** Last rehearsal's inputs must not be on screen.
- Have `docs/WALKTHROUGH.md` §2 — the flow diagram — open on a second screen. It is your
  architecture slide and it answers *"smart choices for a three-day build?"* without a deck.

## If it goes wrong live

- **A story hangs past 20s** — keep talking, then *"we'll take the prepared path"* and
  switch to `/demo`, fully cached, no network needed.
- **Wifi dies** — restart without `ANTHROPIC_API_KEY`. Everything still runs on rules.
  Say so out loud: it's the fallback working, not a save.
- **A judge names a company you don't cover** — perfect. That's the refusal beat early.
- **A typed name gets refused unexpectedly** — *"that's the reluctance rule"* — retype it
  from the list. Don't argue with it.
- **You're at 4:30 with content left** — go straight to the close. Short beats over.
