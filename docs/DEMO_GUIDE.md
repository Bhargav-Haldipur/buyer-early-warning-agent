# Live demo script

> **SAMPLE DATA**

```bash
python3 -m dashboard.server      # http://localhost:8000
```

Five buyers sit at exactly **21.7, Healthy** — each with one open invoice 25 days past
due and no news. Press **Publish article N** to append one article and re-run the
engine. Every score below is reproduced by `python3 -m harness.evaluate`.

| Step | What you publish | What the room sees |
|---|---|---|
| 1 | Marchetti appoints a new plant head | **Nothing moves.** 21.7 → 21.7. News that means nothing costs nothing. |
| 2 | Nordkrans scales back operations | 21.7 → **42.5**, **Watch**. Severity 3 at 35% on a buyer already 25 days behind. |
| 3 | Vendors say Larsson has fallen behind | 21.7 → **49.4**, **Watch**. Severity 4 on a buyer already 25 days behind. |
| 4 | Workers at Oakhurst protest unpaid wages | 21.7 → **56.3**, **Watch**. Severity 5 on the same payment position. |
| 5 | Kessler **Logistics** wage protest | **Refused.** No score moves. Wrong company — a 3PL in Dortmund, not the steel trader in Essen. |
| 6 | Workers at Kessler **Traders** protest unpaid wages | 21.7 → **56.3**, **Watch**. Same story, one token different, accepted. |
| 7 | Northpoint parent in restructuring talks | Reaches both subsidiaries at severity 4, counted at 35%: Marchetti 21.7 → **49.4 Watch**; Westbridge 13.0 → **40.7 Watch**. |
| 8 | Payment data updates — Kessler 25 → 40 DPD | 56.3 → **73.7, High Risk.** The limit action flips to a cut. |

## The three beats that matter

**Steps 5 and 6 are the pair.** The same wage-protest story, published on the same
day, on names differing by a single word. One is refused, one is accepted. That is
entity resolution earning its place — and it is the defence that matters most: five of
the 38 articles in play are about companies that merely share a brand token with a
covered buyer, and every one of them has to be refused.

**Step 7 is the fusion argument.** One parent story reaches both subsidiaries at the
same stepped-down severity, counted at 35% because the subsidiary is not the one in
the news. Marchetti, already 25 days behind, lands higher (49.4) than Westbridge (40.7).

**Step 8 is why lead time is worth money.** Kessler was already on the watchlist from a
news signal before its payment behaviour moved. By the time the payment data confirms
it, the risk underwriter has had the file open for a week.

## What to say if asked

- **"Could the news alone flag someone?"** Barely. News is weighted at 35%, so the
  strongest story - severity 5, published today - adds 35 points, exactly the Watch line,
  and falls below it the next day. Moving a band takes the ledger too. Severe news fades on the 365-day half-life: Vandermeer's
  severity-5 wage story is 710 days old and leaves it Healthy.
- **"Is the model inventing numbers in the case file?"** It cannot. It receives a facts
  dict, and every numeric token it writes back is checked against those facts before
  the page renders. One unmatched figure and the whole text is discarded for a template.
- **"Did you tune this on the answers?"** No. The labels are readable only by the
  harness — `loader.py` raises if engine code opens them, and a test asserts no engine
  file even names them.
