"""CSV access. The D7 leakage boundary lives here and nowhere else.

Every engine module goes through Loader(harness=False), which physically refuses
the label tables and strips the gt_* columns from news before an article can
reach the LLM.

The files are in the shape the insurance platform stores them (see data_model.py):
legal entities, policies, limits and overdue notifications, with the platform's
parameter codes as columns.
This module is also the one place that translates them into the engine's views -
buyers, insurers, credit lines, notifications - so no other module reads a platform code.
"""
from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

from .config import AS_OF, DATASET
from .data_model import AGEING_BUCKETS, EVENT_STATUSES, REASONS, ROLES

ROOT_DATA = Path(__file__).resolve().parent.parent / "data"
# the synthetic book lives at the top of data/; any other book in its own folder
DATA_DIR = ROOT_DATA if DATASET == "synthetic" else ROOT_DATA / DATASET

ENGINE_TABLES = frozenset({
    "legal_entities", "policies", "limits", "notifiable_events", "notifiable_event_ageing",
    "news_articles", "illustrative_articles", "news_watchlist",
})
# Stories about invented companies in a book of real ones (data/sbi): they could never
# come back from a real feed, so they sit apart from the fetched news, which a fetch
# rewrites. Optional: the synthetic book has none.
# The news watchlist (data/sbi) also names each real company's other spellings
# ("L&T", "Voda Idea"); the synthetic book has none.
OPTIONAL_TABLES = frozenset({"illustrative_articles", "news_watchlist"})
# harness_articles holds labelled stories the harness needs and the shipped news does
# not carry - the only parent-company story, and two of the decoys. The harness passes
# them to the engine label-stripped, as extra articles; the engine never reads the file.
HARNESS_ONLY = frozenset({"ground_truth", "payment_behaviour_monthly", "harness_articles"})
# What a story typed into the live sandbox must carry to go through the same pipeline
# as a shipped one. `mentioned_entity_as_written` is deliberately NOT here: the agent
# reads the body and finds the company itself, so the field is a convenience the
# dataset happens to carry, not an input the system depends on. The rule-based
# fallback does depend on it - see FallbackLLM.resolve - so a story typed without one
# resolves on Claude and refuses offline. That is the honest behaviour, not a bug.
LIVE_ARTICLE_FIELDS = ("article_id", "published_date", "publication", "headline", "body")
# An overdue more than a year old is a data-entry slip, not a risk signal.
MAX_LIVE_DPD = 365
# What a notification filed in the live sandbox must carry, as the notification form asks.
LIVE_EVENT_FIELDS = ("event_id", "policy_id", "CORE_LIMIT_REQUEST_DEBTOR", "notification_date",
                     "NEV_REASON", "NEV_AMOUNT_AT_RISK", "NEV_CURRENCY")

NEWS_LABEL_COLUMNS = (
    "gt_buyer_id", "gt_about_covered_buyer", "gt_is_parent_story", "gt_severity", "gt_category",
)


class LeakageError(RuntimeError):
    """Raised when engine code reaches for a table only the harness may read."""


class DataError(ValueError):
    """The dataset is internally inconsistent. Raised loudly - never worked around."""


def _read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


