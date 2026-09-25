"""Orchestrator. Code, not an LLM (D0).

    python -m ews.run                      # the baseline snapshot
    python -m ews.run --demo-steps 4       # first four demo articles appended
    python -m ews.run --demo-steps 7 --swap-invoices   # the full demo
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from . import casefile
from .agents import adjudicator, news as news_agent, payment as payment_agent
from .config import AS_OF
from .evidence import EvidenceStore
from .limits import recommend
from .llm import get_llm
from .loader import Loader

OUT_DIR = Path(__file__).resolve().parent.parent / "out" / "runs"


def run(demo_steps: int = 0, swap_invoices: bool = False, llm=None, cache: bool = True) -> dict:
    loader = Loader(demo_steps=demo_steps, swap_invoices=swap_invoices)
    llm = llm or get_llm(cache=cache)
    store = EvidenceStore()

    payments = payment_agent.assess(loader, store)
    newsvals = news_agent.assess(loader, llm, store)

    verdicts = {bid: adjudicator.adjudicate(bid, payments[bid], newsvals[bid])
                for bid in payments}
    limit_lines = recommend(loader, verdicts)
    by_buyer: dict[str, list[dict]] = defaultdict(list)
    for line in limit_lines:
        by_buyer[line["buyer_id"]].append(line)

    buyers = loader.buyers_by_id()
    records = []
    for bid, verdict in verdicts.items():
        lines = by_buyer.get(bid, [])
        flagged = verdict["band"] != "Healthy"
        cf = casefile.write(llm if flagged else _TemplateOnly(), buyers[bid], verdict, lines)
        records.append({
            **{k: buyers[bid][k] for k in
               ("buyer_id", "buyer_name", "short_name", "sector", "city", "parent_id")},
            "verdict": verdict,
            "limits": lines,
            "case_file": cf,
            "evidence": [e.to_dict() for e in store.for_buyer(bid)],
        })
    records.sort(key=lambda r: -r["verdict"]["score"])

    clients = []
    for c in loader.clients():
        mine = [r for r in records if any(l["client_id"] == c["client_id"] for l in r["limits"])]
        counts = defaultdict(int)
        for r in mine:
            counts[r["verdict"]["band"]] += 1
        clients.append({
            **{k: c[k] for k in ("client_id", "client_name", "city")},
            "buyers": len(mine),
            "bands": dict(counts),
            "expected_loss": sum(l["expected_loss_before"] for r in mine for l in r["limits"]
                                 if l["client_id"] == c["client_id"]),
            "actions_pending": sum(1 for r in mine for l in r["limits"]
                                   if l["client_id"] == c["client_id"]
                                   and l["action"] in ("FREEZE", "REDUCE")),
        })

    return {
        "as_of": AS_OF.isoformat(),
        "llm": getattr(llm, "name", "unknown"),
        "demo_steps": demo_steps,
        "swap_invoices": swap_invoices,
        "clients": clients,
        "buyers": records,
        "refusals": [e.to_dict() for e in store.of_kind("resolution")],
    }


class _TemplateOnly:
    """Healthy buyers get the templated case file - no reason to spend a model call."""
    def write_case_file(self, facts):      # noqa: D102
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Buyer Early Warning Agent")
    ap.add_argument("--demo-steps", type=int, default=0,
                    help="append the first N demo articles (0-7)")
    ap.add_argument("--swap-invoices", action="store_true",
                    help="demo step 8: Udaan moves from 25 to 40 DPD")
    ap.add_argument("--no-cache", action="store_true", help="bypass the LLM disk cache")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    result = run(args.demo_steps, args.swap_invoices, cache=not args.no_cache)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tag = f"demo{args.demo_steps}" + ("-swap" if args.swap_invoices else "")
    path = Path(args.out) if args.out else OUT_DIR / f"{result['as_of']}-{tag}.json"
    path.write_text(json.dumps(result, indent=2))

    print(f"as of {result['as_of']}  ·  llm={result['llm']}  ·  {len(result['buyers'])} buyers")
    for r in result["buyers"]:
        if r["verdict"]["band"] != "Healthy":
            v = r["verdict"]
            print(f"  {v['band']:10} {r['short_name']:17} {v['score']:5.1f}   {v['trace']}")
    print(f"  ({sum(1 for r in result['buyers'] if r['verdict']['band']=='Healthy')} Healthy)")
    print(f"  refusals: {len(result['refusals'])}")
    print(f"→ {path}")


if __name__ == "__main__":
    main()
