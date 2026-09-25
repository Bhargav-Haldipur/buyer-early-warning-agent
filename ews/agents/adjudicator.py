"""Agent 3 - Risk Adjudicator. The only component in the system that emits a number."""
from __future__ import annotations

from ..config import W_NEWS, W_PAYMENT, band, payment_score, pd_for


def adjudicate(buyer_id: str, payment: dict, news: dict) -> dict:
    dpd = payment["dpd"]
    p = payment_score(dpd)
    n = news["value"]
    score = W_PAYMENT * p + W_NEWS * n
    return {
        "buyer_id": buyer_id,
        "score": round(score, 1),
        "band": band(score),
        "pd": round(pd_for(score), 4),
        "payment": {
            "dpd": dpd,
            "raw": round(p, 1),
            "weighted": round(W_PAYMENT * p, 1),
            "worst_line": payment["worst_line"],
        },
        "news": {
            "severity": news["severity"],
            "category": news["category"],
            "article_id": news["article_id"],
            "age_days": news["age_days"],
            "headline": news["headline"],
            "via_parent": news["via_parent"],
            "parent_name": news["parent_name"],
            "raw": round(n, 1),
            "weighted": round(W_NEWS * n, 1),
        },
        "trace": (f"{W_PAYMENT} x {p:.1f} (payment, {dpd} DPD) + "
                  f"{W_NEWS} x {n:.1f} (news) = {score:.1f}"),
    }
