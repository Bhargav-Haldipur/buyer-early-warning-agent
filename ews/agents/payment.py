"""Agent 1 - Payment Behaviour (D2). Autonomous review over the overdue notifications.
Defined in agents/payment.md; this module holds the ledger, its tools and the checks.

What an insurer knows about how a buyer pays is what its policyholders notify: there
is no invoice ledger, only notifiable events - an overdue invoice, its
original due date, the exposure and the outstanding by ageing.

The ledger pass is code: the oldest open overdue decides the buyer's payment input,
and per-insurer findings are kept as first-class evidence so a buyer-level number
can never hide a single bad line.

The agent then investigates the open notifications, the resolved ones and the credit
lines, and reports the trend - including notifications piling up across insureds,
the signal the business model names for underwriters ("a 3rd event in 6 months,
or several insureds reporting in the same week"). It must state the same worst
overdue the ledger found - a submission that disagrees is rejected and the agent is
told to look again - so the score input is never the model's.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from statistics import mean

from ..config import AS_OF
from ..evidence import Evidence
from ..limits import owed_by_line
from ..loader import Loader, parse_date
from . import definition
from .runtime import Tool, attempt

TRENDS = ["deteriorating", "stable", "improving", "insufficient_history"]
# The business model's own example: a third notification in six months.
ACCUMULATION_DAYS = 180
ACCUMULATION_COUNT = 3


def _days_late(n: dict) -> int:
    """A resolved notification with no resolution date is a broken row, not day zero."""
    return (parse_date(n["resolved_date"], what=f"notification {n['event_id']} resolved date")
            - parse_date(n["original_due_date"], what=f"notification {n['event_id']} due date")).days


def accumulation(notes: list[dict]) -> dict:
    """How many notifications arrived in the last six months, from how many policies."""
    since, before = AS_OF - timedelta(days=ACCUMULATION_DAYS), AS_OF - timedelta(days=2 * ACCUMULATION_DAYS)
    recent = [n for n in notes if parse_date(n["notification_date"]) > since]
    prior = [n for n in notes if before < parse_date(n["notification_date"]) <= since]
    return {"window_days": ACCUMULATION_DAYS, "last_window": len(recent),
            "window_before": len(prior),
            "policies_reporting_last_window": len({n["policy_id"] for n in recent})}


def rules_trend(history: list[dict], acc: dict | None = None) -> str:
    """Notifications piling up first; otherwise mean lateness, last three vs the three before."""
    if acc and acc["last_window"] >= ACCUMULATION_COUNT and acc["last_window"] > acc["window_before"]:
        return "deteriorating"
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
    """One buyer's overdue notifications and credit lines, as the agent's tools see them."""

    def __init__(self, bid: str, notifications: list[dict], limits: list[dict],
                 guardrails: dict | None = None):
        self.guard = guardrails or {"must_match_ledger": True, "max_concerns": 5}
        mine = [n for n in notifications if n["buyer_id"] == bid]
        self.open = sorted(
            ({"event_id": n["event_id"], "client_id": n["client_id"], "policy_id": n["policy_id"],
              "reason": n["reason"], "notification_date": n["notification_date"],
              "original_due_date": n["original_due_date"],
              "exposure": n["exposure"], "currency": n["currency"],
              "days_past_due": n["dpd"] or 0,
              "outstanding_by_ageing": {a["bucket"]: a["amount"] for a in n["ageing"]}}
             for n in mine if n["status"] == "OPEN"),
            key=lambda n: (-n["days_past_due"], n["event_id"]))
        self.history = sorted(
            ({"event_id": n["event_id"], "client_id": n["client_id"], "reason": n["reason"],
              "original_due_date": n["original_due_date"], "resolved_date": n["resolved_date"],
              "exposure": n["exposure"], "days_late": _days_late(n)}
             for n in mine if n["status"] == "RESOLVED" and n["original_due_date"]),
            key=lambda n: n["original_due_date"])
        self.accumulation = accumulation(mine)
        self.lines = [{"client_id": l["client_id"], "policy_id": l["policy_id"],
                       "credit_limit": l["credit_limit"], "currency": l["currency"],
                       "payment_terms_days": l["payment_terms_days"],
                       "limit_status": l["limit_status"],
                       "last_reviewed_date": l["last_reviewed_date"]}
                      for l in limits if l["buyer_id"] == bid]
        self.worst_dpd = self.open[0]["days_past_due"] if self.open else 0

    def history_view(self) -> dict:
        return {"resolved": self.history or [{"note": "no resolved notifications"}],
                "accumulation": self.accumulation}

    def submit(self, worst_dpd: int, worst_event_id: str, trend: str, summary: str,
               concerns: list[str]) -> dict:
        if self.guard["must_match_ledger"]:
            if worst_dpd != self.worst_dpd:
                raise ValueError(f"the oldest open overdue is {self.worst_dpd} days past due, "
                                 f"not {worst_dpd}; check get_open_notifications")
            if self.worst_dpd and worst_event_id not in {
                    n["event_id"] for n in self.open if n["days_past_due"] == self.worst_dpd}:
                raise ValueError(f"{worst_event_id!r} is not an open notification at "
                                 f"{self.worst_dpd} days past due")
        if len(concerns) > self.guard["max_concerns"]:
            raise ValueError(f"at most {self.guard['max_concerns']} concerns; keep the ones "
                             f"that matter most")
        if trend not in TRENDS:
            raise ValueError(f"trend must be one of {TRENDS}")
        return {"trend": trend, "summary": summary.strip(), "concerns": concerns}

    def rules_review(self) -> dict:
        trend = rules_trend(self.history, self.accumulation)
        if self.open:
            w = self.open[0]
            summary = (f"{len(self.open)} open overdue notification(s); the oldest, "
                       f"{w['event_id']} under policy {w['policy_id']}, is "
                       f"{w['days_past_due']} days past due.")
        else:
            summary = "No open overdue notifications."
        acc = self.accumulation
        summary += (f" {acc['last_window']} notification(s) in the last {acc['window_days']} days"
                    f" from {acc['policies_reporting_last_window']} polic"
                    f"{'y' if acc['policies_reporting_last_window'] == 1 else 'ies'}."
                    f" Trend: {trend.replace('_', ' ')}.")
        return {"trend": trend, "summary": summary, "concerns": []}


def assess(loader: Loader, store, llm=None, llm_for=None) -> dict[str, dict]:
    """llm_for(buyer), when given, picks the model for each buyer; else llm for all."""
    notes = loader.notifications()
    limits = loader.credit_limits()
    owed = owed_by_line(notes)
    lines: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"dpd": 0, "owed": 0.0, "open_count": 0, "worst_event": None, "worst_due": "",
                 "currency": ""}
    )
    for n in notes:
        if n["status"] != "OPEN" or n["dpd"] is None:
            continue
        key = (n["buyer_id"], n["policy_id"])
        rec = lines[key]
        rec["open_count"] += 1
        rec["owed"] = owed.get(key, 0.0)
        rec.update(currency=n["currency"], client_id=n["client_id"])
        if n["dpd"] >= rec["dpd"]:
            rec.update(dpd=n["dpd"], worst_event=n["event_id"], worst_due=n["original_due_date"])

    spec = definition.load("payment")
    out: dict[str, dict] = {}
    for b in loader.buyers():
        bid = b["buyer_id"]
        mine = {pid: rec for (buyer, pid), rec in lines.items() if buyer == bid}
        for pid, rec in mine.items():
            if rec["worst_event"]:
                store.add(Evidence(
                    kind="payment", buyer_id=bid,
                    detail=(f"{rec['open_count']} open overdue notification(s) under policy "
                            f"{pid}; the oldest is {rec['dpd']} days past due"),
                    source=rec["worst_event"], date=rec["worst_due"],
                    data={"client_id": rec["client_id"], "policy_id": pid, "dpd": rec["dpd"],
                          "owed": rec["owed"], "currency": rec["currency"],
                          "open_count": rec["open_count"]},
                ))
        worst = max((r["dpd"] for r in mine.values()), default=0)
        out[bid] = {
            "dpd": worst,
            "lines": {pid: dict(r) for pid, r in mine.items()},
            # the policy whose overdue sets the payment score
            "worst_line": next((pid for pid, r in mine.items() if r["dpd"] == worst), None),
        }

        ledger = Ledger(bid, notes, limits, spec.guardrails)
        if not (ledger.open or ledger.history):
            continue
        run = attempt(
            llm_for(b) if llm_for else llm, ledger.rules_review, spec=spec,
            task=f"Review payment behaviour for {b['buyer_name']} ({bid}), "
                 f"{b['sector']}, {b['city']}.",
            tools=[
                Tool("get_open_notifications", {},
                     lambda: ledger.open or [{"note": "no open overdue notifications"}]),
                Tool("get_notification_history", {}, ledger.history_view),
                Tool("get_credit_lines", {}, lambda: ledger.lines),
                Tool("submit_payment_review", {
                    "worst_dpd": {"type": "integer"},
                    "worst_event_id": {"type": "string", "description": "'' if nothing is overdue"},
                    "trend": {"type": "string", "enum": TRENDS},
                    "summary": {"type": "string"},
                    "concerns": {"type": "array", "items": {"type": "string"}}},
                    ledger.submit),
            ],
            cache_payload={"open": ledger.open, "history": ledger.history,
                           "accumulation": ledger.accumulation, "lines": ledger.lines},
        )
        review = {**run["result"], "agent": {k: run[k] for k in
                                             ("mode", "turns", "cached", "trace", "error")}}
        out[bid]["review"] = review
        first = ledger.open[0] if ledger.open else ledger.history[-1]
        store.add(Evidence(
            kind="payment_review", buyer_id=bid, detail=review["summary"],
            source=first["event_id"], date=first["original_due_date"], data=review,
        ))
    return out
