"""Case File writer + the D10 guard.

The Case File is the default tab and comes in two forms from one set of facts:

  fields     - structured sections for the risk underwriter to scan: header, bottom line,
               limit actions, drivers, adjudicator review, what would lift or worsen
               it, evidence. Every figure in them is copied from the engine by code.
  narrative  - four short paragraphs, the same story in prose.

The agent writes only the judgement text - the bottom line, a note per driver, the
lift/worsen triggers and the narrative - and is never trusted with arithmetic. Every
numeric token it submits is checked against the data its tools returned; a draft with
an unmatched figure is sent back to the agent, and if it cannot produce a clean one the
template built from the same facts renders instead.
"""
from __future__ import annotations

import json
import math
import re

from .config import (AS_OF, BAND_HIGH, BAND_WATCH, DPD_KNEE, KNEE_POINTS, NEWS_HALF_LIFE_DAYS,
                     PAYMENT_SLOPE, W_NEWS, W_PAYMENT)

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
    # Rupee amounts are written in crore and lakh. Only for a book that has them: on a
    # euro book "42.8" for 4,280,000 would let a wrong figure through.
    rupees = '"INR"' in json.dumps(facts, default=str)
    out: set[float] = set()
    for v in base:
        if rupees and abs(v) >= 1e5:
            out.update({round(v / 1e7, 1), round(v / 1e7, 2), round(v / 1e5, 1), round(v / 1e5)})
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


# ---------------------------------------------------------------- facts
def _dpd_for(payment_points: float) -> int | None:
    """Smallest DPD whose payment score reaches `payment_points`; None if none can."""
    if payment_points <= 0:
        return 0
    if payment_points > 100:
        return None
    if payment_points <= KNEE_POINTS:
        return math.ceil(payment_points / KNEE_POINTS * DPD_KNEE)
    return math.ceil(DPD_KNEE + (payment_points - KNEE_POINTS) / PAYMENT_SLOPE)


def outlook(verdict: dict) -> dict:
    """How far the buyer sits from the band lines, holding the news contribution fixed.

    Computed here so the agent can talk about triggers without doing arithmetic.
    """
    score, band = verdict["score"], verdict["band"]
    news_pts = verdict["news"]["weighted"]
    up = {"Healthy": ("Watch", BAND_WATCH), "Watch": ("High Risk", BAND_HIGH)}.get(band)
    down = {"Watch": ("Healthy", BAND_WATCH), "High Risk": ("Watch", BAND_HIGH)}.get(band)
    out = {"next_band": None, "next_band_at": None, "points_to_next_band": None,
           "dpd_for_next_band": None, "lower_band": None, "lower_band_below": None,
           "points_to_lower_band": None, "news_alone_holds_band": False,
           "news_half_life_days": NEWS_HALF_LIFE_DAYS}
    if up:
        name, at = up
        out.update(next_band=name, next_band_at=at, points_to_next_band=round(at - score, 1),
                   dpd_for_next_band=_dpd_for((at - news_pts) / W_PAYMENT))
    if down:
        name, below = down
        out.update(lower_band=name, lower_band_below=below,
                   points_to_lower_band=round(score - below, 1),
                   news_alone_holds_band=news_pts >= below)
    return out


def build_facts(buyer: dict, verdict: dict, lines: list[dict],
                items: list[dict] | None = None) -> dict:
    v = verdict
    items = items or []
    pay_review = next((e["data"] for e in items if e["kind"] == "payment_review"), None)
    if v["band"] == "Healthy":
        lift = "No action required; the buyer is already in the Healthy band."
    else:
        need = v["payment"]["dpd"]
        lift = (f"This clears if the {need}-day overdue balance is settled and no further "
                f"negative news lands; news weight also decays with age.")
    return {"buyer": buyer, "verdict": v, "limits": lines, "what_would_lift_it": lift,
            "outlook": outlook(v), "as_of": AS_OF.isoformat(),
            "payment_trend": pay_review["trend"] if pay_review else None,
            "payment_summary": pay_review["summary"] if pay_review else None}


# ---------------------------------------------------------------- the rules path
def _headline_action(lines: list[dict]) -> str:
    acts = {l["action"] for l in lines}
    return next((a for a in ("FREEZE", "REDUCE", "MAINTAIN") if a in acts), "NO LIMITS")


