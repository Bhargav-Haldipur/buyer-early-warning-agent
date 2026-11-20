"""Single place for every constant the plan fixes. Nothing here is fitted to labels."""
import math
import os
from datetime import date

# --- which book is being watched ----------------------------------------------
# synthetic: the sample dataset under data/, graded by the harness.
# sbi:       the live-news book: one trade credit insurer covering Indian and overseas
#            buyers, the large ones real companies with news fetched from trusted
#            external sources (python -m ews.fetch_news), and illustrative overdue
#            notifications under data/sbi/. There are no labels for it.
DATASETS = ("synthetic", "sbi")
DATASET = os.environ.get("EWS_DATASET", "synthetic").strip().lower() or "synthetic"
if DATASET not in DATASETS:
    raise ValueError(f"EWS_DATASET must be one of {DATASETS}, got {DATASET!r}")

# The synthetic dataset is a fixed snapshot. The live-news book reads live news, so it is
# scored as of today - a fixed date would score tomorrow's articles as unseen.
# EWS_AS_OF pins either one, for a reproducible run.
if os.environ.get("EWS_AS_OF"):
    AS_OF = date.fromisoformat(os.environ["EWS_AS_OF"])
elif DATASET == "sbi":
    AS_OF = date.today()
else:
    AS_OF = date(2026, 9, 25)      # dataset snapshot

# Each limit and notification carries its own currency (CORE_CURRENCY on its policy).
# Totals across a book are shown in its reporting currency, converted at one fixed,
# dated rate - never a live feed, so a re-run cannot move a total and the cache holds.
REPORTING_CURRENCY = {"synthetic": "EUR", "sbi": "INR"}[DATASET]
CURRENCY = REPORTING_CURRENCY
FX_TO_REPORTING = {
    "synthetic": {"EUR": 1.0},
    # FBIL USD/INR reference rate, as published on rbi.org.in, 19 November 2026
    "sbi": {"INR": 1.0, "USD": 93.3461},
}[DATASET]
FX_AS_OF = date(2026, 11, 19)
FX_SOURCE = "FBIL USD/INR reference rate (rbi.org.in)"


def to_reporting(amount: float, currency: str) -> float:
    """An amount in the book's reporting currency. Unknown currency fails loudly."""
    try:
        return amount * FX_TO_REPORTING[currency]
    except KeyError:
        raise ValueError(f"no fixed rate from {currency} to {REPORTING_CURRENCY}; "
                         f"add it to FX_TO_REPORTING") from None

# --- D5: Risk Score ---------------------------------------------------------
W_PAYMENT, W_NEWS = 0.65, 0.35
# Severities listed here, about the buyer itself, count at W_NEWS_SEVERE instead of
# W_NEWS. Empty: every severity is weighted at 35%, so news alone adds at most
# 0.35 x 100 = 35 (sev 5, published today) and payment drives the bands. Put {4, 5}
# back to let severe news move a buyer that pays on time on its own.
FULL_WEIGHT_SEVERITIES: frozenset[int] = frozenset()
W_NEWS_SEVERE = 1.0
SCORE_CAP = 100.0
DPD_KNEE = 30                       # matches every insurer's overdue reporting window
# Payment points at the knee. 30 x 0.65 = 19.5, just under the Watch line at 20: a buyer
# still inside the reporting window is Healthy on payment alone and enters Watch on the
# first day past it. At 40 (the earlier value) payment alone reached Watch at 23 DPD and
# five sample buyers that never default, each one invoice 25 days late, were flagged.
KNEE_POINTS = 30.0
PAYMENT_SLOPE = 2.0                 # points per day past the knee
NEWS_HALF_LIFE_DAYS = 365           # measured: <270d drops Emberline (see plan D5)
# Decay alone never reaches zero: a 4-year-old severity-5 story still carries 1.6
# points, enough to tip a buyer sitting just under a band line. A risk underwriter would
# not weigh a story that old at all, so news past this age is not read.
NEWS_MAX_AGE_DAYS = 730
# ...and it fades out over its final stretch rather than dropping off a cliff, so a
# buyer never improves overnight just because an article crossed the horizon.
NEWS_FADE_DAYS = 180
# News points by severity, before weighting and decay.
NEWS_BASE = {0: 0.0, 1: 20.0, 2: 40.0, 3: 60.0, 4: 80.0, 5: 100.0}

# --- D4: a parent story counts one rung down for each subsidiary
PARENT_STEP_DOWN = {5: 4, 4: 3, 3: 2, 2: 1, 1: 0, 0: 0}

# --- D8: bands --------------------------------------------------------------
# Healthy 0-19.9 · Watch 20-49.9 · High Risk 50-100
BAND_WATCH, BAND_HIGH = 20.0, 50.0

# --- D3: PD prior, linearly interpolated. Not fitted. ------------------------
PD_ANCHORS = [(0, 0.01), (20, 0.10), (55, 0.45), (80, 0.85), (100, 0.95)]

# --- D6: risk appetite ------------------------------------------------------
# Deliberately not tied to BAND_WATCH: the bands decide who is watched, appetite
# decides when a limit is cut. PD at score 35 == 25%; at the Watch line (20) it
# would be 10%, and nearly every Watch buyer would get a REDUCE.
PD_TARGET_SCORE = 35.0

# --- D11: models are set per agent, in agents/*.md ---------------------------


def _finite(name: str, x: float) -> float:
    """A NaN here is always an upstream bug. Reporting it as a number hides it."""
    x = float(x)
    if math.isnan(x) or math.isinf(x):
        raise ValueError(f"{name} is {x!r}; refusing to score on a non-finite value")
    return x


