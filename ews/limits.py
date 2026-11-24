"""D6 - limit recommendations from expected loss. Deterministic, no LLM, no bands."""
from __future__ import annotations

from .config import PD_TARGET, to_reporting
from .loader import Loader


def _insured(limit: float, policy: dict, insured_pct: str = "") -> float:
    """Exposure the insurer actually carries on this line.

    The limit decision's own insured percentage wins over the policy's, as on the platform
    (LIMIT_DECISION_INSURED_PERCENTAGE over INSURED_PERCENTAGE).
    """
    # fractional percentages are legitimate on a policy (87.5%), so never int()
    indemnity = float(insured_pct or policy["INSURED_PERCENTAGE"]) / 100
    deductible = float(policy["ews_deductible_pct"] or 0) / 100
    return min(float(policy["SYS_MAX_LIABILITY"]), limit * indemnity * (1 - deductible))


def owed_by_line(notifications: list[dict]) -> dict[tuple[str, str], float]:
    """Outstanding exposure: what each buyer owes on each policy, as that policy's
    insured reported it - due and not yet due, the platform's outstanding by ageing.

    Keyed (buyer_id, policy_id): one insurer can cover a buyer under several policies -
    a domestic whole-turnover policy and a bank's TReDS cover - and each is its own line.

    The latest open notification that reports an outstanding by ageing gives the line's
    total; any open notification filed after it adds its exposure, since that
    ageing could not include it. The ageing is optional: a line where no open
    notification has one owes the sum of the exposures. A line with no open
    notification has nothing reported as owed.
    """
    by_line: dict[tuple[str, str], list[dict]] = {}
    for n in notifications:
        if n["status"] == "OPEN":
            by_line.setdefault((n["buyer_id"], n["policy_id"]), []).append(n)
    out = {}
    for key, notes in by_line.items():
        notes.sort(key=lambda n: (n["notification_date"], n["event_id"]))
        aged = [i for i, n in enumerate(notes) if n["ageing"]]
        if aged:
            last = aged[-1]
            out[key] = (sum(a["amount"] for a in notes[last]["ageing"])
                        + sum(n["exposure"] for n in notes[last + 1:]))
        else:
            out[key] = sum(n["exposure"] for n in notes)
    return out


def recommend(loader: Loader, verdicts: dict[str, dict]) -> list[dict]:
    clients = loader.clients_by_id()
    policies = loader.policies_by_id()
    names = {e["legal_entity_id"]: e["CORE_LGE_USUAL_NAME"] or e["CORE_LGE_LEGAL_NAME"]
             for e in loader.table("legal_entities")}
    owed_on = owed_by_line(loader.notifications())

    out = []
    for line in loader.credit_limits():
        bid, cid = line["buyer_id"], line["client_id"]
        verdict = verdicts.get(bid)
        if verdict is None:
            continue
        policy = policies[line["policy_id"]]
        limit = line["credit_limit"]
        owed = owed_on.get((bid, line["policy_id"]), 0.0)
        pd = verdict["pd"]

        insured_now = _insured(limit, policy, line["insured_pct"])
        capped = insured_now >= float(policy["SYS_MAX_LIABILITY"]) - 1e-6

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
                action, why = ("FREEZE", "outstanding exposure already at or above the limit"
                                         " - nothing left to cut")
            else:
                action, why = "REDUCE", f"cut to the limit where expected loss meets {PD_TARGET:.0%} appetite"

        out.append({
            "limit_id": line["limit_id"], "buyer_id": bid, "client_id": cid,
            "client_name": clients[cid]["client_name"], "policy_id": line["policy_id"],
            "insured_name": names.get(policy.get("CORE_MAIN_INSURED", ""), ""),
            "product_type": policy["product_type"], "currency": line["currency"],
            "current_limit": round(limit), "owed": round(owed),
            "revised_limit": round(revised), "change": round(revised - limit),
            "action": action, "reason": why,
            "pd": round(pd, 4), "pd_target": round(PD_TARGET, 4),
            "max_liability_binds": capped,
            "expected_loss_before": round(pd * insured_now),
            "expected_loss_after": round(pd * _insured(revised, policy, line["insured_pct"])),
            # the same, in the book's reporting currency, for totals across currencies
            "expected_loss_before_reporting": round(to_reporting(pd * insured_now, line["currency"])),
        })
    return out
