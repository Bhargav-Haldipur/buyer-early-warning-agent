"""Case File writer + the D10 guard.

The Case File is the default tab, so the agent is never trusted with arithmetic. Every
numeric token it submits is checked against the data its tools returned; a draft with
an unmatched figure is sent back to the agent, and if it cannot produce a clean one the
template built from the same facts renders instead.
"""
from __future__ import annotations

import re

_NUM = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s*(M|m|%)?")


def _collect(obj, acc: set[float]) -> None:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        acc.add(float(obj))
    elif isinstance(obj, str):
        for m in _NUM.finditer(obj):
            try:
                acc.add(float(m.group(1).replace(",", "")))
            except ValueError:
                pass
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect(v, acc)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _collect(v, acc)


def allowed_numbers(facts: dict) -> set[float]:
    """Every number the writer may use, plus the scaled/rounded forms of each."""
    base: set[float] = set()
    _collect(facts, base)
    out: set[float] = set()
    for v in base:
        out.add(v)
        out.add(round(v, 1))
        out.add(round(v))
        if abs(v) >= 1000:                       # 4,280,000 may be written "4.28" (millions)
            out.add(round(v / 1e6, 1))
            out.add(round(v / 1e6, 2))
            out.add(round(v / 1e3))              # or in thousands
        if 0 < abs(v) <= 1:                      # 0.25 may be written "25" (per cent)
            out.add(round(v * 100, 1))
            out.add(round(v * 100))
    return out


def verify(text: str, facts: dict, tolerance: float = 0.051) -> list[str]:
    """Return the numeric tokens in `text` that no fact justifies."""
    ok = allowed_numbers(facts)
    bad = []
    for m in _NUM.finditer(text):
        raw = m.group(1).replace(",", "")
        try:
            val = float(raw)
        except ValueError:
            continue
        if m.group(2) in ("M", "m"):
            candidates = [val, val * 1e6]
        else:
            candidates = [val]
        if not any(any(abs(c - a) <= tolerance for a in ok) for c in candidates):
            bad.append(m.group(0).strip())
    return bad


def template(facts: dict) -> str:
    v, lim = facts["verdict"], facts["limits"]
    news = v["news"]
    if news["severity"]:
        via = f" via its parent {news['parent_name']}" if news["via_parent"] else ""
        news_line = (f"The strongest news signal is severity {news['severity']} "
                     f"({news['category']}){via}, {news['age_days']} days old, contributing "
                     f"{news['weighted']} points after decay.")
    else:
        news_line = "No negative news has been matched to this buyer."
    acts = "; ".join(f"{a['client_name']}: {a['action']}" for a in lim) or "no limit lines"
    return (
        f"{facts['buyer']['buyer_name']} scores {v['score']} and sits in {v['band']}. "
        f"Its worst open invoice is {v['payment']['dpd']} days past due, contributing "
        f"{v['payment']['weighted']} points. {news_line}\n\n"
        f"Score trace: {v['trace']}.\n\n"
        f"Recommended limit action - {acts}.\n\n"
        f"{facts['what_would_lift_it']}"
    )


def build_facts(buyer: dict, verdict: dict, lines: list[dict]) -> dict:
    v = verdict
    if v["band"] == "Healthy":
        lift = "No action required; the buyer is already in the Healthy band."
    else:
        need = v["payment"]["dpd"]
        lift = (f"This clears if the {need}-day overdue balance is settled and no further "
                f"negative news lands; news weight also decays with age.")
    return {"buyer": buyer, "verdict": v, "limits": lines, "what_would_lift_it": lift}


def write(llm, buyer: dict, verdict: dict, lines: list[dict], items: list[dict] | None = None,
          articles: dict[str, dict] | None = None) -> dict:
    """The Case File agent (agents/casefile.md), with the D10 guard as its submit check.

    Without Claude (and for every Healthy buyer) the template renders instead.
    """
    from .agents import definition
    from .agents.runtime import Tool, attempt
    from .evidence import evidence_view

    spec = definition.load("casefile")
    guard = spec.guardrails
    facts = build_facts(buyer, verdict, lines)
    items, articles = items or [], articles or {}
    sources = {e["source"] for e in items}
    view = evidence_view(items)
    guard_facts = {"facts": facts, "evidence": view,
                   "articles": [articles[s] for s in sources if s in articles]}

    def get_article(article_id: str) -> dict:
        if article_id not in sources or article_id not in articles:
            raise ValueError(f"{article_id!r} is not evidence for this buyer")
        a = articles[article_id]
        return {k: a[k] for k in ("article_id", "published_date", "publication",
                                  "headline", "body")}

    def submit(text: str) -> dict:
        bad = (verify(text, guard_facts, guard["figure_tolerance"])
               if guard["verify_figures"] else [])
        if bad:
            raise ValueError(f"these figures are not in the data: {bad}. Use only the "
                             f"numbers the tools returned, then resubmit")
        return {"text": text.strip(), "source": "llm", "rejected_numbers": []}

    run = attempt(
        llm, lambda: {"text": template(facts), "source": "template", "rejected_numbers": []},
        spec=spec,
        task=f"Write the case file for {buyer['buyer_name']} ({buyer['buyer_id']}).",
        tools=[
            Tool("get_verdict", {}, lambda: verdict),
            Tool("get_limits", {}, lambda: lines or [{"note": "no limit lines"}]),
            Tool("get_evidence", {}, lambda: view or [{"note": "no evidence"}]),
            Tool("get_article", {"article_id": {"type": "string"}}, get_article),
            Tool("submit_case_file", {"text": {"type": "string"}}, submit),
        ],
        cache_payload={"facts": facts, "evidence": view},
    )
    return {**run["result"], "agent": {k: run[k] for k in
                                       ("mode", "turns", "cached", "trace", "error")}}