def template_judgement(facts: dict) -> dict:
    """The agent-written parts, rendered from rules. Same shape as a submission."""
    v, o, lim = facts["verdict"], facts["outlook"], facts["limits"]
    pay, news = v["payment"], v["news"]
    name = facts["buyer"]["buyer_name"]
    action = _headline_action(lim)

    bottom = {"FREEZE": "Freeze cover", "REDUCE": "Reduce cover",
              "MAINTAIN": "Maintain cover", "NO LIMITS": "No limit lines to act on"}[action]
    bottom += f": {name} scores {v['score']} and sits in {v['band']}"
    if pay["dpd"]:
        bottom += f", with its oldest open overdue {pay['dpd']} days past due"
    bottom += "."

    if pay["dpd"]:
        pnote = (f"Oldest open overdue is {pay['dpd']} days past due, contributing "
                 f"{pay['weighted']} points.")
    else:
        pnote = "Nothing is overdue."
    if facts["payment_trend"] and facts["payment_trend"] != "insufficient_history":
        pnote += f" Settlement trend: {facts['payment_trend'].replace('_', ' ')}."

    if news["severity"]:
        via = f" via its parent {news['parent_name']}" if news["via_parent"] else ""
        nnote = (f"Severity {news['severity']} ({news['category']}){via}, "
                 f"{news['age_days']} days old, contributing {news['weighted']} points "
                 f"after decay.")
    else:
        nnote = "No negative news has been matched to this buyer."

    if v["band"] == "Healthy":
        lifts = [facts["what_would_lift_it"]]
    else:
        lifts = [f"The score must fall {o['points_to_lower_band']} points, below "
                 f"{o['lower_band_below']}, to reach {o['lower_band']}."]
        if pay["dpd"]:
            lifts.append(f"Settling the {pay['dpd']}-day overdue balance removes up to "
                         f"{pay['weighted']} points.")
        if o["news_alone_holds_band"]:
            lifts.append("News alone holds the buyer in this band until it decays.")
        elif news["severity"]:
            lifts.append(f"News weight halves every {o['news_half_life_days']} days.")

    if o["next_band"] is None:
        worsens = ["Already in the highest band; further overdue days or new severe news "
                   "raise the probability of default."]
    else:
        worsens = [f"A rise of {o['points_to_next_band']} points moves it to "
                   f"{o['next_band']} (score {o['next_band_at']})."]
        if o["dpd_for_next_band"] is not None:
            worsens.append(f"On payment alone, that happens when the oldest overdue reaches "
                           f"{o['dpd_for_next_band']} days past due.")
        else:
            worsens.append("Payment alone cannot move it there; it would take new "
                           "negative news too.")

    return {"bottom_line": bottom, "payment_note": pnote, "news_note": nnote,
            "lifts_it": lifts, "worsens_it": worsens}


def template(facts: dict) -> str:
    """The four-paragraph narrative, rendered from rules."""
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
        f"Its oldest open overdue is {v['payment']['dpd']} days past due, contributing "
        f"{v['payment']['weighted']} points. {news_line}\n\n"
        f"Score trace: {v['trace']}.\n\n"
        f"Recommended limit action - {acts}.\n\n"
        f"{facts['what_would_lift_it']}"
    )


# ---------------------------------------------------------------- assembly
def _fields(facts: dict, judgement: dict, items: list[dict]) -> dict:
    """The structured case file: code-built sections plus the judgement text."""
    b, v = facts["buyer"], facts["verdict"]
    pay, news = v["payment"], v["news"]
    pay_ev = next((e["source"] for e in items if e["kind"] == "payment"
                   and e["data"].get("policy_id") == pay["worst_line"]), None)
    rv = v.get("review")
    return {
        "header": {
            "buyer_id": b["buyer_id"], "buyer_name": b["buyer_name"],
            "sector": b.get("sector"), "city": b.get("city"),
            "parent_id": b.get("parent_id") or None,
            "score": v["score"], "band": v["band"], "pd": v["pd"],
            "assessment": rv["assessment"] if rv else None,
            "as_of": facts["as_of"],
        },
        "bottom_line": judgement["bottom_line"],
        "limit_actions": [
            {k: l.get(k, "") for k in ("client_name", "insured_name", "policy_id", "currency",
                                      "current_limit", "owed", "revised_limit", "change",
                                      "action", "reason")}
            for l in facts["limits"]],
        "drivers": [
            {"driver": "payment", "weight": W_PAYMENT, "points": pay["weighted"],
             "dpd": pay["dpd"], "trend": facts["payment_trend"], "evidence_id": pay_ev,
             "note": judgement["payment_note"]},
            {"driver": "news", "weight": W_NEWS, "points": news["weighted"],
             "severity": news["severity"], "category": news["category"],
             "age_days": news["age_days"], "via_parent": news["via_parent"],
             "evidence_id": news["article_id"] if news["severity"] else None,
             "note": judgement["news_note"]},
        ],
        "score_trace": v["trace"],
        "review": ({k: rv[k] for k in ("assessment", "rationale", "concerns")}
                   if rv else None),
        "lifts_it": list(judgement["lifts_it"]),
        "worsens_it": list(judgement["worsens_it"]),
        "outlook": facts["outlook"],
        "evidence": [{"id": e["source"], "kind": e["kind"], "date": e["date"],
                      "detail": e["detail"]}
                     for e in items if e["kind"] != "resolution"],
    }


