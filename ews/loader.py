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


def _read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


class Loader:
    def __init__(self, data_dir: Path | str = DATA_DIR, *, harness: bool = False,
                 demo_steps: int = 0, swap_invoices: bool = False):
        self.dir = Path(data_dir)
        self.harness = harness
        self.demo_steps = demo_steps          # how many demo articles are in play
        self.swap_invoices = swap_invoices    # step 8: Udaan moves to 40 DPD
        self._cache: dict[str, list[dict]] = {}

    # -- the boundary --------------------------------------------------------
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


def parse_date(s: str) -> date:
    return date.fromisoformat(s)
