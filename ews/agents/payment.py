"""Agent 1 - Payment Behaviour. Deterministic (D2).

The worst Open invoice decides the buyer's payment input. Per-insurer findings are
kept as first-class evidence so a buyer-level number can never hide a single bad line.
"""
from __future__ import annotations

from collections import defaultdict

from ..evidence import Evidence
from ..loader import Loader


def assess(loader: Loader, store) -> dict[str, dict]:
    lines: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"dpd": 0, "owed": 0.0, "open_count": 0, "worst_invoice": None, "worst_due": ""}
    )

    for inv in loader.invoices():
        if inv["status"] != "Open":
            continue
        key = (inv["buyer_id"], inv["client_id"])
        dpd = int(inv["days_past_due"] or 0)
        rec = lines[key]
        rec["owed"] += float(inv["invoice_amount_inr"] or 0)
        rec["open_count"] += 1
        if dpd >= rec["dpd"]:
            rec.update(dpd=dpd, worst_invoice=inv["invoice_id"], worst_due=inv["due_date"])

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
    return out
