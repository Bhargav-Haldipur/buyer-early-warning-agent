"""Agent 2 - News Intelligence. Autonomous, one run per article (D4).
Defined in agents/news.md; this module holds its tools and the checks on its answer.

The agent investigates each article with read-only tools over the entity registry
and the rest of the news, then submits which covered entity (if any) the article is
about and how severe it is. It is deliberately reluctant: a wrong match puts a
healthy company on a watchlist.

Code keeps the parts that must not drift: the submitted entity must exist in the
registry, severity must be on the 0/3/4/5 ladder, and a parent story fans out to
every subsidiary one rung down the ladder. Without Claude, the same decision comes
from the two rule-based passes (strict_resolve, then keyword_grade).
"""
from __future__ import annotations

from ..config import NEWS_BASE, PARENT_STEP_DOWN, AS_OF, decay
from ..evidence import Evidence
from ..llm import FallbackLLM, tokens
from ..loader import Loader, parse_date
from . import definition
from .runtime import Tool, attempt


def _candidates(loader: Loader) -> list[dict]:
    out = [{"kind": "buyer", "id": b["buyer_id"], "name": b["buyer_name"],
            "sector": b["sector"], "city": b["city"]} for b in loader.buyers()]
    out += [{"kind": "parent", "id": p["parent_id"], "name": p["name"],
             "sector": "holding company", "city": p["hq"]} for p in loader.parent_companies()]
    return out


class NewsDesk:
    """The registry and article set one run's agents investigate."""

    def __init__(self, loader: Loader):
        self.candidates = _candidates(loader)
        self.by_id = {c["id"]: c for c in self.candidates}
        self.buyers = loader.buyers_by_id()
        self.parents = loader.parents_by_id()
        self.subs = loader.subsidiaries()
        self.articles = loader.news()
        self.rules = FallbackLLM(cache=False)

    # -- tools ------------------------------------------------------------
    def search_entities(self, name: str) -> list[dict]:
        want = set(tokens(name))
        if not want:
            raise ValueError("give a company name to search for")
        hits = [c for c in self.candidates if want & set(tokens(c["name"]))]
        return hits[:10] or [{"note": f"no covered entity shares a word with {name!r}"}]

    def get_entity(self, entity_id: str) -> dict:
        if entity_id in self.buyers:
            b = self.buyers[entity_id]
            parent = self.parents.get(b.get("parent_id") or "")
            return {"id": entity_id, "kind": "buyer", "name": b["buyer_name"],
                    "short_name": b["short_name"], "sector": b["sector"], "city": b["city"],
                    "size_band": b["size_band"],
                    "parent": {"id": parent["parent_id"], "name": parent["name"]} if parent else None}
        if entity_id in self.parents:
            p = self.parents[entity_id]
            return {"id": entity_id, "kind": "parent", "name": p["name"], "hq": p["hq"],
                    "listed": p["listed"],
                    "subsidiaries": [{"id": s, "name": self.buyers[s]["buyer_name"]}
                                     for s in self.subs.get(entity_id, [])]}
        raise ValueError(f"no entity {entity_id!r}; use search_entities")

    def find_articles(self, query: str, exclude: str) -> list[dict]:
        q = query.lower().strip()
        if not q:
            raise ValueError("give a word or name to search for")
        hits = [{"article_id": a["article_id"], "date": a["published_date"],
                 "publication": a["publication"], "headline": a["headline"],
                 "mentioned_as": a["mentioned_entity_as_written"]}
                for a in self.articles if a["article_id"] != exclude
                and q in f"{a['headline']} {a['body']} {a['mentioned_entity_as_written']}".lower()]
        return hits[:8] or [{"note": f"no other article mentions {query!r}"}]

    def submit(self, kind: str, entity_id: str, severity: int, category: str,
               reason: str, *, guard: dict | None = None, seen: set | None = None) -> dict:
        guard = guard or {"entity_must_be_looked_up": False, "allowed_severities": [0, 3, 4, 5]}
        if kind == "none":
            return {"kind": "none", "id": "", "name": "", "severity": 0,
                    "category": None, "reason": reason}
        c = self.by_id.get(entity_id)
        if c is None or c["kind"] != kind:
            raise ValueError(f"{entity_id!r} is not a registered {kind}; use search_entities "
                             f"and submit an id it returned, or kind 'none'")
        if guard["entity_must_be_looked_up"] and entity_id not in (seen or set()):
            raise ValueError(f"{entity_id!r} did not come back from search_entities or "
                             f"get_entity in this run; look it up before submitting it")
        allowed = [v for v in guard["allowed_severities"] if v in NEWS_BASE]
        if severity not in allowed:
            raise ValueError(f"severity must be one of {allowed}")
        return {"kind": kind, "id": c["id"], "name": c["name"], "severity": int(severity),
                "category": category.strip().lower().replace(" ", "_") or "other",
                "reason": reason}

    # -- the decision -----------------------------------------------------
    def rules_decision(self, art: dict) -> dict:
        res = self.rules.resolve(art, self.candidates)
        if res["kind"] == "none":
            return {**res, "severity": 0, "category": None}
        grade = self.rules.grade(art, res["name"])
        return {**res, "severity": int(grade["severity"]), "category": grade["category"]}

    def decide(self, art: dict, llm) -> dict:
        aid = art["article_id"]
        spec = definition.load("news")
        seen: set[str] = set()                   # ids the agent's lookups returned

        def search(name: str) -> list[dict]:
            hits = self.search_entities(name)
            seen.update(h["id"] for h in hits if "id" in h)
            return hits

        def entity(entity_id: str) -> dict:
            rec = self.get_entity(entity_id)
            seen.add(rec["id"])
            return rec

        tools = [
            Tool("search_entities", {"name": {"type": "string"}}, search),
            Tool("get_entity", {"entity_id": {"type": "string"}}, entity),
            Tool("find_articles", {"query": {"type": "string"}},
                 lambda query: self.find_articles(query, exclude=aid)),
            Tool("submit_assessment", {
                "kind": {"type": "string", "enum": ["buyer", "parent", "none"]},
                "entity_id": {"type": "string", "description": "registry id, or '' when kind is none"},
                "severity": {"type": "integer",
                             "enum": sorted(set(spec.guardrails["allowed_severities"]))},
                "category": {"type": "string", "description": "short snake_case label, e.g. wage_delay"},
                "reason": {"type": "string", "description": "one or two sentences"}},
                lambda **a: self.submit(**a, guard=spec.guardrails, seen=seen)),
        ]
        article = {k: art[k] for k in ("article_id", "published_date", "publication",
                                       "headline", "body", "mentioned_entity_as_written")}
        run = attempt(llm, lambda: self.rules_decision(art), spec=spec,
                      task=f"Assess this article:\n{_json(article)}", tools=tools,
                      # the other articles are context, not input: a cached decision is
                      # reused when later demo articles are added
                      cache_payload={"article": article, "registry": self.candidates})
        return {**run["result"], "agent": _summary(run)}


