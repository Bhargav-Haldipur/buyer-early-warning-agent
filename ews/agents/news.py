"""Agent 2 - News Intelligence, two gated passes (D4).

Pass 1 resolves the entity and is reluctant; pass 2 grades severity and runs ONLY
on what pass 1 accepted. A parent story fans out to every subsidiary one rung down
the severity ladder.
"""
from __future__ import annotations

from ..config import NEWS_BASE, PARENT_STEP_DOWN, AS_OF, decay
from ..evidence import Evidence
from ..loader import Loader, parse_date


def _candidates(loader: Loader) -> list[dict]:
    out = [{"kind": "buyer", "id": b["buyer_id"], "name": b["buyer_name"],
            "sector": b["sector"], "city": b["city"]} for b in loader.buyers()]
    out += [{"kind": "parent", "id": p["parent_id"], "name": p["name"],
             "sector": "holding company", "city": p["hq"]} for p in loader.parent_companies()]
    return out


def assess(loader: Loader, llm, store) -> dict[str, dict]:
    cands = _candidates(loader)
    subs = loader.subsidiaries()
    buyers = loader.buyers_by_id()
    best: dict[str, dict] = {}

    def offer(buyer_id: str, value: float, rec: dict) -> None:
        if value > best.get(buyer_id, {}).get("value", -1.0):
            best[buyer_id] = {"value": value, **rec}

    for art in loader.news():
        # ---- pass 1: resolve (reluctant) ----
        res = llm.resolve(art, cands)
        age = (AS_OF - parse_date(art["published_date"])).days

        if res["kind"] == "none":
            store.add(Evidence(
                kind="resolution", buyer_id="",
                detail=f"refused '{art['mentioned_entity_as_written']}' - {res['reason']}",
                source=art["article_id"], date=art["published_date"],
                data={"resolved": False, "mention": art["mentioned_entity_as_written"],
                      "headline": art["headline"]},
            ))
            continue

        # ---- pass 2: grade (only what survived) ----
        grade = llm.grade(art, res["name"])
        sev = int(grade["severity"])

        if res["kind"] == "buyer":
            bid = res["id"]
            value = NEWS_BASE[sev] * decay(age)
            store.add(Evidence(
                kind="news", buyer_id=bid,
                detail=f"severity {sev} ({grade['category']}): {art['headline']}",
                source=art["article_id"], date=art["published_date"],
                data={"severity": sev, "category": grade["category"], "age_days": age,
                      "base": NEWS_BASE[sev], "decayed": round(value, 2),
                      "entity": res["name"], "via_parent": False,
                      "publication": art["publication"], "headline": art["headline"]},
            ))
            offer(bid, value, {"severity": sev, "category": grade["category"],
                               "article_id": art["article_id"], "age_days": age,
                               "headline": art["headline"], "via_parent": False,
                               "parent_name": None})
        else:
            sub_sev = PARENT_STEP_DOWN[sev]
            for bid in subs.get(res["id"], []):
                value = NEWS_BASE[sub_sev] * decay(age)
                store.add(Evidence(
                    kind="parent", buyer_id=bid,
                    detail=(f"parent {res['name']} - severity {sev} ({grade['category']}), "
                            f"counted at severity {sub_sev} for {buyers[bid]['short_name']}"),
                    source=art["article_id"], date=art["published_date"],
                    data={"severity": sub_sev, "parent_severity": sev,
                          "category": grade["category"], "age_days": age,
                          "base": NEWS_BASE[sub_sev], "decayed": round(value, 2),
                          "entity": res["name"], "via_parent": True,
                          "publication": art["publication"], "headline": art["headline"]},
                ))
                offer(bid, value, {"severity": sub_sev, "category": grade["category"],
                                   "article_id": art["article_id"], "age_days": age,
                                   "headline": art["headline"], "via_parent": True,
                                   "parent_name": res["name"]})

    for b in loader.buyers():
        best.setdefault(b["buyer_id"], {"value": 0.0, "severity": 0, "category": None,
                                        "article_id": None, "age_days": None,
                                        "headline": None, "via_parent": False,
                                        "parent_name": None})
    return best
