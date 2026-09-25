"""D6 - limit recommendations from expected loss. Deterministic, no LLM, no bands."""
from __future__ import annotations

from collections import defaultdict

from .config import PD_TARGET
from .loader import Loader


def _insured(limit: float, client: dict) -> float:
    """Exposure the insurer actually carries on this line."""
    indemnity = int(client["indemnity_pct"]) / 100
    deductible = int(client["deductible_pct"]) / 100
    return min(float(client["max_liability_inr"]), limit * indemnity * (1 - deductible))


def recommend(loader: Loader, verdicts: dict[str, dict]) -> list[dict]:
    clients = loader.clients_by_id()
    owed_by_line: dict[tuple[str, str], float] = defaultdict(float)
    for inv in loader.invoices():
        if inv["status"] == "Open":
            owed_by_line[(inv["buyer_id"], inv["client_id"])] += float(inv["invoice_amount_inr"] or 0)

    out = []
    for line in loader.credit_limits():
        bid, cid = line["buyer_id"], line["client_id"]
        verdict = verdicts.get(bid)
        if verdict is None:
            continue
        client = clients[cid]
        limit = float(line["credit_limit_inr"])
        owed = owed_by_line.get((bid, cid), 0.0)
        pd = verdict["pd"]

        insured_now = _insured(limit, client)
        capped = insured_now >= float(client["max_liability_inr"]) - 1e-6

        if pd <= PD_TARGET:
            action, revised, why = "MAINTAIN", limit, "probability of default is within appetite"
        elif capped:
            # the cap already binds, so cutting the limit does not reduce insured exposure
            action, revised, why = ("FREEZE", limit,
                                    "max liability already binds - the limit cannot reduce exposure")
        else:
            formula = limit * PD_TARGET / pd
            revised = min(limit, max(owed, formula))
            if owed >= limit:
                action, why = "FREEZE", "already owed at or above the limit - nothing left to cut"
            else:
                action, why = "REDUCE", f"cut to the limit where expected loss meets {PD_TARGET:.0%} appetite"

        out.append({
            "limit_id": line["limit_id"], "buyer_id": bid, "client_id": cid,
            "client_name": client["client_name"],
            "current_limit": round(limit), "owed": round(owed),
            "revised_limit": round(revised), "change": round(revised - limit),
            "action": action, "reason": why,
            "pd": round(pd, 4), "pd_target": round(PD_TARGET, 4),
            "max_liability_binds": capped,
            "expected_loss_before": round(pd * insured_now),
            "expected_loss_after": round(pd * _insured(revised, client)),
        })
    return out
