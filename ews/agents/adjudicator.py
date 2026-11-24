"""Agent 3 - Risk Adjudicator.

`adjudicate` is the only component in the system that emits a number: the D5
formula and the D8 bands, in code, so every score is reproducible and traced.

`review` is the autonomous half, defined in agents/adjudicator.md. The agent investigates the evidence behind the
score - payment findings, the payment agent's review, every matched article - and
submits whether it agrees with the verdict, agrees with caveats, or challenges it,
citing the evidence it is worried about. It cannot change the score; a challenge is
surfaced to the risk underwriter next to it. Any figure it writes must exist in the data.
"""
from __future__ import annotations

from ..casefile import verify
from ..evidence import evidence_view
from ..config import (SCORE_CAP, W_NEWS, W_PAYMENT, band, news_weight, payment_score, pd_for,
                      risk_score)
from . import definition
from .runtime import Tool, attempt

ASSESSMENTS = ["agree", "agree_with_caveats", "challenge"]


def adjudicate(buyer_id: str, payment: dict, news: dict) -> dict:
    dpd = payment["dpd"]
    p = payment_score(dpd)
    n = news["value"]
    wn = news_weight(news["severity"], news["via_parent"])
    score = risk_score(p, n, wn)
    uncapped = W_PAYMENT * p + wn * n
    severe = f", sev {news['severity']} full weight" if wn != W_NEWS and n else ""
    trace = (f"{W_PAYMENT} x {p:.1f} (payment, {dpd} DPD) + "
             f"{wn:g} x {n:.1f} (news{severe}) = {uncapped:.1f}")
    if uncapped > SCORE_CAP:
        trace += f", capped at {SCORE_CAP:g}"
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
            "weighted": round(wn * n, 1),
        },
        "trace": trace,
    }


def _rules_review(verdict: dict, items: list[dict]) -> dict:
    concerns = []
    for e in items:
        if e["kind"] == "payment_review" and e["data"].get("trend") == "deteriorating":
            concerns.append({"source_id": e["source"],
                             "issue": "settlements are getting later over time"})
    return {"assessment": "agree_with_caveats" if concerns else "agree",
            "rationale": f"Rule-based verdict from the formula: {verdict['trace']}.",
            "concerns": concerns}


def _has_text(a: dict) -> bool:
    """False for a story that is its headline only, as Google News gives it."""
    body = (a.get("body") or "").strip()
    return bool(body) and body != (a.get("headline") or "").strip()


def review(buyer: dict, verdict: dict, items: list[dict], articles: dict[str, dict],
           llm) -> dict | None:
    """Run the review agent for one buyer. None when there is nothing to review."""
    if not items:
        return None
    sources = {e["source"] for e in items}
    view = evidence_view(items)
    spec = definition.load("adjudicator")
    guard = spec.guardrails

    looked_up: set[str] = set()      # other articles read in this run: their figures count

    def get_article(article_id: str) -> dict:
        a = articles.get(article_id)
        if a is None or (article_id not in sources and article_id not in looked_up):
            raise ValueError(f"{article_id!r} is not evidence for this buyer; "
                             f"find_articles lists the others you may read")
        return {k: a[k] for k in ("article_id", "published_date", "publication",
                                  "headline", "body")}

    def find_articles(query: str) -> list[dict]:
        """Every trusted story in the book mentioning the query - to corroborate a
        severity that rests on one story, often a headline with no article text."""
        q = query.lower().strip()
        if not q:
            raise ValueError("give a word or name to search for")
        hits = [a for a in articles.values()
                if q in f"{a['headline']} {a['body']} {a['mentioned_entity_as_written']}".lower()]
        hits.sort(key=lambda a: a["published_date"], reverse=True)
        looked_up.update(a["article_id"] for a in hits[:10])
        return [{"article_id": a["article_id"], "date": a["published_date"],
                 "publication": a["publication"], "headline": a["headline"],
                 "evidence_for_this_buyer": a["article_id"] in sources,
                 "has_article_text": _has_text(a)}
                for a in hits[:10]] or [{"note": f"no article mentions {query!r}"}]

    def submit(assessment: str, rationale: str, concerns: list[dict]) -> dict:
        if assessment not in ASSESSMENTS:
            raise ValueError(f"assessment must be one of {ASSESSMENTS}")
        if len(concerns) > guard["max_concerns"]:
            raise ValueError(f"at most {guard['max_concerns']} concerns; keep the ones that "
                             f"matter most")
        unknown = [c["source_id"] for c in concerns if c["source_id"] not in sources]
        if guard["require_real_citations"] and unknown:
            raise ValueError(f"not evidence for this buyer: {unknown}; cite ids from get_evidence")
        if guard["verify_figures"]:
            facts = {"verdict": verdict, "evidence": view,
                     "articles": [articles[s] for s in sources | looked_up if s in articles]}
            bad = verify(" ".join([rationale] + [c["issue"] for c in concerns]), facts)
            if bad:
                raise ValueError(f"these figures are not in the data: {bad}")
        return {"assessment": assessment, "rationale": rationale.strip(), "concerns": concerns}

    run = attempt(
        llm, lambda: _rules_review(verdict, items),
        spec=spec,
        task=(f"Review the verdict for {buyer['buyer_name']} ({buyer['buyer_id']}), "
              f"{buyer['sector']}, {buyer['city']}: score {verdict['score']}, "
              f"{verdict['band']}."),
        tools=[
            Tool("get_score_breakdown", {}, lambda: verdict),
            Tool("get_evidence",
                 {"kind": {"type": "string",
                           "enum": ["all", "payment", "payment_review", "news", "parent"]}},
                 lambda kind: evidence_view(items, kind) or [{"note": f"no {kind} evidence"}]),
            Tool("get_article", {"article_id": {"type": "string"}}, get_article),
            Tool("find_articles", {"query": {"type": "string"}}, find_articles),
            Tool("submit_review", {
                "assessment": {"type": "string", "enum": ASSESSMENTS},
                "rationale": {"type": "string", "description": "two to four sentences"},
                "concerns": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"source_id": {"type": "string"}, "issue": {"type": "string"}},
                    "required": ["source_id", "issue"], "additionalProperties": False}}},
                submit),
        ],
        cache_payload={"verdict": verdict, "evidence": view},
    )
    return {**run["result"], "agent": {k: run[k] for k in
                                       ("mode", "turns", "cached", "trace", "error")}}
