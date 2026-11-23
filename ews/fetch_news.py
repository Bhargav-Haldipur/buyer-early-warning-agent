"""Fetch news for the live-news book from trusted external sources.

    EWS_DATASET=sbi python3 -m ews.fetch_news            # last 180 days
    EWS_DATASET=sbi python3 -m ews.fetch_news --days 90

This is the only module that touches the network. It writes what it finds to
data/sbi/news_articles.csv, and the engine reads that file like any other dataset -
so a run is reproducible from the file, the agent cache still works, and the
dashboard never waits on a feed in front of a room.

Sources are listed in data/sbi/trusted_sources.csv:
  feed       sec_edgar    - Form 8-K current reports, from the SEC's own API
  feed       google_news  - press coverage, kept only from the publishers below
  publisher  <name>       - a publisher whose stories are kept from google_news;
                            its `country` column limits it to buyers of that country
                            (blank: every buyer). Other spellings Google News uses
                            for the same publisher follow its name, split by "|"
                            ("Bloomberg|Bloomberg.com"); the first is the one shown.

Each company on news_watchlist.csv is routed by its country:
  IND  Google News, India edition (en-IN), Indian and global publishers
  USA  SEC EDGAR 8-K filings when the company has a CIK, and Google News, US edition
  else Google News in the country's edition where one is listed, else the US one
Only real companies are on the watchlist: an invented one could never come back
from a real feed, and its stories live in illustrative_articles.csv.

Fetching decides nothing about risk. Which company a story is about, and how severe
it is, is still the News agent's call when the engine runs.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from .config import AS_OF, DATASET
from .loader import DATA_DIR

FIELDS = ("article_id", "published_date", "publication", "headline", "body",
          "mentioned_entity_as_written", "url")
LOG = "news_fetch_log.json"

# The SEC asks every automated client to identify itself; set this to your own
# organisation and contact address before using it for anything beyond a demo.
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "TCI-EWS research@example.com")
SEC_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SEC_DOC = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
GOOGLE_URL = "https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={ceid}"
# Google News editions by CORE_LGE_COUNTRY: (hl, gl, ceid)
EDITIONS = {
    "IND": ("en-IN", "IN", "IN:en"),
    "USA": ("en-US", "US", "US:en"),
    "GBR": ("en-GB", "GB", "GB:en"),
}
DEFAULT_EDITION = "USA"


def edition(country: str) -> tuple[str, str, str]:
    return EDITIONS.get(country, EDITIONS[DEFAULT_EDITION])

# Form 8-K items, as the SEC titles them. The body of an 8-K "article" is these
# titles, so the News agent - and the rule-based fallback - grade the event the
# company itself reported, not a journalist's framing of it.
ITEMS_8K = {
    "1.01": "Entry into a Material Definitive Agreement",
    "1.02": "Termination of a Material Definitive Agreement",
    "1.03": "Bankruptcy or Receivership",
    "1.04": "Mine Safety - Reporting of Shutdowns and Patterns of Violations",
    "1.05": "Material Cybersecurity Incidents",
    "2.01": "Completion of Acquisition or Disposition of Assets",
    "2.02": "Results of Operations and Financial Condition",
    "2.03": "Creation of a Direct Financial Obligation or an Obligation under an "
            "Off-Balance Sheet Arrangement",
    "2.04": "Triggering Events That Accelerate or Increase a Direct Financial Obligation",
    "2.05": "Costs Associated with Exit or Disposal Activities",
    "2.06": "Material Impairments",
    "3.01": "Notice of Delisting or Failure to Satisfy a Continued Listing Rule",
    "3.02": "Unregistered Sales of Equity Securities",
    "3.03": "Material Modification to Rights of Security Holders",
    "4.01": "Changes in Registrant's Certifying Accountant",
    "4.02": "Non-Reliance on Previously Issued Financial Statements",
    "5.01": "Changes in Control of Registrant",
    "5.02": "Departure or Election of Directors or Officers",
    "5.03": "Amendments to Articles of Incorporation or Bylaws",
    "5.07": "Submission of Matters to a Vote of Security Holders",
    "7.01": "Regulation FD Disclosure",
    "8.01": "Other Events",
    "9.01": "Financial Statements and Exhibits",
}
# exhibits ride along with every other item and say nothing on their own
SILENT_ITEMS = {"9.01"}


def _get(url: str, *, sec: bool = False, timeout: int = 20) -> bytes:
    headers = {"User-Agent": SEC_USER_AGENT if sec else "Mozilla/5.0 (EWS)",
               "Accept-Encoding": "identity"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _sources(data_dir: Path) -> list[dict]:
    rows = [r for r in _read(data_dir / "trusted_sources.csv")
            if r["enabled"].strip().upper() == "Y"]
    unknown = {r["name"].strip() for r in rows if r["type"] == "feed"} - {"sec_edgar", "google_news"}
    if unknown:
        raise ValueError(f"trusted_sources.csv names feeds this fetcher does not know: "
                         f"{sorted(unknown)}")
    return rows


def _spellings(row: dict) -> list[str]:
    """Every name a publisher row matches: its own, then its other spellings."""
    return [n.strip() for n in row["name"].split("|") if n.strip()]


def load_sources(data_dir: Path) -> tuple[set[str], list[str]]:
    """Enabled feeds, and every trusted publisher spelling whatever its country."""
    rows = _sources(data_dir)
    return ({r["name"].strip() for r in rows if r["type"] == "feed"},
            [n for r in rows if r["type"] == "publisher" for n in _spellings(r)])


def publisher_names(data_dir: Path) -> list[str]:
    """One name per trusted publisher, for showing to a person."""
    return [_spellings(r)[0] for r in _sources(data_dir)
            if r["type"] == "publisher" and _spellings(r)]


def publishers_for(data_dir: Path, country: str) -> list[str]:
    """The publisher spellings trusted for a company in `country`: its own, and the global ones."""
    return [n for r in _sources(data_dir)
            if r["type"] == "publisher" and r.get("country", "").strip() in ("", country)
            for n in _spellings(r)]


def mention_in(text: str, aliases: list[str]) -> str:
    """The alias as the story writes it, or '' when the company is not named in it.

    The rule-based fallback resolves on this field; leaving it empty when the name is
    absent means a story that only came back from the search is refused offline
    rather than pinned on the company by default.

    A company's name is matched as written or in capitals, never in lower case:
    "fantasy intel" in a sports headline is the word, not Intel.
    """
    for alias in aliases:
        for spelling in dict.fromkeys((alias, alias.upper())):
            m = re.search(rf"(?<![A-Za-z0-9]){re.escape(spelling)}(?![A-Za-z0-9])", text)
            if m:
                return m.group(0)
    return ""


# ---------------------------------------------------------------- SEC EDGAR
def sec_filings(buyer: dict, watch: dict, since: date) -> list[dict]:
    cik = int(watch["cik"])
    data = json.loads(_get(SEC_URL.format(cik=cik), sec=True))
    recent = data["filings"]["recent"]
    out = []
    for i, form in enumerate(recent["form"]):
        if form not in ("8-K", "8-K/A"):
            continue
        filed = date.fromisoformat(recent["filingDate"][i])
        if filed < since or filed > AS_OF:
            continue
        items = [x.strip() for x in recent["items"][i].split(",") if x.strip()]
        said = [x for x in items if x not in SILENT_ITEMS] or items
        titles = [ITEMS_8K.get(x, f"Item {x}") for x in said]
        acc = recent["accessionNumber"][i]
        doc = recent["primaryDocument"][i]
        out.append({
            "article_id": f"SEC-{acc}",
            "published_date": filed.isoformat(),
            "publication": f"SEC EDGAR (Form {form})",
            "headline": f"{buyer['buyer_name']} files Form {form}: {'; '.join(titles)}",
            "body": (f"{buyer['buyer_name']} filed a current report on Form {form} with the "
                     f"US Securities and Exchange Commission on {filed.isoformat()}, "
                     f"reporting: " + "; ".join(f"Item {x} - {ITEMS_8K.get(x, 'other')}"
                                                for x in said) + "."),
            "mentioned_entity_as_written": buyer["buyer_name"],
            "url": SEC_DOC.format(cik=cik, acc=acc.replace("-", ""), doc=doc),
        })
    return out


# ---------------------------------------------------------------- Google News
def _strip(raw: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw or ""))).strip()


def google_news(buyer: dict, watch: dict, since: date, publishers: list[str],
                per_buyer: int, stats: dict | None = None) -> tuple[list[dict], int]:
    """Stories from the trusted publishers only. Returns (kept, dropped as untrusted).

    `stats`, when given, is filled with how many stories the search returned at all,
    so a fetch can show its whole funnel: found, dropped, kept.
    """
    days = max(1, (AS_OF - since).days)
    q = urllib.parse.quote(f"{watch['news_query']} when:{days}d")
    hl, gl, ceid = edition(watch.get("country", ""))
    root = ET.fromstring(_get(GOOGLE_URL.format(q=q, hl=hl, gl=gl, ceid=ceid)))
    trusted = {p.lower(): p for p in publishers}
    aliases = [a.strip() for a in watch["aliases"].split("|") if a.strip()]
    kept, dropped = [], 0
    items = list(root.iter("item"))
    if stats is not None:
        stats["returned"] = len(items)
    for item in items:
        source = (item.findtext("source") or "").strip()
        if source.lower() not in trusted:
            dropped += 1
            continue
        title = (item.findtext("title") or "").strip()
        # Google appends " - Publisher" to every title
        if title.endswith(f" - {source}"):
            title = title[: -len(source) - 3].strip()
        try:
            published = parsedate_to_datetime(item.findtext("pubDate") or "").astimezone(
                timezone.utc).date()
        except (TypeError, ValueError):
            continue
        if published < since or published > AS_OF:
            continue
        link = (item.findtext("link") or "").strip()
        desc = _strip(item.findtext("description") or "")
        body = desc if desc and desc.lower() != f"{title} {source}".lower() else title
        kept.append({
            "article_id": "GN-" + hashlib.sha1(link.encode()).hexdigest()[:12],
            "published_date": published.isoformat(),
            "publication": trusted[source.lower()],
            "headline": title,
            "body": body,
            "mentioned_entity_as_written": mention_in(title, aliases),
            "url": link,
        })
    kept.sort(key=lambda a: a["published_date"], reverse=True)
    return kept[:per_buyer], dropped


# ---------------------------------------------------------------- run
def fetch(days: int = 180, per_buyer: int = 12, data_dir: Path = DATA_DIR,
          quiet: bool = False) -> dict:
    if DATASET == "synthetic":
        raise SystemExit("the synthetic dataset is fixed; set EWS_DATASET=sbi to fetch news")
    say = (lambda *a: None) if quiet else (lambda *a: print(*a))
    from .loader import Loader
    feeds, publishers = load_sources(data_dir)
    out = data_dir / "news_articles.csv"
    # what the engine had before this fetch, so the page can say what is new
    had_ids = {r["article_id"] for r in _read(out)} if out.exists() else set()
    previous = last_fetch(data_dir)
    buyers = Loader(data_dir).buyers_by_id()
    watchlist = _read(data_dir / "news_watchlist.csv")
    since = AS_OF - timedelta(days=days)

    articles: dict[str, dict] = {}
    report = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "as_of": AS_OF.isoformat(), "days": days, "feeds": sorted(feeds),
              "publishers": publishers, "buyers": {}, "errors": []}
    for w in watchlist:
        b = buyers.get(w["buyer_id"])
        if b is None:
            raise ValueError(f"news_watchlist.csv names absent buyer {w['buyer_id']}")
        country = w.get("country", "") or b.get("country", "")
        w = {**w, "country": country}
        got = {"country": country, "edition": edition(country)[0], "sec_edgar": 0,
               "google_news": 0, "untrusted_dropped": 0, "returned": 0}
        if "sec_edgar" in feeds and str(w.get("cik", "")).strip().isdigit():
            try:
                for a in sec_filings(b, w, since):
                    articles[a["article_id"]] = a
                    got["sec_edgar"] += 1
            except Exception as exc:                                   # noqa: BLE001
                report["errors"].append(f"{b['short_name']} sec_edgar: {exc}")
            time.sleep(0.15)          # the SEC asks for no more than ten requests a second
        if "google_news" in feeds:
            try:
                stats: dict = {}
                kept, dropped = google_news(b, w, since, publishers_for(data_dir, country),
                                            per_buyer, stats)
                got["returned"] = stats.get("returned", 0)
                for a in kept:
                    # one story can come back for two companies' searches: keep the copy
                    # that names a company, so the fallback still has something to resolve
                    had = articles.get(a["article_id"])
                    if had is None or (not had["mentioned_entity_as_written"]
                                       and a["mentioned_entity_as_written"]):
                        articles[a["article_id"]] = a
                got.update(google_news=len(kept), untrusted_dropped=dropped)
            except Exception as exc:                                   # noqa: BLE001
                report["errors"].append(f"{b['short_name']} google_news: {exc}")
        got["coverage"] = got["sec_edgar"] + got["google_news"]
        report["buyers"][b["short_name"]] = got
        say(f"  {b['short_name']:14} {got['edition']:5}  8-K {got['sec_edgar']:3}   press "
            f"{got['google_news']:3}   (untrusted dropped {got['untrusted_dropped']})"
            + ("   - no coverage found" if not got["coverage"] else ""))

    if not articles and report["errors"]:
        # never replace a good file with an empty one because the network is down
        raise SystemExit("nothing fetched - news_articles.csv left as it was:\n  "
                         + "\n  ".join(report["errors"]))
    rows = sorted(articles.values(), key=lambda a: (a["published_date"], a["article_id"]),
                  reverse=True)
    per = report["buyers"].values()
    kept_per_search = sum(g["coverage"] for g in per)
    found = sum(g["returned"] + g["sec_edgar"] for g in per)
    untrusted = sum(g["untrusted_dropped"] for g in per)
    report["funnel"] = {
        "found": found,
        "untrusted_dropped": untrusted,
        # trusted, but older than the window or past the per-company cap
        "outside_window_or_cap": max(0, found - untrusted - kept_per_search),
        # the same story returned by two companies' searches
        "duplicates": max(0, kept_per_search - len(rows)),
        "kept": len(rows),
    }
    report["new"] = [a["article_id"] for a in rows if a["article_id"] not in had_ids]
    report["previous_fetch"] = previous["fetched_at"] if previous else None
    tmp = out.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=FIELDS)
        wr.writeheader()
        wr.writerows(rows)
    tmp.replace(out)
    report["articles"] = len(rows)
    (data_dir / LOG).write_text(json.dumps(report, indent=2))
    say(f"  {len(rows)} articles -> {out} ({len(report['new'])} new since the last fetch)")
    for err in report["errors"]:
        say(f"  ! {err}")
    return report


def read_articles(data_dir: Path = DATA_DIR) -> list[dict]:
    """The fetched stories as the last fetch wrote them (empty before the first)."""
    out = data_dir / "news_articles.csv"
    return _read(out) if out.exists() else []


def last_fetch(data_dir: Path = DATA_DIR) -> dict | None:
    p = data_dir / LOG
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch news for the live-news book from trusted sources")
    ap.add_argument("--days", type=int, default=180, help="how far back to look (default 180)")
    ap.add_argument("--per-buyer", type=int, default=12,
                    help="most press stories kept per company (default 12)")
    args = ap.parse_args()
    if not 1 <= args.days <= 730:
        ap.error("--days must be between 1 and 730 (older news scores zero anyway)")
    print(f"fetching news as of {AS_OF.isoformat()}, last {args.days} days")
    fetch(args.days, args.per_buyer)


if __name__ == "__main__":
    main()