def write(llm, buyer: dict, verdict: dict, lines: list[dict], items: list[dict] | None = None,
          articles: dict[str, dict] | None = None) -> dict:
    """The Case File agent (agents/casefile.md), with the D10 guard as its submit check.

    Returns {"narrative", "fields", "source", "rejected_numbers", "agent"}. Without
    Claude (and for every band outside run_for_bands) the template renders instead.
    """
    from .agents import definition
    from .agents.runtime import Tool, attempt
    from .evidence import evidence_view

    spec = definition.load("casefile")
    guard = spec.guardrails
    items, articles = items or [], articles or {}
    facts = build_facts(buyer, verdict, lines, items)
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

    def submit(narrative: str, bottom_line: str, payment_note: str, news_note: str,
               lifts_it: list[str], worsens_it: list[str]) -> dict:
        cap = guard["max_list_items"]
        for label, xs in (("lifts_it", lifts_it), ("worsens_it", worsens_it)):
            if not 1 <= len(xs) <= cap:
                raise ValueError(f"{label} needs 1 to {cap} items; keep the ones that matter most")
        if not bottom_line.strip() or not narrative.strip():
            raise ValueError("bottom_line and narrative must not be empty")
        if guard["verify_figures"]:
            text = " ".join([narrative, bottom_line, payment_note, news_note,
                             *lifts_it, *worsens_it])
            bad = verify(text, guard_facts, guard["figure_tolerance"])
            if bad:
                raise ValueError(f"these figures are not in the data: {bad}. Use only the "
                                 f"numbers the tools returned, then resubmit")
        return {"narrative": narrative.strip(), "source": "llm", "rejected_numbers": [],
                "judgement": {"bottom_line": bottom_line.strip(),
                              "payment_note": payment_note.strip(),
                              "news_note": news_note.strip(),
                              "lifts_it": [x.strip() for x in lifts_it],
                              "worsens_it": [x.strip() for x in worsens_it]}}

    def rules() -> dict:
        return {"narrative": template(facts), "source": "template", "rejected_numbers": [],
                "judgement": template_judgement(facts)}

    string_list = {"type": "array", "items": {"type": "string"}}
    run = attempt(
        llm, rules,
        spec=spec,
        task=f"Write the case file for {buyer['buyer_name']} ({buyer['buyer_id']}).",
        tools=[
            Tool("get_verdict", {}, lambda: verdict),
            Tool("get_limits", {}, lambda: lines or [{"note": "no limit lines"}]),
            Tool("get_outlook", {}, lambda: facts["outlook"]),
            Tool("get_evidence", {}, lambda: view or [{"note": "no evidence"}]),
            Tool("get_article", {"article_id": {"type": "string"}}, get_article),
            Tool("submit_case_file", {
                "narrative": {"type": "string", "description": "four short paragraphs"},
                "bottom_line": {"type": "string", "description": "one or two sentences"},
                "payment_note": {"type": "string", "description": "one sentence"},
                "news_note": {"type": "string", "description": "one sentence"},
                "lifts_it": string_list,
                "worsens_it": string_list}, submit),
        ],
        cache_payload={"facts": facts, "evidence": view},
    )
    res = run["result"]
    return {"narrative": res["narrative"],
            "fields": _fields(facts, res["judgement"], items),
            "source": res["source"], "rejected_numbers": res["rejected_numbers"],
            "agent": {k: run[k] for k in ("mode", "turns", "cached", "trace", "error")}}
