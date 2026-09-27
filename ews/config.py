"""Single place for every constant the plan fixes. Nothing here is fitted to labels."""
import math
from datetime import date

AS_OF = date(2026, 9, 25)          # dataset snapshot

# --- D5: Risk Score ---------------------------------------------------------
W_PAYMENT, W_NEWS = 0.65, 0.35
DPD_KNEE = 30                       # matches every insurer's overdue reporting window
NEWS_HALF_LIFE_DAYS = 365           # measured: <270d drops Emberline (see plan D5)
# Decay alone never reaches zero: a 4-year-old severity-5 story still carries 1.6
# points, enough to tip a buyer sitting just under a band line. A risk underwriter would
# not weigh a story that old at all, so news past this age is not read.
NEWS_MAX_AGE_DAYS = 730
# ...and it fades out over its final stretch rather than dropping off a cliff, so a
# buyer never improves overnight just because an article crossed the horizon.
NEWS_FADE_DAYS = 180
NEWS_BASE = {0: 0.0, 3: 20.0, 4: 45.0, 5: 75.0}

# --- D4: a parent story is a moderate concern for a subsidiary, not a severe one
PARENT_STEP_DOWN = {5: 4, 4: 3, 3: 0, 0: 0}

# --- D8: bands --------------------------------------------------------------
BAND_WATCH, BAND_HIGH = 35.0, 60.0

# --- D3: PD prior, linearly interpolated. Not fitted. ------------------------
PD_ANCHORS = [(0, 0.01), (20, 0.10), (55, 0.45), (80, 0.85), (100, 0.95)]

# --- D6: risk appetite ------------------------------------------------------
PD_TARGET_SCORE = 35.0              # PD at the Watch line == 25%

# --- D11: models are set per agent, in agents/*.md ---------------------------


def _finite(name: str, x: float) -> float:
    """A NaN here is always an upstream bug. Reporting it as a number hides it."""
    x = float(x)
    if math.isnan(x) or math.isinf(x):
        raise ValueError(f"{name} is {x!r}; refusing to score on a non-finite value")
    return x


def payment_score(dpd: int) -> float:
    """D5. Linear to 40 at the knee, then 2 points per day, capped at 100 (60 DPD).

    An invoice that is not yet due carries a negative days_past_due in some ledgers;
    it means 'not late', not 'better than on time', so it floors at zero.
    """
    dpd = max(0.0, _finite("days past due", dpd))
    if dpd <= DPD_KNEE:
        return (dpd / DPD_KNEE) * 40.0
    return 40.0 + min(60.0, (dpd - DPD_KNEE) * 2.0)


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
    if abs(W_PAYMENT + W_NEWS - 1.0) > 1e-9:
        problems.append(f"W_PAYMENT + W_NEWS must be 1.0, got {W_PAYMENT + W_NEWS}")
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
