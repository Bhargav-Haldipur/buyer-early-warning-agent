# Live demo script

> **HACKATHON PROTOTYPE · SYNTHETIC DATA**

```bash
python3 -m dashboard.server      # http://localhost:8000
```

Five buyers sit at exactly **21.7, Healthy** — each with one open invoice 25 days past
due and no news. Press **Publish article N** to append one article and re-run the
engine. Every score below is reproduced by `python3 -m harness.evaluate`.

| Step | What you publish | What the room sees |
|---|---|---|
| 1 | Marchetti appoints a new plant head | **Nothing moves.** 21.7 → 21.7. News that means nothing costs nothing. |
| 2 | Nordkrans scales back operations | 21.7 → **28.6**, still Healthy. A mild negative is not an alert. |
| 3 | Vendors say Larsson has fallen behind | 21.7 → **37.3**, crosses to **Watch**. |
| 4 | Workers at Oakhurst protest unpaid wages | 21.7 → **47.7**, **Watch**. Severity 5 on the same payment position. |
| 5 | Kessler **Logistics** wage protest | **Refused.** No score moves. Wrong company — a 3PL in Dortmund, not the steel trader in Essen. |
| 6 | Workers at Kessler **Traders** protest unpaid wages | 21.7 → **47.7**, **Watch**. Same story, one token different, accepted. |
| 7 | Northpoint parent in restructuring talks | **One article, two buyers, two outcomes.** Marchetti 21.7 → **37.3 Watch**; Westbridge 13.0 → **28.6 Healthy**. |
| 8 | Payment data updates — Kessler 25 → 40 DPD | 47.7 → **65.0, High Risk.** The limit action flips to a cut. |

## The three beats that matter

**Steps 5 and 6 are the pair.** The same wage-protest story, published on the same
day, on names differing by a single word. One is refused, one is accepted. That is
entity resolution earning its place — and it is the defence that matters most: five of
the 38 articles in play are about companies that merely share a brand token with a
covered buyer, and every one of them has to be refused.

**Step 7 is the fusion argument.** One parent story reaches both subsidiaries at the
same stepped-down severity. Westbridge absorbs it and stays Healthy because it pays on
time. Marchetti crosses into Watch because it is already 25 days behind. The news did not
decide the outcome; the news *plus the books* did.

**Step 8 is why lead time is worth money.** Kessler was already on the watchlist from a
news signal before its payment behaviour moved. By the time the payment data confirms
it, the risk underwriter has had the file open for a week.

## What to say if asked

- **"Could the news alone flag someone?"** No. The maximum news contribution is
  0.35 × 75 = 26.25, and Watch starts at 35. Only payment behaviour can carry a buyer
  over the line. That is what keeps Vandermeer — a severity-5 wage story on a buyer that
  never defaults — in Healthy.
- **"Is the model inventing numbers in the case file?"** It cannot. It receives a facts
  dict, and every numeric token it writes back is checked against those facts before
  the page renders. One unmatched figure and the whole text is discarded for a template.
- **"Did you tune this on the answers?"** No. The labels are readable only by the
  harness — `loader.py` raises if engine code opens them, and a test asserts no engine
  file even names them.
