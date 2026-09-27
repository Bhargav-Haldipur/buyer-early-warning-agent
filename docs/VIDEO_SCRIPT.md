# Submission video — script (5:00 max)

> Two presenters. **B = Bhargav**, **S = Sarvagya**. The split follows what each of us
> actually built, so questions afterwards land on the right person.
>
> - **B** — the domain model, the dataset, the scoring engine, the leakage boundary,
>   the harness and the spend controls.
> - **S** — the autonomous agent runtime, the markdown agent definitions, the per-agent
>   settings and guardrails, the structured case file, the dashboard's underwriter framing.

Screen recording throughout, both voices over it. **726 spoken words ≈ 4:41 of speech; the four demo clicks fit inside the demo's own
window, landing the whole thing at about 4:55.** Read at a normal pace — the timings already allow for it.

---

## Pre-flight — before you hit record

```bash
cd ~/Projects/buyer-early-warning-agent
export ANTHROPIC_API_KEY=$(cat ~/.anthropic-key)

python3 -m unittest discover -s tests -q      # expect 96 OK
python3 -m harness.evaluate                   # expect 9/9   ← leave this on screen for 3:22
python3 -m dashboard.server                   # http://localhost:8000
```

In the browser, **click "Publish article" four times** so the demo panel sits at step 4.
You record from step 5 — the decoy — because that is the beat that sells the system and
there is no time to walk all eight.

Two tabs open: **(1)** Adlerhof's insurer page, **(2)** `/demo`.

> ⚠ Warm the case-file cache first (see *Notes*), or steps 5–8 will pause on camera
> while Claude writes four fresh case files.

---

## 0:00 – 0:32 · The problem — **B**  *(93 words · 36s)*

> *Home page.*

"A credit insurer promises to pay a supplier if that supplier's customer doesn't. So its
entire exposure sits on companies it has no relationship with. Usually the first warning
is the claim itself.

This is **Buyer Early Warning**. It watches every covered buyer daily and flags the ones
heading for default **while there is still credit limit left to cut**. On this book it
catches all four companies that go on to fail, with zero false alarms across
twenty-two survivors.

Everything here is synthetic — no real company, invoice or news story appears."

---

## 0:32 – 1:05 · Two signals, one number — **B**  *(84 words · 33s)*

> *Click into **Adlerhof Trade Credit** — the sortable book.*

"Every buyer gets one score from two signals.

**How it pays us** — the worst overdue invoice on our own ledger. Sixty-five percent.

**What the world says about it** — news, graded zero to five, and decayed: it halves in
weight every year and we stop reading it after two. Thirty-five percent.

Which means, deliberately, **news alone can never flag anybody** — the most it can
contribute is twenty-six points, and Watch starts at thirty-five. News changes the
ranking. Only money changes the verdict."

---

## 1:05 – 1:52 · The four agents — **S**  *(124 words · 48s)*

> *A High Risk buyer → the **Agents** tab. Scroll slowly.*

"Four Claude agents do the reading. Each is a markdown file — its tools and its
instructions — with read-only access to our data, deciding for itself what to look at.

**Payment** judges the trend. **News** runs once per article: it searches our registry
and checks sector and city against the story. The **Adjudicator** reviews the verdict.
The **Case File** agent writes it up. Every tool call each one made is on this tab.

And here's the invariant the system rests on — **agents produce judgement, code produces
numbers.** The News agent cannot submit a company it never looked up. The Adjudicator
can challenge a score; it cannot change one. Rejections go back to the agent to correct,
and they show up here too."

---

## 1:52 – 3:22 · The demo — **alternating**  *(174 words · 67s + 4 clicks)*

> *Switch to `/demo`. You are at step 4.*

**S** — "Each click publishes one story and re-runs the whole engine. Nothing is scripted."

> *Click **Publish article 5**.*