def _json(obj) -> str:
    import json
    return json.dumps(obj, indent=2)


def _summary(run: dict) -> dict:
    return {k: run[k] for k in ("mode", "turns", "cached", "trace", "error")}


def assess(loader: Loader, llm, store) -> dict[str, dict]:
    desk = NewsDesk(loader)
    buyers = desk.buyers
    best: dict[str, dict] = {}

    def offer(buyer_id: str, value: float, rec: dict) -> None:
        if value > best.get(buyer_id, {}).get("value", -1.0):
            best[buyer_id] = {"value": value, **rec}

    for art in desk.articles:
        d = desk.decide(art, llm)
        age = (AS_OF - parse_date(art["published_date"],
                                  what=f"article {art['article_id']} published_date")).days

        if d["kind"] == "none":
            store.add(Evidence(
                kind="resolution", buyer_id="",
                detail=f"refused '{art['mentioned_entity_as_written']}' - {d['reason']}",
                source=art["article_id"], date=art["published_date"],
                data={"resolved": False, "mention": art["mentioned_entity_as_written"],
                      "headline": art["headline"], "reason": d["reason"], "agent": d["agent"]},
            ))
            continue

        sev = d["severity"]
        if d["kind"] == "buyer":
            bid = d["id"]
            value = NEWS_BASE[sev] * decay(age)
            store.add(Evidence(
                kind="news", buyer_id=bid,
                detail=f"severity {sev} ({d['category']}): {art['headline']}",
                source=art["article_id"], date=art["published_date"],
                data={"severity": sev, "category": d["category"], "age_days": age,
                      "base": NEWS_BASE[sev], "decayed": round(value, 2),
                      "entity": d["name"], "via_parent": False,
                      "publication": art["publication"], "headline": art["headline"],
                      "reason": d["reason"], "agent": d["agent"]},
            ))
            offer(bid, value, {"severity": sev, "category": d["category"],
                               "article_id": art["article_id"], "age_days": age,
                               "headline": art["headline"], "via_parent": False,
                               "parent_name": None})
        else:
            sub_sev = PARENT_STEP_DOWN[sev]
            for bid in desk.subs.get(d["id"], []):
                value = NEWS_BASE[sub_sev] * decay(age)
                store.add(Evidence(
                    kind="parent", buyer_id=bid,
                    detail=(f"parent {d['name']} - severity {sev} ({d['category']}), "
                            f"counted at severity {sub_sev} for {buyers[bid]['short_name']}"),
                    source=art["article_id"], date=art["published_date"],
                    data={"severity": sub_sev, "parent_severity": sev,
                          "category": d["category"], "age_days": age,
                          "base": NEWS_BASE[sub_sev], "decayed": round(value, 2),
                          "entity": d["name"], "via_parent": True,
                          "publication": art["publication"], "headline": art["headline"],
                          "reason": d["reason"], "agent": d["agent"]},
                ))
                offer(bid, value, {"severity": sub_sev, "category": d["category"],
                                   "article_id": art["article_id"], "age_days": age,
                                   "headline": art["headline"], "via_parent": True,
                                   "parent_name": d["name"]})

    for b in loader.buyers():
        best.setdefault(b["buyer_id"], {"value": 0.0, "severity": 0, "category": None,
                                        "article_id": None, "age_days": None,
                                        "headline": None, "via_parent": False,
                                        "parent_name": None})
    return best