class Loader:
    def __init__(self, data_dir: Path | str = DATA_DIR, *, harness: bool = False,
                 extra_articles: list[dict] | None = None,
                 extra_events: list[dict] | None = None):
        self.dir = Path(data_dir)
        self.harness = harness
        # Live input from the dashboard sandbox: a story nobody prepared, and an overdue
        # notification filed by hand, as a policyholder files one on the platform. Both go through
        # the same pipeline as shipped data - there is no second code path for them. The
        # harness uses the same seam for its labelled fixture articles.
        self.extra_articles = [dict(a) for a in (extra_articles or [])]
        self.extra_events = [{"status": "SUBMITTED", "ews_status": "OPEN",
                              "ews_resolved_date": "", "NEV_ORIGINAL_DUE_DATE": "",
                              "reference": e.get("event_id", ""), **e}
                             for e in (extra_events or [])]
        for aid, art in enumerate(self.extra_articles):
            missing = [k for k in LIVE_ARTICLE_FIELDS if not str(art.get(k, "")).strip()]
            if missing:
                raise DataError(f"live article {aid + 1} is missing {missing}")
        for i, ev in enumerate(self.extra_events):
            missing = [k for k in LIVE_EVENT_FIELDS if not str(ev.get(k, "")).strip()]
            if missing:
                raise DataError(f"live notification {i + 1} is missing {missing}")
        self._cache: dict[str, list[dict]] = {}
        self._validated = False

    # -- the boundary --------------------------------------------------------
    def validate(self) -> None:
        """Referential integrity. Every one of these fails silently if unchecked:
        a duplicate id quietly overwrites, an orphan reference quietly does nothing."""
        if self._validated:
            return
        self._validated = True          # set first: the checks below call table()
        problems: list[str] = []

        def dupes(rows, key, what):
            seen, dup = set(), set()
            for r in rows:
                (dup if r[key] in seen else seen).add(r[key])
            if dup:
                problems.append(f"duplicate {what}: {sorted(dup)}")
            return seen

        ents = self.table("legal_entities")
        ids = dupes(ents, "legal_entity_id", "legal_entity_id in legal_entities.csv")
        role = {e["legal_entity_id"]: e["role"] for e in ents}
        for e in ents:
            if e["role"] not in ROLES:
                problems.append(f"legal entity {e['legal_entity_id']} has unknown role {e['role']!r}")
            for col in ("legal_entity_parent_id", "legal_entity_ultimate_parent_id"):
                ref = e.get(col)
                if ref and role.get(ref) != "GROUP":
                    problems.append(f"legal entity {e['legal_entity_id']} names absent group {ref}")

        policies = self.table("policies")
        pol = {p["policy_id"]: p for p in policies}
        dupes(policies, "policy_id", "policy_id in policies.csv")
        for p in policies:
            if role.get(p["CORE_INSURER"]) != "INSURER":
                problems.append(f"policy {p['policy_id']} names absent insurer {p['CORE_INSURER']}")
            if p.get("CORE_MAIN_INSURED") and role.get(p["CORE_MAIN_INSURED"]) != "INSURED":
                problems.append(f"policy {p['policy_id']} names absent insured "
                                f"{p['CORE_MAIN_INSURED']}")

        limits = self.table("limits")
        dupes(limits, "limit_id", "limit_id in limits.csv")
        for l in limits:
            if role.get(l["CORE_LIMIT_REQUEST_DEBTOR"]) != "BUYER":
                problems.append(f"credit limit {l['limit_id']} names absent buyer "
                                f"{l['CORE_LIMIT_REQUEST_DEBTOR']}")
            p = pol.get(l["policy_id"])
            if p is None:
                problems.append(f"credit limit {l['limit_id']} names absent policy {l['policy_id']}")
            elif l["CORE_LIMIT_DECISION_CURRENCY"] != p["CORE_CURRENCY"]:
                problems.append(f"credit limit {l['limit_id']} is in "
                                f"{l['CORE_LIMIT_DECISION_CURRENCY']}, its policy in {p['CORE_CURRENCY']}")
        covered = {l["CORE_LIMIT_REQUEST_DEBTOR"] for l in limits}
        for b in sorted(i for i in ids if role[i] == "BUYER" and i not in covered):
            # scored but on no insurer's book: it would appear on the home page and on
            # no insurer page, with no exposure and no recommendation
            problems.append(f"buyer {b} has no credit limit line")
        # run.py indexes articles by id; a duplicate would silently replace another
        dupes(self.news(), "article_id", "article_id in news_articles.csv")

        events = self.events()
        ev_ids = dupes(events, "event_id", "event_id in notifiable_events.csv")
        lines = {(l["CORE_LIMIT_REQUEST_DEBTOR"], l["policy_id"]) for l in limits}
        for ev in self.extra_events:
            # a policyholder notifies on a buyer its own policy covers
            if (ev["CORE_LIMIT_REQUEST_DEBTOR"], ev["policy_id"]) not in lines:
                problems.append(f"notification {ev['event_id']}: policy {ev['policy_id']} has "
                                f"no limit on buyer {ev['CORE_LIMIT_REQUEST_DEBTOR']}")
        for ev in events:
            eid = ev["event_id"]
            if role.get(ev["CORE_LIMIT_REQUEST_DEBTOR"]) != "BUYER":
                problems.append(f"notification {eid} names absent buyer "
                                f"{ev['CORE_LIMIT_REQUEST_DEBTOR']}")
            p = pol.get(ev["policy_id"])
            if p is None:
                problems.append(f"notification {eid} names absent policy {ev['policy_id']}")
            elif ev["NEV_CURRENCY"] != p["CORE_CURRENCY"]:
                problems.append(f"notification {eid} is in {ev['NEV_CURRENCY']}, "
                                f"its policy in {p['CORE_CURRENCY']}")
            if ev["NEV_REASON"] not in REASONS:
                problems.append(f"notification {eid} has unknown reason {ev['NEV_REASON']!r}")
            if ev["ews_status"] not in EVENT_STATUSES:
                problems.append(f"notification {eid} has unknown status {ev['ews_status']!r}")
            if ev["NEV_REASON"] == "OVERDUE_INVOICE" and not ev["NEV_ORIGINAL_DUE_DATE"]:
                # the platform makes the original due date mandatory for an overdue invoice
                problems.append(f"notification {eid} is an overdue invoice with no due date")
            if ev["ews_status"] == "RESOLVED" and not ev["ews_resolved_date"]:
                problems.append(f"notification {eid} is resolved with no resolution date")
            for col in ("notification_date", "NEV_ORIGINAL_DUE_DATE", "ews_resolved_date"):
                if ev.get(col):
                    try:
                        parse_date(ev[col], what=f"notification {eid} {col}")
                    except DataError as exc:
                        problems.append(str(exc))
        for a in self.table("notifiable_event_ageing"):
            if a["event_id"] not in ev_ids:
                problems.append(f"ageing row names absent notification {a['event_id']}")
            if a["NEV_OUTSTANDING_AGEING"] not in AGEING_BUCKETS:
                problems.append(f"ageing row for {a['event_id']} has unknown bucket "
                                f"{a['NEV_OUTSTANDING_AGEING']!r}")

        if problems:
            raise DataError("dataset is inconsistent:\n  - " + "\n  - ".join(sorted(set(problems))))

    def table(self, name: str) -> list[dict]:
        if name in HARNESS_ONLY and not self.harness:
            raise LeakageError(
                f"'{name}' holds answer labels and is readable only by the harness. "
                f"Construct Loader(harness=True) if you are the harness."
            )
        if name not in ENGINE_TABLES and name not in HARNESS_ONLY:
            raise KeyError(f"unknown table '{name}'")
        if name not in self._cache:
            path = self.dir / f"{name}.csv"
            self._cache[name] = [] if name in OPTIONAL_TABLES and not path.exists() else _read(path)
        return self._cache[name]

    # -- engine views --------------------------------------------------------
    # The engine never reads a platform code: these views are the translation.
    def _entities(self, role: str) -> list[dict]:
        return [e for e in self.table("legal_entities") if e["role"] == role]

    def buyers(self) -> list[dict]:
        return [{"buyer_id": e["legal_entity_id"], "buyer_name": e["CORE_LGE_LEGAL_NAME"],
                 "short_name": e["CORE_LGE_USUAL_NAME"] or e["CORE_LGE_LEGAL_NAME"],
                 "sector": e["LGE_TRADE_SECTOR"], "city": e["CORE_LGE_LEGAL_ADDRESS_TOWN"],
                 "country": e["CORE_LGE_COUNTRY"], "size_band": e["ews_size_band"],
                 "parent_id": e["legal_entity_parent_id"], "is_real": e["ews_is_real"] == "Y"}
                for e in self._entities("BUYER")]

    def parent_companies(self) -> list[dict]:
        return [{"parent_id": e["legal_entity_id"], "name": e["CORE_LGE_LEGAL_NAME"],
                 "hq": e["CORE_LGE_LEGAL_ADDRESS_TOWN"], "listed": e["ews_is_listed"]}
                for e in self._entities("GROUP")]

    def clients(self) -> list[dict]:
        """The insurers: each one's book is the limits on its policies."""
        return [{"client_id": e["legal_entity_id"], "client_name": e["CORE_LGE_LEGAL_NAME"],
                 "city": e["CORE_LGE_LEGAL_ADDRESS_TOWN"], "country": e["CORE_LGE_COUNTRY"]}
                for e in self._entities("INSURER")]

    def events(self) -> list[dict]:
        """Shipped notifications plus any filed in the live sandbox."""
        return list(self.table("notifiable_events")) + self.extra_events

    def policies_by_id(self) -> dict[str, dict]:
        return {p["policy_id"]: p for p in self.table("policies")}

    def credit_limits(self) -> list[dict]:
        pol = self.policies_by_id()
        return [{"limit_id": l["limit_id"], "policy_id": l["policy_id"],
                 "client_id": pol[l["policy_id"]]["CORE_INSURER"],
                 "buyer_id": l["CORE_LIMIT_REQUEST_DEBTOR"],
                 "credit_limit": float(l["CORE_LIMIT_DECISION_AMOUNT"]),
                 "currency": l["CORE_LIMIT_DECISION_CURRENCY"],
                 "insured_pct": l["LIMIT_DECISION_INSURED_PERCENTAGE"],
                 "payment_terms_days": int(l["LIMIT_DECISION_PAYMENT_TERMS"] or 0),
                 "limit_approved_date": l["LIMIT_DECISION_EFFECTIVE_DATE"],
                 "last_reviewed_date": l["decision_date"],
                 "limit_status": l["decision_status"]}
                for l in self.table("limits")]

    def notifications(self) -> list[dict]:
        """Overdue notifications known on the as-of date, with days past due for open ones.

        A notification dated after the as-of date is not known yet, and one resolved
        after it was still open then. One filed in the live sandbox is read exactly like
        a shipped one: its days past due follow from its original due date.
        """
        pol = self.policies_by_id()
        ageing: dict[str, list[dict]] = {}
        for a in self.table("notifiable_event_ageing"):
            ageing.setdefault(a["event_id"], []).append(
                {"bucket": a["NEV_OUTSTANDING_AGEING"], "amount": float(a["NEV_OUTSTANDING_AMOUNT"])})
        out = []
        for ev in self.events():
            eid = ev["event_id"]
            notified = parse_date(ev["notification_date"], what=f"notification {eid} notification_date")
            if notified > AS_OF:
                continue
            resolved = (parse_date(ev["ews_resolved_date"], what=f"notification {eid} resolved date")
                        if ev["ews_resolved_date"] else None)
            is_open = ev["ews_status"] == "OPEN" or (resolved is not None and resolved > AS_OF)
            due = (parse_date(ev["NEV_ORIGINAL_DUE_DATE"], what=f"notification {eid} due date")
                   if ev["NEV_ORIGINAL_DUE_DATE"] else None)
            out.append({
                "event_id": eid, "policy_id": ev["policy_id"],
                "client_id": pol[ev["policy_id"]]["CORE_INSURER"],
                "buyer_id": ev["CORE_LIMIT_REQUEST_DEBTOR"], "reason": ev["NEV_REASON"],
                "notification_date": ev["notification_date"],
                "original_due_date": ev["NEV_ORIGINAL_DUE_DATE"],
                "amount_at_risk": float(ev["NEV_AMOUNT_AT_RISK"] or 0),
                "currency": ev["NEV_CURRENCY"],
                "status": "OPEN" if is_open else ev["ews_status"],
                "resolved_date": ev["ews_resolved_date"] if not is_open else "",
                "dpd": max(0, (AS_OF - due).days) if (is_open and due) else None,
                "ageing": ageing.get(eid, []),
            })
        return out

    def news(self) -> list[dict]:
        """Shipped articles plus any extra ones (live sandbox input, harness fixtures).

        gt_* columns are stripped unless this is the harness — the LLM must never
        see the answer it is being asked for.
        """
        rows = list(self.table("news_articles")) + list(self.table("illustrative_articles"))
        rows += self.extra_articles
        if self.harness:
            return rows
        return [{k: v for k, v in r.items() if k not in NEWS_LABEL_COLUMNS} for r in rows]

    # -- convenience indexes -------------------------------------------------
    def buyers_by_id(self) -> dict[str, dict]:
        return {b["buyer_id"]: b for b in self.buyers()}

    def clients_by_id(self) -> dict[str, dict]:
        return {c["client_id"]: c for c in self.clients()}

    def parents_by_id(self) -> dict[str, dict]:
        return {p["parent_id"]: p for p in self.parent_companies()}

    def aliases(self) -> dict[str, list[str]]:
        """Other spellings of a buyer's name, by buyer id, from the news watchlist."""
        out: dict[str, list[str]] = {}
        for w in self.table("news_watchlist"):
            names = [a.strip() for a in w.get("aliases", "").split("|") if a.strip()]
            if names:
                out[w["buyer_id"]] = names
        return out

    def subsidiaries(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for b in self.buyers():
            if b.get("parent_id"):
                out.setdefault(b["parent_id"], []).append(b["buyer_id"])
        return out


def parse_date(s: str, *, what: str = "date") -> date:
    """Fail with something an operator can act on, not 'Invalid isoformat string'."""
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError) as exc:
        raise DataError(f"{what}: cannot read {s!r} as a date ({exc})") from exc