def payment_score(dpd: int) -> float:
    """D5. Linear to KNEE_POINTS (30) at the knee, then 2 points a day, capped at 100 (65 DPD).

    An invoice that is not yet due carries a negative days_past_due in some ledgers;
    it means 'not late', not 'better than on time', so it floors at zero.
    """
    dpd = max(0.0, _finite("days past due", dpd))
    if dpd <= DPD_KNEE:
        return (dpd / DPD_KNEE) * KNEE_POINTS
    return KNEE_POINTS + min(100.0 - KNEE_POINTS, (dpd - DPD_KNEE) * PAYMENT_SLOPE)


def news_weight(severity: int, via_parent: bool) -> float:
    """The weight one story's news points carry into the score."""
    if not via_parent and severity in FULL_WEIGHT_SEVERITIES:
        return W_NEWS_SEVERE
    return W_NEWS


def risk_score(payment_points: float, news_points: float, news_w: float = W_NEWS) -> float:
    """D5, capped: full-weight news on top of a bad ledger can pass 100."""
    return min(SCORE_CAP, W_PAYMENT * payment_points + news_w * news_points)


def decay(age_days: int) -> float:
    """D5 news half-life, bounded at both ends.

    Older than the relevance horizon -> nothing. Dated after the run -> nothing:
    an article the run could not have seen must not score it.
    """
    age_days = _finite("article age", age_days)
    if age_days < 0 or age_days >= NEWS_MAX_AGE_DAYS:
        return 0.0
    weight = 0.5 ** (age_days / NEWS_HALF_LIFE_DAYS)
    fade_from = NEWS_MAX_AGE_DAYS - NEWS_FADE_DAYS
    if age_days > fade_from:
        weight *= (NEWS_MAX_AGE_DAYS - age_days) / NEWS_FADE_DAYS
    return weight


def band(score: float) -> str:
    score = _finite("risk score", score)
    if score >= BAND_HIGH:
        return "High Risk"
    if score >= BAND_WATCH:
        return "Watch"
    return "Healthy"


def pd_for(score: float) -> float:
    """Linear interpolation across PD_ANCHORS."""
    score = max(0.0, min(100.0, _finite("risk score", score)))
    for (x0, y0), (x1, y1) in zip(PD_ANCHORS, PD_ANCHORS[1:]):
        if x0 <= score <= x1:
            if x1 == x0:
                return y0
            return y0 + (y1 - y0) * (score - x0) / (x1 - x0)
    return PD_ANCHORS[-1][1]


def _validate() -> None:
    """These constants are the whole scoring model. A wrong one does not crash - it
    quietly changes every score, so each is checked when the module loads."""
    problems = []
    if not 0 < NEWS_HALF_LIFE_DAYS:
        problems.append("NEWS_HALF_LIFE_DAYS must be positive (a zero divides by zero)")
    if not 0 < NEWS_MAX_AGE_DAYS:
        problems.append("NEWS_MAX_AGE_DAYS must be positive (a negative scores all news 0)")
    if not 0 <= NEWS_FADE_DAYS < NEWS_MAX_AGE_DAYS:
        problems.append(f"NEWS_FADE_DAYS must be in [0, {NEWS_MAX_AGE_DAYS}) - a longer "
                        f"fade than horizon discounts even a same-day article")
    if DPD_KNEE <= 0:
        problems.append("DPD_KNEE must be positive")
    if not 0 < KNEE_POINTS < 100 or PAYMENT_SLOPE <= 0:
        problems.append("KNEE_POINTS must be in (0, 100) and PAYMENT_SLOPE positive")
    if W_PAYMENT * KNEE_POINTS >= BAND_WATCH:
        problems.append("payment alone must not reach Watch inside the reporting window: "
                        "W_PAYMENT x KNEE_POINTS must stay below BAND_WATCH")
    if abs(W_PAYMENT + W_NEWS - 1.0) > 1e-9:
        problems.append(f"W_PAYMENT + W_NEWS must be 1.0, got {W_PAYMENT + W_NEWS}")
    if not 0 < W_NEWS_SEVERE <= 1.0 or W_NEWS_SEVERE < W_NEWS:
        problems.append("W_NEWS_SEVERE must be in [W_NEWS, 1.0] - severe news must never "
                        "weigh less than mild news")
    if not FULL_WEIGHT_SEVERITIES <= set(NEWS_BASE):
        problems.append(f"FULL_WEIGHT_SEVERITIES names severities absent from NEWS_BASE: "
                        f"{sorted(FULL_WEIGHT_SEVERITIES - set(NEWS_BASE))}")
    if not 0 < BAND_WATCH < BAND_HIGH <= 100:
        problems.append("bands must satisfy 0 < BAND_WATCH < BAND_HIGH <= 100")
    xs = [x for x, _ in PD_ANCHORS]
    ys = [y for _, y in PD_ANCHORS]
    if xs != sorted(xs) or len(set(xs)) != len(xs):
        problems.append("PD_ANCHORS scores must be strictly increasing")
    if ys != sorted(ys) or not all(0 <= y <= 1 for y in ys):
        problems.append("PD_ANCHORS probabilities must be non-decreasing and within [0, 1]")
    missing = set(PARENT_STEP_DOWN) - set(NEWS_BASE)
    if missing:
        problems.append(f"PARENT_STEP_DOWN reads severities absent from NEWS_BASE: {sorted(missing)}")
    unreachable = set(PARENT_STEP_DOWN.values()) - set(NEWS_BASE)
    if unreachable:
        problems.append(f"PARENT_STEP_DOWN maps onto severities absent from NEWS_BASE: "
                        f"{sorted(unreachable)}")
    if problems:
        raise ValueError("ews/config.py is inconsistent:\n  - " + "\n  - ".join(problems))


_validate()

PD_TARGET = pd_for(PD_TARGET_SCORE)
