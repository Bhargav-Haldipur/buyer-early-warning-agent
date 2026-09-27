# The 5 minutes — video (2:00) + live (2:30)

> **Hard cap 5:00. Overrun is negatively marked.**
> **B = Bhargav**, **S = Sarvagya**. Both speak in both halves.
>
> Submitted as: *a 2-minute video followed by a 2½-minute live demo.* Say that when you
> submit, so nobody is surprised when the video stops.

## Why this split

The rubric rewards two different things, and one format cannot carry both.

| | Carries | Why that format |
|---|---|---|
| **Video 2:00** | Business Value (20%), Technical Execution (15%), *"show it calling tools"* | Narration and cached screens. Nothing can go wrong, pacing is exact, and it buys back the 45 seconds you'd lose fumbling live. |
| **Live 2:30** | **Working Demo (30%)**, *"show guardrails / what it does when unsure"* (part of 25%) | A judge types the input. That is the one thing a video cannot earn, and the rubric asks for it by name. |

**Do not demo the scripted 8-step `/demo` page.** The live sandbox supersedes it. Keep it
loaded in a tab purely as the wifi-failure fallback.

---

# PART 1 — Video (2:00, ~305 words)

Record tonight. Screen recording, both voices. All screens are cache-warm, so nothing
waits on the network.

### 0:00 – 0:25 · The problem — **B** *(65 words)*

> *Home page.*

"A credit insurer pays the supplier when the supplier's customer doesn't. So its entire
exposure sits on companies it has **no relationship with** — it never sees their books.

Limits get reviewed **quarterly**. On this book, four of twenty-six buyers go on to fail.
Under quarterly review you find out when the claim lands, and by then the limit you could
have cut is fully drawn."

### 0:25 – 0:55 · The solution — **S** *(75 words)*

> *Click into Adlerhof — the book, sorted by expected loss.*

"Two signals. **How the buyer pays us** — our own invoice ledger, sixty-five percent.
**What the world says about it** — news, thirty-five, decayed so a story halves in weight
every year.

Four Claude agents do the reading. Out comes one score, one band, and a recommended limit
action with a euro figure on it.

One rule holds the whole thing together: **the agents produce judgement, the code produces
every number.** No score is ever a model's opinion."

### 0:55 – 1:25 · The agents are real — **S** *(75 words)*

> *Arcline → **Agents** tab. Scroll through the four cards.*

"Four agents, and every tool call each one made is here. Payment read the ledger. News
searched our registry and checked the company's sector and city against the story. The
Adjudicator reviewed the verdict — it can challenge a score, it cannot change one. The
Case File agent wrote it up, and every figure it wrote was checked against the data first.

When a guardrail sends an agent back, that shows here too."

### 1:25 – 1:50 · The proof — **B** *(65 words)*

> *Terminal: `python3 -m harness.evaluate`, 9/9 green.*

"A demo proves nothing on its own. Everything is graded against labels the engine is
**physically forbidden to read** — the loader raises if engine code opens them.

Nine gates. Four of four defaulters caught. Twenty-two of twenty-two survivors clean.
Thirty-three of thirty-three entity matches right, five of five decoys refused. A hundred
and eleven tests underneath, and these pass **with no API key at all.**"

### 1:50 – 2:00 · Handoff — **B** *(25 words)*

"Everything so far was prepared. So for the last two minutes we'd like one of you to give
us something we haven't seen."

> **Cut. Stop the video. Switch to the browser, `/live` tab.**

---

# PART 2 — Live (2:30)

One tab: **`/live`**. A second tab on `/demo` as the fallback. Do not switch tabs otherwise.

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
| **"Who uses this on Monday?"** | B | "The underwriter doing limit reviews. Today that's a quarterly queue; this is a daily one, ranked by money, with the file already drafted." |
| **"How do you know it isn't tuned on the answers?"** | B | "The labels are unreadable to the engine — the loader raises, and a test greps every file to prove none of them even names them." |
| **"Biggest trade-off?"** | B | "The model never produces a number. Costs some fluency in the write-up; buys an auditable score, which a regulated insurer can't do without." |
| **"Why not just watch payment data?"** | S | "You already do, and it's late. Fifty-seven days versus forty-five is the whole argument." |
| **"Could news alone flag someone?"** | S | "No, by design — news tops out at 26 points and Watch starts at 35. Only money crosses a line." |
| **"What does it cost to run?"** | B | "Measured, not estimated — printed every run. A full pass over 26 buyers is 87 agent runs, a couple of dollars; roughly eight cents per buyer per day." |
| **"What breaks at 10,000 buyers?"** | S | "Entity resolution against a real company master, and news volume — 87 runs a day becomes 30,000. It fans out fine; cost is the constraint, not the design." |
| **"What would you change for production?"** | B | "A real news feed instead of a CSV, entity resolution against LEI or Orbis, the underwriter's approve/amend/reject written back, and weights backtested on a real book rather than reasoned about." |
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
