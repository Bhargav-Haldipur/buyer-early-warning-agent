"""CSV access. The D7 leakage boundary lives here and nowhere else.

Every engine module goes through Loader(harness=False), which physically refuses
the label tables and strips the gt_* columns from news before an article can
reach the LLM.
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

ENGINE_TABLES = frozenset(
    {"clients", "buyers", "credit_limits", "invoices", "news_articles", "parent_companies"}
)
HARNESS_ONLY = frozenset({"ground_truth", "payment_behaviour_monthly"})
# What a story typed into the live sandbox must carry to go through the same
# pipeline as a shipped one. Nothing here is optional: the news agent reads all of it.
LIVE_ARTICLE_FIELDS = ("article_id", "published_date", "publication", "headline",
                       "body", "mentioned_entity_as_written")
# An invoice more than a year overdue is a data-entry slip, not a risk signal.
MAX_LIVE_DPD = 365

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
                 demo_steps: int = 0, swap_invoices: bool = False,
                 extra_articles: list[dict] | None = None,
                 dpd_overrides: dict[str, int] | None = None):
        # a negative slice silently *keeps* demo articles ([:-1] of 7 keeps 6), so the
        # range is checked rather than trusted - but only when the demo is in play, so a
        # dataset without a demo/ folder still loads
        if demo_steps:
            demo_file = Path(data_dir) / "demo" / "demo_articles_to_add.csv"
            if not demo_file.exists():
                raise ValueError(f"demo_steps={demo_steps} but there is no {demo_file}")
            available = len(_read(demo_file))
            if not 0 <= demo_steps <= available:
                raise ValueError(f"demo_steps must be between 0 and {available}, "
                                 f"got {demo_steps}")
        elif demo_steps < 0:
            raise ValueError(f"demo_steps must not be negative, got {demo_steps}")
        self.dir = Path(data_dir)
        self.harness = harness
        self.demo_steps = demo_steps          # how many demo articles are in play
        self.swap_invoices = swap_invoices    # step 8: Kessler moves to 40 DPD
        # Live input from the dashboard sandbox: a story nobody prepared, and an
        # invoice aged by hand. Both go through the same pipeline as shipped data -
        # there is no second code path for them, which is the point of the demo.
        self.extra_articles = [dict(a) for a in (extra_articles or [])]
        self.dpd_overrides = {str(b): int(d) for b, d in (dpd_overrides or {}).items()}
        for aid, art in enumerate(self.extra_articles):
            missing = [k for k in LIVE_ARTICLE_FIELDS if not str(art.get(k, "")).strip()]
            if missing:
                raise DataError(f"live article {aid + 1} is missing {missing}")
        for bid, dpd in self.dpd_overrides.items():
            if not 0 <= dpd <= MAX_LIVE_DPD:
                raise DataError(f"days past due for {bid} must be between 0 and "
                                f"{MAX_LIVE_DPD}, got {dpd}")
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

        buyers = dupes(self.buyers(), "buyer_id", "buyer_id in buyers.csv")
        clients = dupes(self.clients(), "client_id", "client_id in clients.csv")
        parents = dupes(self.parent_companies(), "parent_id", "parent_id in parent_companies.csv")
        dupes(self.credit_limits(), "limit_id", "limit_id in credit_limits.csv")

        for b in self.buyers():
            if b.get("parent_id") and b["parent_id"] not in parents:
                problems.append(f"buyer {b['buyer_id']} names absent parent {b['parent_id']}")
        for l in self.credit_limits():
            if l["buyer_id"] not in buyers:
                problems.append(f"credit limit {l['limit_id']} names absent buyer {l['buyer_id']}")
            if l["client_id"] not in clients:
                problems.append(f"credit limit {l['limit_id']} names absent client {l['client_id']}")
        covered = {l["buyer_id"] for l in self.credit_limits()}
        for b in buyers - covered:
            # scored but on no insurer's book: it would appear on the home page and on
            # no client page, with no exposure and no recommendation
            problems.append(f"buyer {b} has no credit limit line")
        # run.py indexes articles by id; a duplicate would silently replace another
        dupes(self.news(), "article_id", "article_id in news_articles.csv")
        for i in self.invoices():
            if i["buyer_id"] not in buyers:
                problems.append(f"invoice {i['invoice_id']} names absent buyer {i['buyer_id']}")
            elif i["client_id"] not in clients:
                problems.append(f"invoice {i['invoice_id']} names absent client {i['client_id']}")

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
            self._cache[name] = _read(self.dir / f"{name}.csv")
        return self._cache[name]

    # -- engine inputs -------------------------------------------------------
    def clients(self) -> list[dict]:
        return self.table("clients")

    def buyers(self) -> list[dict]:
        return self.table("buyers")

    def parent_companies(self) -> list[dict]:
        return self.table("parent_companies")

    def credit_limits(self) -> list[dict]:
        return self.table("credit_limits")

    def invoices(self) -> list[dict]:
        rows = (_read(self.dir / "demo" / "invoices_after_payment_demo.csv")
                if self.swap_invoices else self.table("invoices"))
        if not self.dpd_overrides:
            return rows
        # copy first: table() hands back the cached list, and an override must not
        # leak into the next Loader that reads the same table
        rows = [dict(r) for r in rows]
        for bid, dpd in self.dpd_overrides.items():
            open_rows = [r for r in rows if r["buyer_id"] == bid and r["status"] == "Open"]
            if not open_rows:
                raise DataError(f"buyer {bid} has no open invoice to age")
            worst = max(open_rows, key=lambda r: int(r["days_past_due"] or 0))
            worst["days_past_due"] = str(dpd)
        return rows

    def news(self) -> list[dict]:
        """Baseline articles plus however many demo articles the demo has reached.

        gt_* columns are stripped unless this is the harness — the LLM must never
        see the answer it is being asked for.
        """
        rows = list(self.table("news_articles"))
        if self.demo_steps:
            rows += _read(self.dir / "demo" / "demo_articles_to_add.csv")[: self.demo_steps]
        rows += self.extra_articles
        if self.harness:
            return rows
        return [{k: v for k, v in r.items() if k not in NEWS_LABEL_COLUMNS} for r in rows]

    def demo_articles(self) -> list[dict]:
        return _read(self.dir / "demo" / "demo_articles_to_add.csv")

    # -- convenience indexes -------------------------------------------------
    def buyers_by_id(self) -> dict[str, dict]:
        return {b["buyer_id"]: b for b in self.buyers()}

    def clients_by_id(self) -> dict[str, dict]:
        return {c["client_id"]: c for c in self.clients()}

    def parents_by_id(self) -> dict[str, dict]:
        return {p["parent_id"]: p for p in self.parent_companies()}

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