**S** — "A wage protest at **Kessler Logistics** — a logistics firm in Dortmund. Our
buyer is **Kessler Traders**, a steel trader in Essen. Same brand word. **Refused.**
Nobody's score moved."

> *Click **Publish article 6**. Point at Kessler → 47.7.*

**B** — "Same story, same day. **Kessler Traders.** One word different — accepted.
Forty-seven point seven, Watch.

That pair is the most important thing here. Five of the thirty-eight articles are about
companies that merely share a name with someone we cover. Get one wrong and you've
frozen a healthy customer's credit line."

> *Click **Publish article 7**. Point at Marchetti, then Westbridge.*

**S** — "Now a **parent holding company** in restructuring talks. It reaches both
subsidiaries at the same weight. **Marchetti** crosses into Watch. **Westbridge** stays
Healthy — because Marchetti is already twenty-five days behind and Westbridge pays on
time. Same news, different outcome. Neither signal gets there alone."

> *Click **Update payment data**. Kessler → 65.0, High Risk.*

**B** — "Now the payment data catches up. Kessler hits **sixty-five, High Risk**, and the
recommendation flips to a limit cut.

Kessler was already on the watchlist from news **before** its books moved. That gap is
the product."

---

## 3:22 – 4:02 · The proof — **B**  *(104 words · 40s)*

> *Terminal: the 9/9 harness output.*

"A demo proves nothing on its own. So everything is graded against labels the engine is
physically forbidden to read — the loader raises if engine code opens them, and a test
greps every file to check none of them even names them.

**Nine gates. Four of four defaulters caught. Twenty-two of twenty-two survivors clean.
Thirty-three of thirty-three entity matches right, five of five decoys refused.** Plus
determinism, the parent fan-out, and the demo replaying to the exact scores.

Ninety-six tests underneath. And these pass **without an API key** — the rule-based path
is always there, so anyone who clones this reproduces the numbers."

---

## 4:02 – 4:37 · What the underwriter gets — **S**  *(101 words · 39s)*

> *The **Case File** tab on Kessler.*

"None of that matters unless someone can act on it. So this is the deliverable: a
**draft case file awaiting underwriter approval** — the bottom line, the limit action
with a number on it, what would lift it, what would worsen it, every piece of evidence
cited by id.

The agent writes the judgement and never touches the arithmetic. **Every number it
writes is checked against the data before this page renders.** One figure that doesn't
trace and the draft goes back; fail twice and we render a template and say so.

Last full run: four written by Claude, **zero discarded**."

---

## 4:37 – 4:55 · Impact — **B**  *(43 words · 17s)*

> *Back to home, the three insurer cards.*

"Three insurers, twenty-six buyers, one screen. Every alert carries why it fired and
what to do about it.

Underwriters review limits quarterly. This watches them daily, says which four of
twenty-six to open first — and shows its working every time. Thank you."

---

## Notes

**Warm the cache before recording.** The demo steps re-run the Case File agent for each
newly flagged buyer, and four of those are not in the shipped cache — on camera they
would pause, or quietly fall back to the template and undercut the 4:02 section. One
warming pass fixes it permanently and the entries are committed for both of us:

```bash
export ANTHROPIC_API_KEY=$(cat ~/.anthropic-key)
for n in 3 4 5 6 7; do python3 -m ews.run --demo-steps $n; done
python3 -m ews.run --demo-steps 7 --swap-invoices
# each prints its own measured spend; expect well under a dollar in total
```

Re-run the same commands afterwards — every line should report
`spend: nothing — every agent run came from the cache`.

**Other things worth knowing on the day**

- Say "synthetic" once, early, and let the banner carry the rest. It is on every page.
- Every figure in this script is one the engine currently produces. If a number on
  screen differs, **say what is on screen** — do not read the script over it.
- If you overrun, cut **0:32–1:05**. The demo and the harness cannot be cut.
- If a click is slow, talk through it: the engine re-runs from scratch every time, and
  that is worth saying out loud rather than apologising for.
