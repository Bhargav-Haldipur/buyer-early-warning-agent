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
                 demo_steps: int = 0, swap_invoices: bool = False):
        # a negative slice silently *keeps* demo articles ([:-1] of 7 keeps 6), so the
        # range is checked rather than trusted
        available = len(_read(Path(data_dir) / "demo" / "demo_articles_to_add.csv"))
        if not 0 <= demo_steps <= available:
            raise ValueError(f"demo_steps must be between 0 and {available}, got {demo_steps}")
        self.dir = Path(data_dir)
        self.harness = harness
        self.demo_steps = demo_steps          # how many demo articles are in play
        self.swap_invoices = swap_invoices    # step 8: Kessler moves to 40 DPD
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
        if self.swap_invoices:
            return _read(self.dir / "demo" / "invoices_after_payment_demo.csv")
        return self.table("invoices")

    def news(self) -> list[dict]:
        """Baseline articles plus however many demo articles the demo has reached.

        gt_* columns are stripped unless this is the harness — the LLM must never
        see the answer it is being asked for.
        """
        rows = list(self.table("news_articles"))
        if self.demo_steps:
            rows += _read(self.dir / "demo" / "demo_articles_to_add.csv")[: self.demo_steps]
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
