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

How much cover each one gets is the **risk underwriter's** call. Grading and limit
decisions are already automated — that part works.

What isn't automated is **the brief**. When a buyer comes up for review, someone pulls the
financials, finds the old memos, compares exposure and payment behaviour, reads the
external reports. Our own estimate for that is **thirty to sixty minutes per buyer**.

So nobody does it for every buyer, every day. On this book the median limit was last
looked at **six hundred and ninety-one days ago**, and all four buyers that fail began
deteriorating *after* their last review.

Nobody was asleep. The cycle is just slower than the risk."

> **Say "risk underwriter", not "underwriter".** The policy underwriter prices the
> seller's contract; the risk underwriter sets limits on individual buyers. This tool
> serves the second one only, and in a Tinubu room the loose term invites a clarifying
> question you have no clock for.
>
> **Be precise about what is and isn't manual — the line is not where you'd guess.**
>
> - **Grading and limit decisioning: automated.** Carriers score tens of millions of
>   companies continuously and auto-decide most limit requests. Claim this is manual and
>   someone in the room who does it for a living corrects you in the first thirty seconds.
> - **The underwriting brief: manual.** Tinubu's own *Buyer Intelligence Synthesizer*
>   spec says underwriters "manually pull and read financial statements, search for past
>   underwriting memos, compare exposures and payment behavior" and puts it at **30–60+
>   minutes per buyer**, with an expected **60–80% reduction**. That number is internal,
>   so say "our own estimate" — it lands harder than anything you could assert yourself.
>
> **You are proving the software, not the insurance.** Tinubu sells TCS to carriers and
> MGAs; the risk underwriter is your customer's employee, not yours. Frame every benefit
> as a TCS capability.
>
> **Both halves of this are already on the roadmap** — `Product / TCS Strategy & Vision /
> Agentic AI`, product TCS-ATLAS: *AI Notifiable event — Early warning & portfolio
> monitoring* (Gain: Medium) and *Automated Underwriting Brief — Buyer Intelligence
> Synthesizer* (Gain: High). Naming them is a strength, not a weakness: this is not a
> science project, it is two backlog items working. The Early Warning spec even lists
> "match buyer names across databases for global buyers with subsidiaries" as an
> **optional advanced** capability — that is your entity resolution and parent contagion,
> and you built the stretch goal.
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

"Two ideas already sit in the TCS-ATLAS backlog: **Early Warning**, and the **Automated
Underwriting Brief**. We built both, fused into one.

Two signals. **How the buyer pays us** — our invoice ledger, sixty-five percent.
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

**Every beat is on one buyer — Nordkrans Steel Traders AB** (Steel Trading, Malmö,
insured by Nordhaven). One narrative, and a €1.46M limit, so the cuts are legible from
the back of the room.

**Only ~85 seconds of this is talking.** The rest is typing, three ~7-second agent runs,
and the judge deciding. Click the name chip rather than typing it, keep the headline to
six words, keep the body to one sentence.

**Measured: ~2:42 with the optional beat, ~2:27 without it.** Plan to cut it — it is
marked, and it is the only thing in here that is not load-bearing. If you are still long
after that, say the ledger line without demoing it. **Never cut the refusal** — it is what
the rubric asks for by name.

### 0:00 – 0:20 · Hand over the keyboard — **S**

> *`/live`, reset, already open.*

"Nothing from here is prepared. There's the book — **pick any company on it**, and give me
a headline. Anything you like."

> *If they pick their own, use it. If they defer, use Nordkrans and the story below.*
> *Click the name chip. Type the headline. One sentence of body. Submit.*

| | |
|---|---|
| Company | click the **Nordkrans** chip |
| Headline | `Steel trader misses payroll for a second month` |
| Body | `Nordkrans Steel Traders AB has missed payroll for a second consecutive month at its Malmo yard, three workers said. Union talks have stalled.` |

### 0:20 – 0:50 · Narrate the wait, then the result — **S**

> *~7 seconds. Do not go quiet.*

"It's searching our registry, pulling that company's record, checking its line of business
and its city against the story, and grading how bad it is for their ability to pay. This
story didn't exist thirty seconds ago — there is nothing cached."

> *Result lands: 21.7 → 47.7, Healthy → Watch. Point at the tool list.*

"Healthy to Watch. And there are the tool calls it made to get there."

### 0:50 – 1:25 · What it does when it isn't sure — **B**

> *Change **only** the company field. Leave the headline and body untouched.*

`Nordkrans Yachting Ltd`

> *Say this before submitting: "Same story. Same day. One word different in the name."*

"**Refused.** Nothing scored — and it says why: a Southampton leisure-boat firm is not a
Malmö steel trader.

A wrong match freezes a healthy customer's credit line, so when it can't place a name it
says so instead of guessing. And it **cannot see which of these are decoys** — those
columns are stripped before an article reaches it."

