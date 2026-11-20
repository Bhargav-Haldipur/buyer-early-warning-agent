"""The dataset in the shape a trade-credit insurance platform stores it.

    python3 -m ews.data_model data            # convert a legacy book in place
    python3 -m ews.data_model data/sbi --as-of 2026-11-19

Column names are the platform's parameter codes, so the mapping is visible in the
header row. Columns the platform does not have are prefixed `ews_` and are this
prototype's own.

  legal_entities.csv           legal entities           buyers, insurers, groups
  policies.csv                 policies                 one insurer, one product, terms
  limits.csv                   limit -> request -> decision
  notifiable_events.csv        notifiable events        overdue notifications
  notifiable_event_ageing.csv  NEV_OUTSTANDING_BY_AGEING

There is no invoice ledger. What an insurer learns about a buyer's payments is what
its policyholders notify: an overdue invoice, its original due date, the amount at
risk and, optionally, the outstanding split by ageing. A notification has no closed
state yet (Draft -> Submitted only); `ews_status` and `ews_resolved_date` stand in
for the planned lifecycle status ("Open, Updated, Resolved/Closed, Converted to
claim").

This module also converts the legacy layout (clients / buyers / parent_companies /
credit_limits / invoices) the prototype started from. The conversion is exact for
scoring: every open overdue keeps its days past due, and the latest open
notification on a line carries the line's whole outstanding by ageing. Lateness comes
from the ledger's days_past_due column, which the engine has always treated as the
truth: the sample data leaves it blank on 62 of its 93 open invoices, many of them
past their due date, and a blank has always meant "not overdue".
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

LEGAL_ENTITY_FIELDS = (
    "legal_entity_id", "role", "CORE_LGE_LEGAL_NAME", "CORE_LGE_USUAL_NAME",
    "CORE_LGE_COUNTRY", "CORE_LGE_LEGAL_ADDRESS_TOWN", "national_ids", "LGE_DUNS_ID",
    "LGE_ACTIVITY_TYPE", "LGE_ACTIVITY_CODE", "LGE_TRADE_SECTOR", "LGE_LEGAL_FORM_DESC",
    "legal_entity_parent_id", "legal_entity_ultimate_parent_id",
    "ews_size_band", "ews_is_real", "ews_is_listed",
)
POLICY_FIELDS = (
    "policy_id", "reference", "product_type", "CORE_INSURER", "CORE_MAIN_INSURED",
    "CORE_CURRENCY", "INSURED_PERCENTAGE", "SYS_MAX_LIABILITY", "SYS_CLM_WAIT_PERIOD",
    "OVERDUE_REPORTING_LIMIT", "coverage_start", "coverage_end",
    "ews_deductible_pct", "ews_overdue_reporting_window_days",
)
LIMIT_FIELDS = (
    "limit_id", "policy_id", "CORE_LIMIT_REQUEST_DEBTOR", "CORE_LIMIT_REQUEST_AMOUNT",
    "CORE_LIMIT_DECISION_AMOUNT", "CORE_LIMIT_DECISION_CURRENCY",
    "LIMIT_DECISION_EFFECTIVE_DATE", "LIMIT_DECISION_EXPIRY_DATE",
    "LIMIT_DECISION_INSURED_PERCENTAGE", "LIMIT_DECISION_PAYMENT_TERMS", "decision_status",
    "LIMIT_DECISION_REASON_CODE", "underwriter_type", "decision_date",
)
EVENT_FIELDS = (
    "event_id", "reference", "policy_id", "CORE_LIMIT_REQUEST_DEBTOR", "status",
    "notification_date", "NEV_REASON", "NEV_ORIGINAL_DUE_DATE", "NEV_AMOUNT_AT_RISK",
    "NEV_CURRENCY", "ews_status", "ews_resolved_date",
)
AGEING_FIELDS = ("event_id", "NEV_OUTSTANDING_AGEING", "NEV_OUTSTANDING_AMOUNT")

ROLES = ("BUYER", "INSURER", "INSURED", "GROUP")
# NEV_REASON_REF in the standard configuration
REASONS = ("OVERDUE_INVOICE", "DISHONOURED_PAYMENT", "INSOLVENCY_EVENT", "CASH_FLOW_ISSUES",
           "PAYMENT_DISPUTE", "LEGAL_OR_COLLECTION_ACTION", "CEASED_TRADING", "MARKET_RUMOUR",
           "OTHER_ADVERSE_INFORMATION")
AGEING_BUCKETS = ("NOT_YET_DUE", "OVERDUE_1_30_DAYS", "OVERDUE_31_60_DAYS",
                  "OVERDUE_61_90_DAYS", "OVERDUE_OVER_90_DAYS")
EVENT_STATUSES = ("OPEN", "RESOLVED", "CONVERTED_TO_CLAIM")

# ISO 3166 alpha-3, as CORE_LGE_COUNTRY stores it
_COUNTRY = {
    "Aarhus": "DNK", "Copenhagen": "DNK", "Antwerp": "BEL", "Brussels": "BEL", "Namur": "BEL",
    "Bielefeld": "DEU", "Duisburg": "DEU", "Essen": "DEU", "Frankfurt": "DEU", "Kassel": "DEU",
    "Biella": "ITA", "Milan": "ITA", "Parma": "ITA",
    "Birmingham": "GBR", "Bristol": "GBR", "Coventry": "GBR", "Leeds": "GBR", "London": "GBR",
    "Boras": "SWE", "Gothenburg": "SWE", "Linkoping": "SWE", "Malmo": "SWE", "Stockholm": "SWE",
    "Dordrecht": "NLD", "Eindhoven": "NLD", "Geleen": "NLD", "Terneuzen": "NLD", "Zwolle": "NLD",
    "Limoges": "FRA", "Lyon": "FRA", "Roubaix": "FRA", "Tampere": "FIN", "Mumbai": "IND",
}
_US_STATE = ", "


def country_of(city: str) -> str:
    if city in _COUNTRY:
        return _COUNTRY[city]
    # "Santa Clara, CA": a US city with its state code
    if _US_STATE in city and len(city.rsplit(_US_STATE, 1)[1]) == 2:
        return "USA"
    return ""


def bucket(days_past_due: int) -> str:
    if days_past_due <= 0:
        return "NOT_YET_DUE"
    if days_past_due <= 30:
        return "OVERDUE_1_30_DAYS"
    if days_past_due <= 60:
        return "OVERDUE_31_60_DAYS"
    if days_past_due <= 90:
        return "OVERDUE_61_90_DAYS"
    return "OVERDUE_OVER_90_DAYS"


def _num(x) -> str:
    """Write 440000.0 as 440000 - the files are read by people as well."""
    f = float(x)
    return str(int(f)) if f == int(f) else str(f)


def from_legacy(clients: list[dict], buyers: list[dict], parents: list[dict],
                limits: list[dict], invoices: list[dict], *, as_of: date,
                currency: str, real: bool) -> dict[str, list[dict]]:
    """The legacy book, reshaped. Raises if an open overdue would change its DPD."""
    policy_of = {c["client_id"]: c["policy_id"] for c in clients}

    entities = []
    for c in clients:
        entities.append({
            "legal_entity_id": c["client_id"], "role": "INSURER",
            "CORE_LGE_LEGAL_NAME": c["client_name"], "CORE_LGE_USUAL_NAME": c["client_name"],
            "CORE_LGE_COUNTRY": country_of(c["city"]), "CORE_LGE_LEGAL_ADDRESS_TOWN": c["city"],
            "LGE_TRADE_SECTOR": c.get("sector", ""), "ews_is_real": "N"})
    for p in parents:
        entities.append({
            "legal_entity_id": p["parent_id"], "role": "GROUP",
            "CORE_LGE_LEGAL_NAME": p["name"], "CORE_LGE_USUAL_NAME": p["name"],
            "CORE_LGE_COUNTRY": country_of(p["hq"]), "CORE_LGE_LEGAL_ADDRESS_TOWN": p["hq"],
            "ews_is_real": "N", "ews_is_listed": p.get("listed", "")})
    for b in buyers:
        entities.append({
            "legal_entity_id": b["buyer_id"], "role": "BUYER",
            "CORE_LGE_LEGAL_NAME": b["buyer_name"], "CORE_LGE_USUAL_NAME": b["short_name"],
            "CORE_LGE_COUNTRY": country_of(b["city"]), "CORE_LGE_LEGAL_ADDRESS_TOWN": b["city"],
            "LGE_TRADE_SECTOR": b["sector"],
            "legal_entity_parent_id": b.get("parent_id", ""),
            "legal_entity_ultimate_parent_id": b.get("parent_id", ""),
            "ews_size_band": b.get("size_band", ""), "ews_is_real": "Y" if real else "N"})

    policies = [{
        "policy_id": c["policy_id"], "reference": c["policy_id"], "product_type": "WHOLE_TURNOVER",
        "CORE_INSURER": c["client_id"], "CORE_CURRENCY": currency,
        "INSURED_PERCENTAGE": c["indemnity_pct"], "SYS_MAX_LIABILITY": c["max_liability_eur"],
        "ews_deductible_pct": c["deductible_pct"],
        "ews_overdue_reporting_window_days": c.get("overdue_reporting_window_days", ""),
    } for c in clients]

    out_limits = [{
        "limit_id": l["limit_id"], "policy_id": policy_of[l["client_id"]],
        "CORE_LIMIT_REQUEST_DEBTOR": l["buyer_id"],
        "CORE_LIMIT_REQUEST_AMOUNT": l["credit_limit_eur"],
        "CORE_LIMIT_DECISION_AMOUNT": l["credit_limit_eur"],
        "CORE_LIMIT_DECISION_CURRENCY": currency,
        "LIMIT_DECISION_EFFECTIVE_DATE": l["limit_approved_date"],
        "LIMIT_DECISION_PAYMENT_TERMS": l["payment_terms_days"],
        "decision_status": "ACCEPTED" if l["limit_status"] == "Active" else l["limit_status"].upper(),
        "decision_date": l["last_reviewed_date"],
    } for l in limits]

    events, ageing = [], []
    open_by_line: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for inv in invoices:
        due = date.fromisoformat(inv["due_date"])
        if inv["status"] == "Open":
            open_by_line[(inv["buyer_id"], inv["client_id"])].append(inv)
            stored = int(inv["days_past_due"] or 0)
            if stored <= 0:
                continue                          # not overdue: nothing to notify
            if (as_of - due).days != stored:
                raise ValueError(f"invoice {inv['invoice_id']}: stored {stored} days past due, "
                                 f"but {as_of} - {due} is {(as_of - due).days}")
            status, resolved = "OPEN", ""
        else:
            paid = date.fromisoformat(inv["payment_date"]) if inv["payment_date"] else None
            if paid is None or paid <= due:
                continue                          # paid on time: never notified
            status, resolved = "RESOLVED", paid.isoformat()
        events.append({
            "event_id": f"NE-{inv['invoice_id']}", "reference": f"NE-{inv['invoice_id']}",
            "policy_id": policy_of[inv["client_id"]], "CORE_LIMIT_REQUEST_DEBTOR": inv["buyer_id"],
            "status": "SUBMITTED", "notification_date": (due + timedelta(days=1)).isoformat(),
            "NEV_REASON": "OVERDUE_INVOICE", "NEV_ORIGINAL_DUE_DATE": inv["due_date"],
            "NEV_AMOUNT_AT_RISK": inv["invoice_amount_eur"], "NEV_CURRENCY": currency,
            "ews_status": status, "ews_resolved_date": resolved,
            "_line": (inv["buyer_id"], inv["client_id"]),
        })

    # the latest open notification on each line reports the line's whole outstanding
    latest: dict[tuple[str, str], dict] = {}
    for ev in events:
        if ev["ews_status"] == "OPEN":
            cur = latest.get(ev["_line"])
            if cur is None or (ev["notification_date"], ev["event_id"]) > (
                    cur["notification_date"], cur["event_id"]):
                latest[ev["_line"]] = ev
    for line, ev in sorted(latest.items(), key=lambda kv: kv[1]["event_id"]):
        totals: dict[str, float] = defaultdict(float)
        for inv in open_by_line[line]:
            # the legacy ledger's own days_past_due, not the due date: the sample data
            # leaves it blank on many open invoices whose due date has passed, and the
            # engine has always read a blank as "not overdue". Ageing from the dates
            # would show money 90+ days late on a buyer whose score says 45.
            totals[bucket(int(inv["days_past_due"] or 0))] += float(inv["invoice_amount_eur"] or 0)
        for b in AGEING_BUCKETS:
            if totals.get(b):
                ageing.append({"event_id": ev["event_id"], "NEV_OUTSTANDING_AGEING": b,
                               "NEV_OUTSTANDING_AMOUNT": _num(totals[b])})
    for ev in events:
        del ev["_line"]

    return {"legal_entities": entities, "policies": policies, "limits": out_limits,
            "notifiable_events": events, "notifiable_event_ageing": ageing}


FIELDS = {"legal_entities": LEGAL_ENTITY_FIELDS, "policies": POLICY_FIELDS,
          "limits": LIMIT_FIELDS, "notifiable_events": EVENT_FIELDS,
          "notifiable_event_ageing": AGEING_FIELDS}
LEGACY = ("clients", "buyers", "parent_companies", "credit_limits", "invoices")


def write(directory: Path, tables: dict[str, list[dict]]) -> None:
    for name, rows in tables.items():
        with (directory / f"{name}.csv").open("w", newline="", encoding="utf-8") as fh:
            wr = csv.DictWriter(fh, fieldnames=FIELDS[name], restval="", lineterminator="\n")
            wr.writeheader()
            wr.writerows(rows)


def convert_dir(directory: Path, *, as_of: date, currency: str, real: bool) -> dict:
    def read(name):
        with (directory / f"{name}.csv").open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    tables = from_legacy(*(read(n) for n in LEGACY), as_of=as_of, currency=currency, real=real)
    write(directory, tables)
    for n in LEGACY:
        (directory / f"{n}.csv").unlink()
    return {n: len(rows) for n, rows in tables.items()}


def main() -> None:
    ap = argparse.ArgumentParser(description="Convert a legacy book to the platform layout, in place")
    ap.add_argument("directory")
    ap.add_argument("--as-of", required=True, help="the book's snapshot date")
    ap.add_argument("--currency", default="EUR")
    ap.add_argument("--real", action="store_true", help="the buyers are real companies")
    a = ap.parse_args()
    print(convert_dir(Path(a.directory), as_of=date.fromisoformat(a.as_of),
                      currency=a.currency, real=a.real))


if __name__ == "__main__":
    main()
