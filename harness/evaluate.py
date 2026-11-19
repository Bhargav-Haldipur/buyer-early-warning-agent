"""D9 - the only module that may read the labels.

    python -m harness.evaluate
    python -m harness.evaluate --json out/eval.json
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from ews import run as engine
from ews.agents.news import NewsDesk
from ews.config import DATASET, PARENT_STEP_DOWN
from ews.llm import get_llm
from ews.loader import Loader

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"


def evaluate(llm=None) -> dict:
    if DATASET != "synthetic":
        # real companies carry no labels: there is nothing to grade them against
        raise SystemExit(f"the harness grades the synthetic dataset only; unset "
                         f"EWS_DATASET (it is {DATASET!r}) and run it again")
    llm = llm or get_llm()
    labels = {r["buyer_id"]: r for r in Loader(harness=True).table("ground_truth")}
    all_demo = len(Loader(harness=True).demo_articles())
    labelled_news = Loader(harness=True, demo_steps=all_demo).news()
    hl = Loader(harness=True)
    # the agent investigates through an engine loader, so its tools never see a label
    desk = NewsDesk(Loader(demo_steps=all_demo))
    subs = hl.subsidiaries()
    parents_by_name = {p["name"]: p["parent_id"] for p in hl.parent_companies()}

    result = engine.run(llm=llm)
    verdicts = {r["buyer_id"]: r["verdict"] for r in result["buyers"]}
    gates: list[dict] = []

    unscored = sorted(set(labels) - set(verdicts))
    unlabelled = sorted(set(verdicts) - set(labels))
    if unscored or unlabelled:
        raise ValueError(
            "ground_truth.csv and the scored buyers disagree — every gate below would "
            f"be measuring a different population.\n  labelled but not scored: {unscored}"
            f"\n  scored but not labelled: {unlabelled}")

    # --- 1/2: detection and false positives ------------------------------
    missed = [b for b, l in labels.items() if l["failed"] == "Y" and verdicts[b]["band"] == "Healthy"]
    defaulters = [b for b, l in labels.items() if l["failed"] == "Y"]
    gates.append({"gate": "Detection - every defaulter leaves Healthy",
                  "status": PASS if not missed else FAIL,
                  "detail": f"{len(defaulters)-len(missed)}/{len(defaulters)} flagged"
                            + (f"; missed {missed}" if missed else "")})

    false_pos = [b for b, l in labels.items() if l["failed"] == "N" and verdicts[b]["band"] != "Healthy"]
    survivors = [b for b, l in labels.items() if l["failed"] == "N"]
    gates.append({"gate": "False positives - every survivor stays Healthy",
                  "status": PASS if not false_pos else FAIL,
                  "detail": f"{len(survivors)-len(false_pos)}/{len(survivors)} clean"
                            + (f"; flagged {false_pos}" if false_pos else "")})

    wobblers = [b for b, l in labels.items() if l["trajectory"] == "wobble_recovered"]
    # derived, not hardcoded: a buyer that never defaults yet carries a severity-5
    # story. Naming it would let a rename silently drop the check.
    traps = sorted({a["gt_buyer_id"] for a in labelled_news
                    if a["gt_buyer_id"] and int(a["gt_severity"]) == 5
                    and labels.get(a["gt_buyer_id"], {}).get("failed") == "N"})
    watched = sorted(set(wobblers) | set(traps))
    named = [b for b in watched if verdicts[b]["band"] != "Healthy"]
    trap_names = ", ".join(labels[b]["buyer_name"].split()[0] for b in traps) or "none in data"
    gates.append({"gate": "Named traps - wobblers and severity-5 survivors stay Healthy",
                  "status": PASS if not named else FAIL,
                  "detail": f"{len(wobblers)} wobblers + {len(traps)} sev-5 trap(s) "
                            f"({trap_names})" + (f"; flagged {named}" if named else "; all clean")})

    # --- 3/4: entity resolution ------------------------------------------
    recall_ok = recall_n = 0
    precision_bad = []
    sev_pairs: list[tuple[int, int]] = []
    for art in labelled_news:
        clean = {k: v for k, v in art.items() if not k.startswith("gt_")}
        res = desk.decide(clean, llm)
        if art["gt_category"] == "decoy":
            if res["kind"] != "none":
                precision_bad.append((art["article_id"], res["name"]))
            continue
        if art["gt_is_parent_story"] == "Y":
            recall_n += 1
            recall_ok += res["kind"] == "parent" and res["id"] == parents_by_name.get(
                art["mentioned_entity_as_written"])
        elif art["gt_buyer_id"]:
            recall_n += 1
            hit = res["kind"] == "buyer" and res["id"] == art["gt_buyer_id"]
            recall_ok += hit
            if hit and art.get("gt_severity"):
                sev_pairs.append((int(res["severity"]), int(art["gt_severity"])))

    gates.append({"gate": "Entity resolution - recall on genuine mentions",
                  "status": PASS if recall_ok == recall_n else FAIL,
                  "detail": f"{recall_ok}/{recall_n} resolved to the right entity"})
    n_decoys = sum(1 for a in labelled_news if a["gt_category"] == "decoy")
    gates.append({"gate": "Entity resolution - every decoy refused",
                  "status": PASS if not precision_bad else FAIL,
                  "detail": f"{n_decoys - len(precision_bad)}/{n_decoys} refused"
                            + (f"; wrongly matched {precision_bad}" if precision_bad else "")})

    # --- 5: severity agreement -------------------------------------------
    exact = sum(1 for got, want in sev_pairs if got == want)
    confusion = Counter((want, got) for got, want in sev_pairs if got != want)
    gates.append({"gate": "Severity agreement with labels",
                  "status": PASS if exact == len(sev_pairs) else WARN,
                  "detail": f"{exact}/{len(sev_pairs)} exact"
                            + (f"; disagreements (label->got) {dict(confusion)}" if confusion else "")})

    # --- 6: parent fan-out ------------------------------------------------
    demo = engine.run(demo_steps=all_demo, llm=llm)
    fan_issues = []
    for art in labelled_news:
        if art["gt_is_parent_story"] != "Y":
            continue
        pid = parents_by_name.get(art["mentioned_entity_as_written"])
        expected_subs, want_sev = set(subs.get(pid, [])), PARENT_STEP_DOWN[int(art["gt_severity"])]
        got = {r["buyer_id"]: e for r in demo["buyers"] for e in r["evidence"]
               if e["kind"] == "parent" and e["source"] == art["article_id"]}
        if set(got) != expected_subs:
            fan_issues.append(f"{art['article_id']}: reached {sorted(got)} not {sorted(expected_subs)}")
        for bid, e in got.items():
            if e["data"]["severity"] != want_sev:
                fan_issues.append(f"{art['article_id']}->{bid}: severity {e['data']['severity']} != {want_sev}")
    n_parent = sum(1 for a in labelled_news if a["gt_is_parent_story"] == "Y")
    gates.append({"gate": "Parent fan-out - exact subsidiaries, stepped-down severity",
                  "status": PASS if not fan_issues else FAIL,
                  "detail": f"{n_parent} parent story/stories" + ("; " + "; ".join(fan_issues) if fan_issues else "")})

    # --- 11: demo replay --------------------------------------------------
    # news points 0/20/40/60/80/100 by severity, every severity weighted at 35%
    expected = {1: ("BUY011", 21.7), 2: ("BUY014", 42.5), 3: ("BUY016", 49.4),
                4: ("BUY019", 56.3), 6: ("BUY023", 56.3), 7: ("BUY011", 49.4)}
    replay_bad = []
    for step, (bid, want) in expected.items():
        got = next(r["verdict"]["score"] for r in engine.run(demo_steps=step, llm=llm)["buyers"]
                   if r["buyer_id"] == bid)
        if abs(got - want) > 0.15:
            replay_bad.append(f"step {step} {bid}: {got} != {want}")
    swap = next(r["verdict"] for r in engine.run(demo_steps=all_demo, swap_invoices=True,
                                                 llm=llm)["buyers"]
                if r["buyer_id"] == "BUY023")
    if abs(swap["score"] - 73.7) > 0.15 or swap["band"] != "High Risk":
        replay_bad.append(f"step 8 BUY023: {swap['score']} {swap['band']} != 73.7 High Risk")
    gates.append({"gate": "Demo replay reproduces the planned scores",
                  "status": PASS if not replay_bad else FAIL,
                  "detail": "steps 1-8" + ("; " + "; ".join(replay_bad) if replay_bad else "")})

    # --- case file guard --------------------------------------------------
    bad_cf = [r["short_name"] for r in result["buyers"] if r["case_file"]["rejected_numbers"]]
    from_llm = sum(1 for r in result["buyers"] if r["case_file"]["source"] == "llm")
    gates.append({"gate": "Case file - every figure traced to the engine",
                  "status": PASS,
                  "detail": f"{from_llm} written by the model, "
                            f"{len(result['buyers'])-from_llm} templated"
                            + (f"; discarded for {bad_cf}" if bad_cf else "; none discarded")})

    return {"llm": getattr(llm, "name", "unknown"), "gates": gates,
            "scores": {r["short_name"]: [r["verdict"]["score"], r["verdict"]["band"],
                                         labels[r["buyer_id"]]["trajectory"]]
                       for r in result["buyers"]}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None)
    ap.add_argument("--agents", default=None,
                    help="comma-separated agents to run on Claude (the rest use rules)")
    ap.add_argument("--max-calls", type=int, default=None,
                    help="cap the model calls this harness run may make")
    args = ap.parse_args()
    from ews import settings
    try:
        settings.apply_overrides(args.agents, args.max_calls)
    except settings.SettingsError as exc:
        ap.error(str(exc))
    print(f"agents on Claude: {', '.join(settings.enabled_agents()) or 'none'} "
          f"· budget {settings.MAX_MODEL_CALLS} calls")
    report = evaluate()

    width = max(len(g["gate"]) for g in report["gates"])
    print(f"\nHARNESS  ·  llm={report['llm']}\n")
    for g in report["gates"]:
        mark = {"PASS": "PASS", "FAIL": "FAIL", "WARN": "WARN"}[g["status"]]
        print(f"  [{mark}] {g['gate']:<{width}}  {g['detail']}")
    failed = [g for g in report["gates"] if g["status"] == FAIL]
    print(f"\n  {len(report['gates'])-len(failed)}/{len(report['gates'])} gates passing\n")
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2))
        print(f"→ {args.json}")


if __name__ == "__main__":
    main()
