"""Typed, dated, source-cited evidence. Producers emit these; they never score risk."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass(frozen=True)
class Evidence:
    kind: str          # 'payment' | 'news' | 'parent' | 'resolution'
    buyer_id: str      # '' when the item is about a parent or an unresolved article
    detail: str        # one human-readable sentence
    source: str        # invoice_id or article_id — always citable
    date: str          # ISO date of the underlying fact
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class EvidenceStore:
    def __init__(self) -> None:
        self._items: list[Evidence] = []

    def add(self, ev: Evidence) -> None:
        self._items.append(ev)

    def for_buyer(self, buyer_id: str, kind: str | None = None) -> list[Evidence]:
        return [e for e in self._items
                if e.buyer_id == buyer_id and (kind is None or e.kind == kind)]

    def of_kind(self, kind: str) -> list[Evidence]:
        return [e for e in self._items if e.kind == kind]

    def all(self) -> list[Evidence]:
        return list(self._items)

    def to_list(self) -> list[dict]:
        return [e.to_dict() for e in self._items]


def evidence_view(items: list[dict], kind: str = "all") -> list[dict]:
    """Evidence as the agents see it - without other agents' tool traces."""
    out = []
    for e in items:
        if kind != "all" and e["kind"] != kind:
            continue
        data = {k: v for k, v in e["data"].items() if k != "agent"}
        out.append({"id": e["source"], "kind": e["kind"], "date": e["date"],
                    "detail": e["detail"], "data": data})
    return out