### 1:25 – 1:40 · *(optional — cut this first)* It doesn't need the name — **B**

> *Clear the company field entirely. Leave the headline and body.*

"It doesn't even need that field. The company name is only in the body now — nothing tells
it who this is about."

> *Still finds Nordkrans, still grades it 5.*

### 1:40 – 2:15 · What the underwriter actually does — **B**

> *Age an invoice: **Nordkrans**, **45** days. Submit — then open the **Limit** tab.*

"Forty-five days late. Seventy-one point five, **High Risk**.

And here's what the risk underwriter does with that. The recommendation was **maintain a
one-point-four-six million limit**. It's now **reduce to five hundred and eleven
thousand**. Expected loss on that line was a hundred and thirty thousand — it's now
**seven hundred and ninety-seven**. That's exposure we were carrying without knowing.

On payment alone, with no news at all, those same forty-five days only reach Watch and the
cut stops at a million. **The news signal is worth half a million euros of cover we would
otherwise still be writing.**"

> **The numbers, verified — read them off the screen, not off this page.**
>
> | | Score | Band | Action | Limit → revised | Expected loss |
> |---|---|---|---|---|---|
> | baseline | 21.7 | Healthy | MAINTAIN | €1,460,000 | €130,342 |
> | + the story | 47.7 | Watch | REDUCE | → €968,941 | €420,736 |
> | + 45 days | 71.5 | High Risk | REDUCE | → €511,204 | €797,467 |
> | 45 days, no story | 45.5 | Watch | REDUCE | → €1,028,169 | €396,500 |
>
> €1,028,169 − €511,204 = **€516,965** — what the news signal is worth in cover.
>
> **If someone spots that expected-loss-after is €279,225 every time:** that is the
> formula working, not a bug. It cuts to wherever expected loss meets our risk appetite,
> so the after figure is the same by construction — what changes is how far it has to cut
> to get there.
>
> The Limit tab is code-generated, so it renders fully even though the sandbox skips
> commentary. Only the Case File tab falls back to the template while live input is in play.

### 2:15 – 2:25 · Close — **B**

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
| **"Isn't this already on our roadmap?"** | S | "Yes — *AI Notifiable event* and *Automated Underwriting Brief*, both TCS-ATLAS, both Priority 2. That's why we picked it. The point isn't the idea, it's that it works, and the entity matching the spec lists as an optional advanced capability is in there." |
| **"Doesn't the insurer already monitor buyers?"** | B | "Yes — grading and overdue reporting both exist. What doesn't exist is the two fused into one daily queue ranked by money with the limit action already drafted. We're not replacing the monitoring; we're deciding what the underwriter opens first." |
| **"Who uses this on Monday?"** | B | "The **risk underwriter** — the one who sets limits on individual buyers, not the policy underwriter who prices the seller's contract. Today they work a queue driven by limit requests and triggers; this is a daily one ranked by money, with the file already drafted." |
| **"How do you know it isn't tuned on the answers?"** | B | "The labels are unreadable to the engine — the loader raises, and a test greps every file to prove none of them even names them." |
| **"Biggest trade-off?"** | B | "The model never produces a number. Costs some fluency in the write-up; buys an auditable score, which a regulated insurer can't do without." |
| **"Why not just watch payment data?"** | S | "You already do, and it's late. Fifty-seven days versus forty-five is the whole argument." |
| **"Could news alone flag someone?"** | S | "Barely — news is weighted 35%, so a same-day severity 5 story adds 35 points, exactly the Watch line. Moving a band takes the ledger too." |
| **"What does it cost to run?"** | B | "Measured, not estimated — printed every run. A full pass over 26 buyers is 87 agent runs, a couple of dollars; roughly eight cents per buyer per day." |
| **"You know we pool overdue data across all policyholders?"** | B | "Yes, and that's a stronger signal than anything here — we see one insurer's view of one buyer. Pooled, the payment side gets better and nothing about the design changes; the news side and the drafted case file are what we're adding." |
| **"What breaks at 10,000 buyers?"** | S | "Entity resolution against a real company master, and news volume — 87 runs a day becomes 30,000. It fans out fine; cost is the constraint, not the design." |
| **"What would you change for production?"** | B | "Entity resolution stops being string matching — you resolve a buyer to a **company registry identifier**, a DUNS or a national registration number, which the platform already carries. Then a real news feed instead of a CSV, the underwriter's approve/amend/reject written back, and weights backtested on a real book rather than reasoned about." |
| **"Would this work on a real book?"** | S | "Structurally yes — whole-turnover cover over mid-market European debtors is the shape of this data, and the platform already holds the limits, payment terms and exposure we would read. Two honest gaps: we match buyers by name where production matches on a registry identifier, and we model one insurer per buyer, so we do not get the pooled overdue signal a carrier has across policyholders. Both make our job harder, not easier." |
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
