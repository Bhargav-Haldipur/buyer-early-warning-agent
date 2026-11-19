"""Build the SBI Trade Credit book: one insurer, ten real US companies.

    python3 -m ews.sbi_seed                  # ledger dated as of today
    python3 -m ews.sbi_seed --as-of 2026-11-18

The companies, their SEC CIKs and their headquarters are real (checked against
EDGAR). The insurer's book on them - credit limits, invoices, payments - is
ILLUSTRATIVE: there is no real trade-credit ledger behind it. It is deliberately
unremarkable - everyone pays on or near time, two buyers are a few days late - so
that what moves a score in the demo is real news, never an invented payment problem
at a real company.

Re-run before a presentation so invoice dates sit around the day it is shown. It
rewrites everything in data/sbi/ except trusted_sources.csv and the fetched news.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, timedelta
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent / "data" / "sbi"

CLIENT = {
    "client_id": "SBI01", "client_name": "SBI Trade Credit", "sector": "Trade Credit Insurance",
    "city": "Mumbai", "policy_id": "TCI-SBI01-2026", "overdue_reporting_window_days": 30,
    "indemnity_pct": 90, "deductible_pct": 10, "max_liability_eur": 100_000_000,
}

# id, legal name, short, sector, HQ, CIK, ticker, Google News query, aliases,
# credit limit (USD), invoice size (USD), days past due on the worst open invoice
COMPANIES = [
    ("US001", "NVIDIA Corporation", "Nvidia", "Semiconductors", "Santa Clara, CA",
     1045810, "NVDA", '"Nvidia"', "Nvidia", 12_000_000, 900_000, 0),
    ("US002", "Microsoft Corporation", "Microsoft", "Software", "Redmond, WA",
     789019, "MSFT", '"Microsoft"', "Microsoft", 10_000_000, 750_000, 0),
    ("US003", "Apple Inc.", "Apple", "Consumer Electronics", "Cupertino, CA",
     320193, "AAPL", '"Apple Inc" OR "Apple shares" OR "Apple stock"', "Apple",
     10_000_000, 800_000, 0),
    ("US004", "Walmart Inc.", "Walmart", "Retail", "Bentonville, AR",
     104169, "WMT", '"Walmart"', "Walmart", 8_000_000, 600_000, 0),
    ("US005", "Caterpillar Inc.", "Caterpillar", "Construction Machinery", "Irving, TX",
     18230, "CAT", '"Caterpillar"', "Caterpillar", 6_000_000, 450_000, 0),
    ("US006", "Intel Corporation", "Intel", "Semiconductors", "Santa Clara, CA",
     50863, "INTC", '"Intel"', "Intel", 7_000_000, 500_000, 0),
    ("US007", "The Boeing Company", "Boeing", "Aerospace", "Arlington, VA",
     12927, "BA", '"Boeing"', "Boeing", 9_000_000, 700_000, 0),
    ("US008", "Ford Motor Company", "Ford", "Automotive", "Dearborn, MI",
     37996, "F", '"Ford Motor" OR "Ford shares" OR "Ford stock"', "Ford Motor|Ford",
     6_000_000, 450_000, 9),
    ("US009", "NIKE, Inc.", "Nike", "Apparel & Footwear", "Beaverton, OR",
     320187, "NKE", '"Nike"', "Nike", 4_000_000, 300_000, 0),
    ("US010", "Starbucks Corporation", "Starbucks", "Restaurants", "Seattle, WA",
     829224, "SBUX", '"Starbucks"', "Starbucks", 3_000_000, 220_000, 6),
]

TERMS = 60
# days late on the six settled invoices, oldest first: on time give or take a few days,
# so the settlement trend reads as stable for every buyer
SETTLED_LATE = [(-2, 1, 0, 2, -1, 1), (0, -1, 1, 0, 2, 0), (1, 0, -2, 1, 0, 1),
                (0, 2, 1, -1, 0, 0), (2, 0, 1, 0, -1, 2), (0, 1, 0, 2, 1, 0),
                (1, 2, 0, 1, 0, 2), (0, 1, 2, 0, 1, 1), (-1, 0, 0, 1, 2, 0),
                (2, 1, 0, 0, 1, 2)]


def _write(name: str, fields: list[str], rows: list[dict]) -> None:
    with (DIR / name).open("w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=fields)
        wr.writeheader()
        wr.writerows(rows)


def build(as_of: date) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    _write("clients.csv", list(CLIENT), [CLIENT])
    _write("parent_companies.csv", ["parent_id", "name", "hq", "listed"], [])

    buyers, watch, limits, invoices = [], [], [], []
    n = 0
    for k, (bid, name, short, sector, city, cik, ticker, query, aliases, limit, size,
            dpd) in enumerate(COMPANIES):
        buyers.append({"buyer_id": bid, "buyer_name": name, "short_name": short,
                       "sector": sector, "city": city, "size_band": "large", "parent_id": "",
                       "annual_turnover_eur": "", "relationship_start": "2023-01-15"})
        watch.append({"buyer_id": bid, "cik": cik, "ticker": ticker,
                      "news_query": query, "aliases": aliases})
        limits.append({"limit_id": f"LIM-{bid}", "client_id": CLIENT["client_id"],
                       "buyer_id": bid, "credit_limit_eur": limit, "payment_terms_days": TERMS,
                       "limit_approved_date": "2025-01-20",
                       "last_reviewed_date": (as_of - timedelta(days=120)).isoformat(),
                       "limit_status": "Active"})

        def inv(invoice_date: date, amount: int, paid: date | None, past_due: int | None):
            nonlocal n
            n += 1
            return {"invoice_id": f"SBI-INV{n:05d}", "client_id": CLIENT["client_id"],
                    "buyer_id": bid, "invoice_date": invoice_date.isoformat(),
                    "due_date": (invoice_date + timedelta(days=TERMS)).isoformat(),
                    "invoice_amount_eur": amount,
                    "payment_date": paid.isoformat() if paid else "",
                    "days_past_due": "" if past_due is None else past_due,
                    "status": "Paid" if paid else "Open"}

        # six settled invoices, one a month, the last due about a month ago
        for m, late in enumerate(SETTLED_LATE[k]):
            due = as_of - timedelta(days=30 * (6 - m) + 5)
            amount = size + 10_000 * ((k + m) % 5)
            invoices.append(inv(due - timedelta(days=TERMS), amount,
                                due + timedelta(days=late), None))
        # two open: the older one is due now (or a few days overdue), one not yet due
        due_now = as_of - timedelta(days=dpd)
        invoices.append(inv(due_now - timedelta(days=TERMS), size, None, dpd or None))
        invoices.append(inv(as_of + timedelta(days=25) - timedelta(days=TERMS), size, None, None))

    _write("buyers.csv", list(buyers[0]), buyers)
    _write("news_watchlist.csv", list(watch[0]), watch)
    _write("credit_limits.csv", list(limits[0]), limits)
    _write("invoices.csv", list(invoices[0]), invoices)
    news = DIR / "news_articles.csv"
    if not news.exists():
        from .fetch_news import FIELDS
        _write("news_articles.csv", list(FIELDS), [])
    print(f"SBI book written to {DIR} as of {as_of.isoformat()}: {len(buyers)} buyers, "
          f"{len(invoices)} invoices")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the illustrative SBI Trade Credit book")
    ap.add_argument("--as-of", default=None, help="ledger date (default: today)")
    args = ap.parse_args()
    build(date.fromisoformat(args.as_of) if args.as_of else date.today())


if __name__ == "__main__":
    main()
