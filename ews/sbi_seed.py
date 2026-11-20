"""Build the live-news book: one trade credit insurer, four policies, eighteen buyers.

    python3 -m ews.sbi_seed                  # dated as of today
    python3 -m ews.sbi_seed --as-of 2026-11-19

Written in the shape the insurance platform stores it (see data_model.py). Eighteen buyers on a 3 x 2
grid - large, medium and small; Indian and overseas - three in each cell:

  * The six LARGE buyers are REAL listed companies (Tata Motors, Larsen & Toubro,
    Vodafone Idea; Intel, Boeing, Ford) and their news is fetched from public sources.
    Their credit limits and overdue notifications are ILLUSTRATIVE, and deliberately
    unremarkable: never an overdue past 30 days, so whatever moves a real company's
    score is real news, never an invented payment problem.
  * The twelve MEDIUM and SMALL buyers are INVENTED, and so are their stories
    (illustrative_articles.csv, marked "Illustrative"). The High Risk and FREEZE cases
    in the book are all invented companies. Most small buyers have no news at all -
    that is what a small company's coverage looks like.
  * The four policyholders are invented, and so is the insurer: a generic Indian trade
    credit insurer, with its policies, limits and notifications.

Domestic limits are decided by hand and export limits through the Tinubu Risk team's
recommendations, hence underwriter_type MANUAL / AUTOMATIC. The insurer uses one
notifiable-event reason, overdue payment, so every notification is an overdue invoice.
Indemnity is 80% throughout.

Re-run before a presentation so the dates sit around the day it is shown. It rewrites
everything in data/sbi/ except trusted_sources.csv and the fetched news.
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from . import data_model

DIR = Path(__file__).resolve().parent.parent / "data" / "sbi"
CR, L = 10_000_000, 100_000        # one crore, one lakh

INSURER = ("TCI", "Trade Credit Insurer", "Trade Credit Insurer", "Mumbai", "IND")

# id, legal name, usual name, town
INSUREDS = [
    ("INS01", "Velaris Polymers Private Limited", "Velaris Polymers", "Pune"),
    ("INS02", "Orvana Steel Components Private Limited", "Orvana Steel", "Ahmedabad"),
    ("INS03", "Tamrin Global Exports Limited", "Tamrin Exports", "Chennai"),
    ("INS04", "Meridia Commercial Bank Limited", "Meridia Bank", "Mumbai"),
]

# id, product, insured, currency, max liability, reporting threshold, underwriter
POLICIES = [
    ("TCI-WT-2026-0001", "WHOLE_TURNOVER", "INS01", "INR", 60 * CR, 5 * L, "MANUAL"),
    ("TCI-WT-2026-0002", "WHOLE_TURNOVER", "INS02", "INR", 50 * CR, 5 * L, "MANUAL"),
    ("TCI-EX-2026-0001", "EXPORT", "INS03", "USD", 25_000_000, 10_000, "AUTOMATIC"),
    # the bank buys cover on invoices it discounts on a TReDS platform
    ("TCI-SCF-2026-0001", "SUPPLY_CHAIN_FINANCE", "INS04", "INR", 20 * CR, 5 * L, "MANUAL"),
]
WT1, WT2, EXP, SCF = (p[0] for p in POLICIES)

# Buyers. `limits` is [(policy, amount, payment terms)]; `open` is the overdues still
# unpaid [(policy, days past due, amount)]; `paid` is [(policy, due days ago, days
# late, amount)]; `not_due` is what the latest notification reports as not yet due.
# `news` is set for the real ones (fetched) and the invented stories below.
B = dict
BUYERS = [
    # ---- India, large, real ------------------------------------------------------
    B(id="IN01", name="Tata Motors Limited", short="Tata Motors", sector="Automotive",
      town="Mumbai", country="IND", size="large", real=True, exchange="NSE",
      query='"Tata Motors"', aliases="Tata Motors",
      limits=[(WT1, 45 * CR, 60)], open=[], paid=[(WT1, 150, 4, 2.2 * CR)]),
    B(id="IN02", name="Larsen & Toubro Limited", short="L&T", sector="Engineering & Construction",
      town="Mumbai", country="IND", size="large", real=True, exchange="NSE",
      query='"Larsen & Toubro" OR "Larsen and Toubro"', aliases="Larsen & Toubro|Larsen and Toubro|L&T",
      limits=[(WT2, 35 * CR, 90)], open=[(WT2, 12, 1.8 * CR)], not_due={WT2: 6.5 * CR},
      paid=[(WT2, 210, 6, 1.4 * CR)]),
    B(id="IN03", name="Vodafone Idea Limited", short="Vodafone Idea", sector="Telecommunications",
      town="Mumbai", country="IND", size="large", real=True, exchange="NSE",
      query='"Vodafone Idea" OR "Voda Idea"', aliases="Vodafone Idea|Voda Idea",
      limits=[(SCF, 12 * CR, 90)], open=[(SCF, 18, 90 * L)], not_due={SCF: 3.1 * CR},
      paid=[(SCF, 120, 9, 75 * L), (SCF, 240, 5, 60 * L)]),
    # ---- India, medium, invented ------------------------------------------------
    B(id="IN04", name="Shrivana Textile Mills Private Limited", short="Shrivana Textiles",
      sector="Textiles", town="Tiruppur", country="IND", size="medium",
      limits=[(WT1, 8 * CR, 60), (SCF, 2 * CR, 60)],
      open=[(WT1, 50, 1.1 * CR), (SCF, 34, 40 * L), (WT1, 20, 60 * L)],
      not_due={WT1: 2.5 * CR, SCF: 55 * L},
      paid=[(WT1, 300, 10, 70 * L), (WT1, 240, 14, 85 * L), (WT1, 160, 22, 95 * L)]),
    B(id="IN05", name="Vardhit Auto Components Limited", short="Vardhit Auto",
      sector="Auto Components", town="Chennai", country="IND", size="medium",
      limits=[(WT2, 6 * CR, 60)], open=[(WT2, 36, 70 * L)], not_due={WT2: 1.9 * CR},
      paid=[(WT2, 330, 3, 40 * L), (WT2, 260, 5, 45 * L), (WT2, 190, 4, 38 * L),
            (WT2, 120, 6, 52 * L)]),
    B(id="IN06", name="Aranya Pharma Packaging Private Limited", short="Aranya Packaging",
      sector="Pharma Packaging", town="Hyderabad", country="IND", size="medium",
      limits=[(WT1, 5 * CR, 45)], open=[], paid=[(WT1, 280, 7, 30 * L), (WT1, 140, 3, 26 * L)]),
    # ---- India, small, invented -------------------------------------------------
    B(id="IN07", name="Mehtab Agro Foods", short="Mehtab Agro", sector="Food Processing",
      town="Indore", country="IND", size="small",
      limits=[(SCF, 1.5 * CR, 60), (WT2, 80 * L, 45)],
      open=[(SCF, 64, 42 * L), (WT2, 41, 18 * L)], not_due={SCF: 35 * L, WT2: 12 * L},
      paid=[(SCF, 200, 18, 25 * L)]),
    B(id="IN08", name="Ravisha Engineering Works", short="Ravisha Engineering",
      sector="Engineering", town="Ludhiana", country="IND", size="small",
      limits=[(WT2, 60 * L, 45)], open=[], paid=[]),
    B(id="IN09", name="Jyotsna Electricals", short="Jyotsna Electricals",
      sector="Electrical Equipment", town="Coimbatore", country="IND", size="small",
      limits=[(WT1, 40 * L, 30)], open=[(WT1, 22, 6 * L)], not_due={WT1: 9 * L}, paid=[]),
    # ---- Overseas, large, real --------------------------------------------------
    B(id="OS01", name="Intel Corporation", short="Intel", sector="Semiconductors",
      town="Santa Clara, CA", country="USA", size="large", real=True, exchange="NASDAQ",
      ticker="INTC", cik=50863, query='"Intel"', aliases="Intel",
      limits=[(EXP, 7_000_000, 60)], open=[], paid=[]),
    B(id="OS02", name="The Boeing Company", short="Boeing", sector="Aerospace",
      town="Arlington, VA", country="USA", size="large", real=True, exchange="NYSE",
      ticker="BA", cik=12927, query='"Boeing"', aliases="Boeing",
      limits=[(EXP, 9_000_000, 60)], open=[], paid=[(EXP, 170, 3, 650_000)]),
    B(id="OS03", name="Ford Motor Company", short="Ford", sector="Automotive",
      town="Dearborn, MI", country="USA", size="large", real=True, exchange="NYSE",
      ticker="F", cik=37996, query='"Ford Motor" OR "Ford shares" OR "Ford stock"',
      aliases="Ford Motor|Ford", limits=[(EXP, 6_000_000, 60)],
      open=[(EXP, 9, 450_000)], not_due={EXP: 1_200_000}, paid=[]),
    # ---- Overseas, medium, invented ---------------------------------------------
    B(id="OS04", name="Brightwell Home Retail Inc.", short="Brightwell Retail",
      sector="Home Retail", town="Columbus, OH", country="USA", size="medium",
      limits=[(EXP, 2_500_000, 60)], open=[(EXP, 15, 180_000)], not_due={EXP: 520_000},
      paid=[(EXP, 190, 8, 150_000)]),
    B(id="OS05", name="Qasr Meridian Trading LLC", short="Qasr Meridian",
      sector="General Trading", town="Dubai", country="ARE", size="medium",
      limits=[(EXP, 1_800_000, 90)], open=[], paid=[(EXP, 230, 11, 210_000), (EXP, 110, 6, 190_000)]),
    B(id="OS06", name="Hessler Maschinenbau GmbH", short="Hessler", sector="Industrial Machinery",
      town="Stuttgart", country="DEU", size="medium",
      limits=[(EXP, 3_000_000, 60)], open=[(EXP, 52, 640_000)], not_due={EXP: 2_600_000},
      paid=[(EXP, 260, 9, 400_000), (EXP, 150, 19, 450_000)]),
    # ---- Overseas, small, invented ----------------------------------------------
    B(id="OS07", name="Pinecrest Outdoor Supply LLC", short="Pinecrest Outdoor",
      sector="Outdoor Retail", town="Boise, ID", country="USA", size="small",
      limits=[(EXP, 400_000, 45)], open=[], paid=[]),
    B(id="OS08", name="Kestrel Marine Parts Ltd", short="Kestrel Marine",
      sector="Marine Equipment", town="Southampton", country="GBR", size="small",
      limits=[(EXP, 500_000, 60)], open=[(EXP, 38, 70_000)], not_due={EXP: 95_000},
      paid=[(EXP, 140, 12, 60_000)]),
    B(id="OS09", name="Ostara Organics BV", short="Ostara Organics", sector="Organic Foods",
      town="Utrecht", country="NLD", size="small",
      limits=[(EXP, 300_000, 60)], open=[], paid=[(EXP, 180, 5, 40_000)]),
]

# Stories about invented companies. They will never appear in a real feed, so they are
# written here, dated relative to the as-of date, and marked Illustrative everywhere.
# (buyer, days ago, headline, body)
STORIES = [
    ("IN04", 30, "Lenders review exposure to Shrivana Textile Mills as orders slow",
     "Two banks are reviewing their exposure to Shrivana Textile Mills after the Tiruppur "
     "knitwear maker asked for longer credit on its working-capital lines, people familiar "
     "with the matter said. Export orders from two European retailers were cut this quarter."),
    ("OS04", 25, "Brightwell Home Retail scales back, closing 14 stores across the Midwest",
     "Brightwell Home Retail Inc. said it is scaling back its store network, closing 14 "
     "locations by January as same-store sales fell for a third straight quarter."),
    ("OS06", 15, "Hessler Maschinenbau has fallen behind on payments to suppliers",
     "Stuttgart machine builder Hessler Maschinenbau GmbH has fallen behind on payments to "
     "several component suppliers, three of them told a regional business paper, after a "
     "large customer postponed acceptance of two production lines."),
]


def _write(name: str, fields, rows: list[dict]) -> None:
    with (DIR / name).open("w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(fields), restval="", lineterminator="\n")
        wr.writeheader()
        wr.writerows(rows)


def _num(x: float) -> str:
    return str(int(round(x)))


def build(as_of: date) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    currency = {p[0]: p[3] for p in POLICIES}
    d = lambda days: (as_of - timedelta(days=days)).isoformat()  # noqa: E731

    entities = [{"legal_entity_id": INSURER[0], "role": "INSURER", "CORE_LGE_LEGAL_NAME": INSURER[1],
                 "CORE_LGE_USUAL_NAME": INSURER[2], "CORE_LGE_LEGAL_ADDRESS_TOWN": INSURER[3],
                 "CORE_LGE_COUNTRY": INSURER[4], "LGE_TRADE_SECTOR": "Trade Credit Insurance",
                 "ews_is_real": "Y"}]
    entities += [{"legal_entity_id": i, "role": "INSURED", "CORE_LGE_LEGAL_NAME": n,
                  "CORE_LGE_USUAL_NAME": u, "CORE_LGE_LEGAL_ADDRESS_TOWN": t,
                  "CORE_LGE_COUNTRY": "IND", "ews_is_real": "N"} for i, n, u, t in INSUREDS]
    entities += [{"legal_entity_id": b["id"], "role": "BUYER", "CORE_LGE_LEGAL_NAME": b["name"],
                  "CORE_LGE_USUAL_NAME": b["short"], "CORE_LGE_LEGAL_ADDRESS_TOWN": b["town"],
                  "CORE_LGE_COUNTRY": b["country"], "LGE_TRADE_SECTOR": b["sector"],
                  "ews_size_band": b["size"], "ews_is_real": "Y" if b.get("real") else "N",
                  "ews_is_listed": "Y" if b.get("exchange") else "N"} for b in BUYERS]

    policies = [{
        "policy_id": pid, "reference": pid, "product_type": product, "CORE_INSURER": INSURER[0],
        "CORE_MAIN_INSURED": insured, "CORE_CURRENCY": cur, "INSURED_PERCENTAGE": "80",
        "SYS_MAX_LIABILITY": _num(cap), "SYS_CLM_WAIT_PERIOD": "150",
        "OVERDUE_REPORTING_LIMIT": _num(threshold), "coverage_start": "2026-04-01",
        "coverage_end": "2027-03-31", "ews_deductible_pct": "10",
        "ews_overdue_reporting_window_days": "30",
    } for pid, product, insured, cur, cap, threshold, _ in POLICIES]
    underwriter = {p[0]: p[6] for p in POLICIES}

    limits, events, ageing, watch = [], [], [], []
    n = 0
    for k, b in enumerate(BUYERS):
        for j, (pid, amount, terms) in enumerate(b["limits"]):
            limits.append({
                "limit_id": f"LIM-{b['id']}-{j + 1}", "policy_id": pid,
                "CORE_LIMIT_REQUEST_DEBTOR": b["id"], "CORE_LIMIT_REQUEST_AMOUNT": _num(amount),
                "CORE_LIMIT_DECISION_AMOUNT": _num(amount),
                "CORE_LIMIT_DECISION_CURRENCY": currency[pid],
                "LIMIT_DECISION_EFFECTIVE_DATE": d(400 + 7 * k),
                "LIMIT_DECISION_EXPIRY_DATE": "2027-03-31",
                "LIMIT_DECISION_PAYMENT_TERMS": str(terms), "decision_status": "ACCEPTED",
                "underwriter_type": underwriter[pid], "decision_date": d(120 + 11 * k),
            })

        def event(pid, due_ago, amount, resolved_after=None):
            nonlocal n
            n += 1
            due = as_of - timedelta(days=due_ago)
            notified = due + timedelta(days=1)   # an overdue is unpaid the day after it falls due
            eid = f"N-{notified.strftime('%y%m%d')}-{n:05d}"
            row = {"event_id": eid, "reference": eid, "policy_id": pid,
                   "CORE_LIMIT_REQUEST_DEBTOR": b["id"], "status": "SUBMITTED",
                   "notification_date": notified.isoformat(), "NEV_REASON": "OVERDUE_INVOICE",
                   "NEV_ORIGINAL_DUE_DATE": due.isoformat(), "NEV_AMOUNT_AT_RISK": _num(amount),
                   "NEV_CURRENCY": currency[pid]}
            if resolved_after is None:
                row.update(ews_status="OPEN", ews_resolved_date="")
            else:
                row.update(ews_status="RESOLVED",
                           ews_resolved_date=(due + timedelta(days=resolved_after)).isoformat())
            events.append(row)
            return row

        for pid, due_ago, late, amount in b["paid"]:
            event(pid, due_ago, amount, late)
        latest: dict[str, dict] = {}
        buckets: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for pid, dpd, amount in sorted(b["open"], key=lambda o: -o[1]):
            latest[pid] = event(pid, dpd, amount)          # oldest first: the last is latest
            buckets[pid][data_model.bucket(dpd)] += amount
        for pid, row in latest.items():
            buckets[pid]["NOT_YET_DUE"] += b.get("not_due", {}).get(pid, 0)
            for name in data_model.AGEING_BUCKETS:
                if buckets[pid].get(name):
                    ageing.append({"event_id": row["event_id"], "NEV_OUTSTANDING_AGEING": name,
                                   "NEV_OUTSTANDING_AMOUNT": _num(buckets[pid][name])})

        if b.get("real"):
            watch.append({"buyer_id": b["id"], "country": b["country"],
                          "exchange": b.get("exchange", ""), "ticker": b.get("ticker", ""),
                          "cik": b.get("cik", ""), "news_query": b["query"],
                          "aliases": b["aliases"]})
        for o in b["open"]:
            if b.get("real") and o[1] >= 30:
                raise ValueError(f"{b['short']} is a real company: no invented overdue past 30 days")

    data_model.write(DIR, {"legal_entities": entities, "policies": policies, "limits": limits,
                           "notifiable_events": events, "notifiable_event_ageing": ageing})
    for legacy in data_model.LEGACY:
        (DIR / f"{legacy}.csv").unlink(missing_ok=True)
    _write("news_watchlist.csv",
           ("buyer_id", "country", "exchange", "ticker", "cik", "news_query", "aliases"), watch)

    from .fetch_news import FIELDS
    _write("illustrative_articles.csv", FIELDS, [{
        "article_id": f"ILL-{i + 1:03d}", "published_date": d(days),
        "publication": "Illustrative", "headline": head, "body": body,
        "mentioned_entity_as_written": next(b["name"] for b in BUYERS if b["id"] == bid),
        "url": "",
    } for i, (bid, days, head, body) in enumerate(STORIES)])
    if not (DIR / "news_articles.csv").exists():
        _write("news_articles.csv", FIELDS, [])
    print(f"Live-news book written to {DIR} as of {as_of.isoformat()}: {len(BUYERS)} buyers "
          f"({sum(1 for b in BUYERS if b.get('real'))} real), {len(policies)} policies, "
          f"{len(limits)} limits, {len(events)} overdue notifications, {len(STORIES)} "
          f"illustrative stories")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the illustrative live-news book")
    ap.add_argument("--as-of", default=None, help="book date (default: today)")
    args = ap.parse_args()
    build(date.fromisoformat(args.as_of) if args.as_of else date.today())


if __name__ == "__main__":
    main()
