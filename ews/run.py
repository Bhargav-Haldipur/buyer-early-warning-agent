"""Orchestrator. Code, not an LLM (D0): it runs the four agents in a fixed order.

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
from .agents import adjudicator, definition, news as news_agent, payment as payment_agent
from .config import AS_OF
from .evidence import EvidenceStore
from .limits import recommend
from .llm import FallbackLLM, get_llm
from .loader import Loader

OUT_DIR = Path(__file__).resolve().parent.parent / "out" / "runs"


def run(demo_steps: int = 0, swap_invoices: bool = False, llm=None, cache: bool = True) -> dict:
    loader = Loader(demo_steps=demo_steps, swap_invoices=swap_invoices)
    loader.validate()          # fail on an inconsistent dataset, not halfway through scoring
    llm = llm or get_llm(cache=cache)
    store = EvidenceStore()

    payments = payment_agent.assess(loader, store, llm)
    newsvals = news_agent.assess(loader, llm, store)

    buyers = loader.buyers_by_id()
    articles = {a["article_id"]: a for a in loader.news()}
    verdicts = {}
    for bid in payments:
        v = adjudicator.adjudicate(bid, payments[bid], newsvals[bid])
        v["review"] = adjudicator.review(buyers[bid], v,
                                         [e.to_dict() for e in store.for_buyer(bid)],
                                         articles, llm)
        verdicts[bid] = v
    limit_lines = recommend(loader, verdicts)
    by_buyer: dict[str, list[dict]] = defaultdict(list)
    for line in limit_lines:
        by_buyer[line["buyer_id"]].append(line)

    write_for = definition.load("casefile").guardrails["run_for_bands"]
    records = []
    for bid, verdict in verdicts.items():
        lines = by_buyer.get(bid, [])
        items = [e.to_dict() for e in store.for_buyer(bid)]
        # bands outside settings.py run_for_bands (Healthy, by default) get the template
        cf = casefile.write(llm if verdict["band"] in write_for else _RULES, buyers[bid],
                            verdict, lines, items, articles)
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
        "agent_runs": _agent_stats(records, store),
        "spend": llm.spend() if hasattr(llm, "spend") else None,
        "demo_steps": demo_steps,
        "swap_invoices": swap_invoices,
        "clients": clients,
        "buyers": records,
        "refusals": [e.to_dict() for e in store.of_kind("resolution")],
    }


_RULES = FallbackLLM(cache=False)


def _agent_stats(records: list[dict], store: EvidenceStore) -> dict:
    """How each agent's runs went: ran as agent, rules (no Claude), or fell back."""
    runs: dict[str, list[dict]] = defaultdict(list)
    seen_articles = set()
    for e in store.all():
        a = e.data.get("agent")
        if not a:
            continue
        if e.kind == "payment_review":
            runs["payment"].append(a)
        elif e.source not in seen_articles:          # a parent story fans out to many
            seen_articles.add(e.source)
            runs["news"].append(a)
    for r in records:
        if r["verdict"].get("review"):
            runs["adjudicator"].append(r["verdict"]["review"]["agent"])
        if r["verdict"]["band"] != "Healthy":
            runs["casefile"].append(r["case_file"]["agent"])
    out = {}
    for name in ("payment", "news", "adjudicator", "casefile"):
        c = defaultdict(int)
        for a in runs[name]:
            c[a["mode"]] += 1
        out[name] = dict(c)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Buyer Early Warning Agent")
    ap.add_argument("--demo-steps", type=int, default=0,
                    help="append the first N demo articles (0-7)")
    ap.add_argument("--swap-invoices", action="store_true",
                    help="demo step 8: Kessler moves from 25 to 40 DPD")
    ap.add_argument("--no-cache", action="store_true", help="bypass the LLM disk cache")
    ap.add_argument("--agents", default=None,
                    help="comma-separated agents to run on Claude this run "
                         "(payment,news,adjudicator,casefile); the rest use rules")
    ap.add_argument("--max-calls", type=int, default=None,
                    help="override the run-wide model call budget (default: settings.MAX_MODEL_CALLS)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    from . import settings
    try:
        settings.apply_overrides(args.agents, args.max_calls)
    except settings.SettingsError as exc:
        ap.error(str(exc))
    if args.agents is not None or args.max_calls is not None:
        print(f"running on Claude: {', '.join(settings.enabled_agents()) or 'none'} "
              f"(others use rules) · budget {settings.MAX_MODEL_CALLS} calls")

    result = run(args.demo_steps, args.swap_invoices, cache=not args.no_cache)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # The filename records what produced the run, so a narrowed test run cannot
    # quietly overwrite a full one - they are different results, not versions.
    parts = [result["as_of"], f"demo{args.demo_steps}"]
    if args.swap_invoices:
        parts.append("swap")
    parts.append(result["llm"])
    on_claude = settings.enabled_agents()
    if result["llm"] == "claude" and set(on_claude) != set(settings.AGENTS):
        parts.append("agents-" + ("+".join(on_claude) if on_claude else "none"))
    path = Path(args.out) if args.out else OUT_DIR / ("-".join(parts) + ".json")
    path.write_text(json.dumps(result, indent=2))

    print(f"as of {result['as_of']}  ·  llm={result['llm']}  ·  {len(result['buyers'])} buyers")
    for r in result["buyers"]:
        if r["verdict"]["band"] != "Healthy":
            v = r["verdict"]
            print(f"  {v['band']:10} {r['short_name']:17} {v['score']:5.1f}   {v['trace']}")
    print(f"  ({sum(1 for r in result['buyers'] if r['verdict']['band']=='Healthy')} Healthy)")
    print(f"  refusals: {len(result['refusals'])}")
    for name, modes in result["agent_runs"].items():
        print(f"  agent {name:11} " + ", ".join(f"{n} {m}" for m, n in modes.items()))
    sp = result.get("spend")
    if sp is not None and not sp["by_model"]:
        print("  spend: nothing — every agent run came from the cache")
    elif sp:
        print("  spend (measured, not estimated):")
        for model, r in sp["by_model"].items():
            print(f"    {model:18} {r['calls']:4} calls  "
                  f"{r['input']:>9,} in  {r['output']:>8,} out  ${r['usd']:.2f}")
        print(f"    {'TOTAL':18} {sp['total_tokens']:>9,} tokens{'':20}${sp['total_usd']:.2f}")
    print(f"-> {path}")


if __name__ == "__main__":
    main()
