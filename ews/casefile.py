"""Case File writer + the D10 guard.

The Case File is the default tab, so the LLM is never trusted with arithmetic. It
receives a facts dict and may use only those numbers; every numeric token it writes
back is checked against them, and a single unmatched figure discards the whole text
in favour of a template built from the same facts.
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
        if abs(v) >= 1000:                       # ₹42,800,000 may be written "42.8" (millions)
            out.add(round(v / 1e6, 1))
            out.add(round(v / 1e6, 2))
            out.add(round(v / 1e5, 1))           # or in lakh
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


def write(llm, buyer: dict, verdict: dict, lines: list[dict]) -> dict:
    facts = build_facts(buyer, verdict, lines)
    text = llm.write_case_file(facts)
    if text is None:
        return {"text": template(facts), "source": "template", "rejected_numbers": []}
    bad = verify(text, facts)
    if bad:
        return {"text": template(facts), "source": "template",
                "rejected_numbers": bad,
                "note": "LLM output discarded - it contained figures not present in the facts"}
    return {"text": text, "source": "llm", "rejected_numbers": []}
