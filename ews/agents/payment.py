"""Agent 1 - Payment Behaviour (D2). Autonomous review over a deterministic ledger.
Defined in agents/payment.md; this module holds the ledger, its tools and the checks.

The ledger pass is code: the worst Open invoice decides the buyer's payment input,
and per-insurer findings are kept as first-class evidence so a buyer-level number
can never hide a single bad line.

The agent then investigates the buyer's open invoices, settled history and credit
lines, and reports the trend and anything an underwriter should know. It must state
the same worst invoice the ledger found - a submission that disagrees is rejected
and the agent is told to look again - so the score input is never the model's.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import mean

from ..evidence import Evidence
from ..loader import Loader, parse_date
from . import definition
from .runtime import Tool, attempt

TRENDS = ["deteriorating", "stable", "improving", "insufficient_history"]


def _days_late(inv: dict) -> int:
    """A Paid invoice with no payment_date is a broken row, not a zero-day settlement."""
    return (parse_date(inv["payment_date"], what=f"invoice {inv['invoice_id']} payment_date")
            - parse_date(inv["due_date"], what=f"invoice {inv['invoice_id']} due_date")).days


def rules_trend(history: list[dict]) -> str:
    """Mean lateness of the last three settlements against the three before."""
    lates = [h["days_late"] for h in history]
    if len(lates) < 4:
        return "insufficient_history"
    recent, before = mean(lates[-3:]), mean(lates[:-3][-3:])
    if recent - before > 5:
        return "deteriorating"
    if before - recent > 5:
        return "improving"
    return "stable"


class Ledger:
    """One buyer's invoices and credit lines, as the agent's tools see them."""

    def __init__(self, bid: str, invoices: list[dict], limits: list[dict],
                 guardrails: dict | None = None):
        self.guard = guardrails or {"must_match_ledger": True, "max_concerns": 5}
        mine = [i for i in invoices if i["buyer_id"] == bid]
        self.open = sorted(
            ({"invoice_id": i["invoice_id"], "client_id": i["client_id"],
              "invoice_date": i["invoice_date"], "due_date": i["due_date"],
              "amount_eur": float(i["invoice_amount_eur"] or 0),
              "days_past_due": int(i["days_past_due"] or 0)}
             for i in mine if i["status"] == "Open"),
            key=lambda i: -i["days_past_due"])
        self.history = sorted(
            ({"invoice_id": i["invoice_id"], "client_id": i["client_id"],
              "due_date": i["due_date"], "payment_date": i["payment_date"],
              "amount_eur": float(i["invoice_amount_eur"] or 0), "days_late": _days_late(i)}
             for i in mine if i["status"] != "Open" and i["payment_date"]),
            key=lambda i: i["due_date"])
        self.lines = [{"client_id": l["client_id"], "credit_limit_eur": float(l["credit_limit_eur"]),
                       "payment_terms_days": int(l["payment_terms_days"]),
                       "limit_status": l["limit_status"],
                       "last_reviewed_date": l["last_reviewed_date"]}
                      for l in limits if l["buyer_id"] == bid]
        self.worst_dpd = self.open[0]["days_past_due"] if self.open else 0

    def submit(self, worst_dpd: int, worst_invoice_id: str, trend: str, summary: str,
               concerns: list[str]) -> dict:
        if self.guard["must_match_ledger"]:
            if worst_dpd != self.worst_dpd:
                raise ValueError(f"the ledger's worst open invoice is {self.worst_dpd} days "
                                 f"past due, not {worst_dpd}; check get_open_invoices")
            if self.open and worst_invoice_id not in {
                    i["invoice_id"] for i in self.open if i["days_past_due"] == self.worst_dpd}:
                raise ValueError(f"{worst_invoice_id!r} is not an open invoice at "
                                 f"{self.worst_dpd} days past due")
        if len(concerns) > self.guard["max_concerns"]:
            raise ValueError(f"at most {self.guard['max_concerns']} concerns; keep the ones "
                             f"that matter most")
        if trend not in TRENDS:
            raise ValueError(f"trend must be one of {TRENDS}")
        return {"trend": trend, "summary": summary.strip(), "concerns": concerns}

    def rules_review(self) -> dict:
        trend = rules_trend(self.history)
        if self.open:
            w = self.open[0]
            summary = (f"{len(self.open)} open invoice(s); the worst, {w['invoice_id']} with "
                       f"{w['client_id']}, is {w['days_past_due']} days past due.")
        else:
            summary = "No open invoices."
        summary += f" Settlement trend: {trend.replace('_', ' ')}."
        return {"trend": trend, "summary": summary, "concerns": []}


def assess(loader: Loader, store, llm=None) -> dict[str, dict]:
    invoices = loader.invoices()
    limits = loader.credit_limits()
    lines: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"dpd": 0, "owed": 0.0, "open_count": 0, "worst_invoice": None, "worst_due": ""}
    )

    for inv in invoices:
        if inv["status"] != "Open":
            continue
        key = (inv["buyer_id"], inv["client_id"])
        dpd = int(inv["days_past_due"] or 0)
        rec = lines[key]
        rec["owed"] += float(inv["invoice_amount_eur"] or 0)
        rec["open_count"] += 1
        if dpd >= rec["dpd"]:
            rec.update(dpd=dpd, worst_invoice=inv["invoice_id"], worst_due=inv["due_date"])

    spec = definition.load("payment")
    out: dict[str, dict] = {}
    for b in loader.buyers():
        bid = b["buyer_id"]
        mine = {cid: rec for (buyer, cid), rec in lines.items() if buyer == bid}
        for cid, rec in mine.items():
            if rec["worst_invoice"]:
                store.add(Evidence(
                    kind="payment", buyer_id=bid,
                    detail=(f"{rec['open_count']} open invoice(s) with {cid}; worst is "
                            f"{rec['dpd']} days past due"),
                    source=rec["worst_invoice"], date=rec["worst_due"],
                    data={"client_id": cid, "dpd": rec["dpd"], "owed": rec["owed"],
                          "open_count": rec["open_count"]},
                ))
        worst = max((r["dpd"] for r in mine.values()), default=0)
        out[bid] = {
            "dpd": worst,
            "lines": {cid: dict(r) for cid, r in mine.items()},
            "worst_line": next((cid for cid, r in mine.items() if r["dpd"] == worst), None),
        }

        ledger = Ledger(bid, invoices, limits, spec.guardrails)
        if not (ledger.open or ledger.history):
            continue
        run = attempt(
            llm, ledger.rules_review, spec=spec,
            task=f"Review payment behaviour for {b['buyer_name']} ({bid}), "
                 f"{b['sector']}, {b['city']}.",
            tools=[
                Tool("get_open_invoices", {},
                     lambda: ledger.open or [{"note": "no open invoices"}]),
                Tool("get_payment_history", {},
                     lambda: ledger.history or [{"note": "no settled invoices"}]),
                Tool("get_credit_lines", {}, lambda: ledger.lines),
                Tool("submit_payment_review", {
                    "worst_dpd": {"type": "integer"},
                    "worst_invoice_id": {"type": "string", "description": "'' if nothing is open"},
                    "trend": {"type": "string", "enum": TRENDS},
                    "summary": {"type": "string"},
                    "concerns": {"type": "array", "items": {"type": "string"}}},
                    ledger.submit),
            ],
            cache_payload={"open": ledger.open, "history": ledger.history, "lines": ledger.lines},
        )
        review = {**run["result"], "agent": {k: run[k] for k in
                                             ("mode", "turns", "cached", "trace", "error")}}
        out[bid]["review"] = review
        store.add(Evidence(
            kind="payment_review", buyer_id=bid, detail=review["summary"],
            source=ledger.open[0]["invoice_id"] if ledger.open else ledger.history[-1]["invoice_id"],
            date=ledger.open[0]["due_date"] if ledger.open else ledger.history[-1]["due_date"],
            data=review,
        ))
    return out
