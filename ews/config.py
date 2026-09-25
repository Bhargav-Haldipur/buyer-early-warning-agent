"""Single place for every constant the plan fixes. Nothing here is fitted to labels."""
from datetime import date

AS_OF = date(2026, 9, 25)          # dataset snapshot

# --- D5: Risk Score ---------------------------------------------------------
W_PAYMENT, W_NEWS = 0.65, 0.35
DPD_KNEE = 30                       # matches every insurer's overdue reporting window
NEWS_HALF_LIFE_DAYS = 365           # measured: <270d drops Emberline (see plan D5)
NEWS_BASE = {0: 0.0, 3: 20.0, 4: 45.0, 5: 75.0}

# --- D4: a parent story is a moderate concern for a subsidiary, not a severe one
PARENT_STEP_DOWN = {5: 4, 4: 3, 3: 0, 0: 0}

# --- D8: bands --------------------------------------------------------------
BAND_WATCH, BAND_HIGH = 35.0, 60.0

# --- D3: PD prior, linearly interpolated. Not fitted. ------------------------
PD_ANCHORS = [(0, 0.01), (20, 0.10), (55, 0.45), (80, 0.85), (100, 0.95)]

# --- D6: risk appetite ------------------------------------------------------
PD_TARGET_SCORE = 35.0              # PD at the Watch line == 25%

# --- D11: models ------------------------------------------------------------
MODEL_GRADING = "claude-sonnet-5"   # entity resolution + severity
MODEL_CASEFILE = "claude-opus-5"    # case file prose


def payment_score(dpd: int) -> float:
    """D5. Linear to 40 at the knee, then 2 points per day, capped at 100 (60 DPD)."""
    if dpd <= DPD_KNEE:
        return (dpd / DPD_KNEE) * 40.0
    return 40.0 + min(60.0, (dpd - DPD_KNEE) * 2.0)


def decay(age_days: int) -> float:
    """D5 news half-life."""
    return 0.5 ** (age_days / NEWS_HALF_LIFE_DAYS)


def band(score: float) -> str:
    if score >= BAND_HIGH:
        return "High Risk"
    if score >= BAND_WATCH:
        return "Watch"
    return "Healthy"


def pd_for(score: float) -> float:
    """Linear interpolation across PD_ANCHORS."""
    score = max(0.0, min(100.0, score))
    for (x0, y0), (x1, y1) in zip(PD_ANCHORS, PD_ANCHORS[1:]):
        if x0 <= score <= x1:
            if x1 == x0:
                return y0
            return y0 + (y1 - y0) * (score - x0) / (x1 - x0)
    return PD_ANCHORS[-1][1]


PD_TARGET = pd_for(PD_TARGET_SCORE)
