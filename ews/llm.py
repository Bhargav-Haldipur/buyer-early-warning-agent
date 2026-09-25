"""One interface, two implementations (D11).

  ClaudeLLM    - the real thing, needs `pip install anthropic` and an API key
  FallbackLLM  - deterministic, always available, used offline and by every gate

Every response is cached to disk by content hash, so a demo re-run costs nothing
and needs no network. A Claude call that fails for any reason degrades to the
deterministic answer rather than taking the demo down with it.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

from . import config

CACHE_DIR = Path(__file__).resolve().parent.parent / "out" / ".llm_cache"

# --------------------------------------------------------------------------
# entity normalisation — shared by the fallback matcher and the Claude prompt
# --------------------------------------------------------------------------
# Dropped before comparison: legal forms, and "Inds." which appears in genuine
# mentions ("Mahanadi Inds.") as a generic stand-in for the real business word.
GENERIC_TOKENS = frozenset(
    {"PVT", "PRIVATE", "LTD", "LIMITED", "LLP", "INC", "CO", "COMPANY", "CORP", "INDS"}
)


def tokens(name: str) -> list[str]:
    raw = re.sub(r"[^A-Za-z0-9 ]", " ", name).upper().split()
    return [t for t in raw if t not in GENERIC_TOKENS]


def strict_resolve(mention: str, candidates: list[dict]) -> dict | None:
    """The reluctant rule from D4.

    The brand token must match exactly one candidate, and every remaining
    distinguishing token in the mention must appear in that candidate's own
    name. Anything else refuses.

    'Arcline Inds.'        -> Arcline Fabricators Limited   (no distinguishing tokens)
    'Arcline Media Pvt Ltd'-> refused ('MEDIA' is not in the name)
    """
    tk = tokens(mention)
    if not tk:
        return None
    brand, rest = tk[0], set(tk[1:])
    hits = [c for c in candidates if tokens(c["name"]) and tokens(c["name"])[0] == brand]
    if len(hits) != 1:            # unknown brand, or ambiguous between two entities
        return None
    cand = hits[0]
    if not rest.issubset(set(tokens(cand["name"]))):
        return None
    return cand


# --------------------------------------------------------------------------
# deterministic severity grading
# --------------------------------------------------------------------------
# (regex, category, severity) — first match wins. Severities follow the dataset's
# own category->severity mapping.
_GRADE_RULES: list[tuple[str, str, int]] = [
    (r"protest over delayed wages|delayed wages|unpaid salaries", "wage_delay", 5),
    (r"restructuring talks|restructure .*debt|lender.* restructuring", "parent_distress", 5),
    (r"fallen behind on payments|recovery notice|unpaid invoices|vendors say", "vendor_payment_delay", 4),
    (r"reviewing exposure|lenders review|review .*exposure", "lender_review", 4),
    (r"scales back|scaling back|halts production|capacity cut", "capacity_cut", 3),
    (r"legal notice|winding.up petition|insolvency petition", "legal_notice", 3),
    (r"appoints|appointment of", "appointment", 0),
    (r"commissions new line|new facility|expansion", "expansion", 0),
    (r"tie.up|distribution arrangement|partnership", "tie_up", 0),
    (r"higher volumes|volume growth|reports higher", "volumes", 0),
]


def keyword_grade(article: dict) -> dict:
    text = f"{article.get('headline','')} {article.get('body','')}".lower()
    for pattern, category, severity in _GRADE_RULES:
        if re.search(pattern, text):
            return {"severity": severity, "category": category,
                    "reason": f"matched '{category}' language"}
    return {"severity": 0, "category": "other", "reason": "no distress language found"}


# --------------------------------------------------------------------------
# cache
# --------------------------------------------------------------------------
def _key(impl: str, task: str, payload: dict) -> str:
    blob = json.dumps({"impl": impl, "task": task, "payload": payload}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


class _Cache:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        if enabled:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def get(self, key: str):
        if not self.enabled:
            return None
        p = CACHE_DIR / f"{key}.json"
        return json.loads(p.read_text()) if p.exists() else None

    def put(self, key: str, value) -> None:
        if self.enabled:
            (CACHE_DIR / f"{key}.json").write_text(json.dumps(value, indent=2))


# --------------------------------------------------------------------------
# implementations
# --------------------------------------------------------------------------
class FallbackLLM:
    name = "fallback"

    def __init__(self, cache: bool = True):
        self.cache = _Cache(cache)
        self.calls = 0

    def resolve(self, article: dict, candidates: list[dict]) -> dict:
        self.calls += 1
        hit = strict_resolve(article["mentioned_entity_as_written"], candidates)
        if hit is None:
            return {"kind": "none", "id": "", "name": "",
                    "reason": "no candidate whose own name contains every distinguishing token"}
        return {"kind": hit["kind"], "id": hit["id"], "name": hit["name"],
                "reason": "brand token matched one candidate and all remaining tokens are in its name"}

    def grade(self, article: dict, entity_name: str) -> dict:
        self.calls += 1
        return keyword_grade(article)

    def write_case_file(self, facts: dict) -> str | None:
        return None      # signals casefile.py to render the template


class ClaudeLLM:
    """Wraps the official SDK. Any failure degrades to FallbackLLM for that call."""
    name = "claude"

    RESOLVE_SCHEMA = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["buyer", "parent", "none"]},
            "id": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["kind", "id", "reason"],
        "additionalProperties": False,
    }
    GRADE_SCHEMA = {
        "type": "object",
        "properties": {
            "severity": {"type": "integer", "enum": [0, 3, 4, 5]},
            "category": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["severity", "category", "reason"],
        "additionalProperties": False,
    }

    def __init__(self, cache: bool = True):
        import anthropic                                   # noqa: F401  (import error is caught by get_llm)
        self._anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.cache = _Cache(cache)
        self.fallback = FallbackLLM(cache=False)
        self.calls = 0
        self.degraded = 0

    # -- plumbing ---------------------------------------------------------
    def _json_call(self, task: str, payload: dict, system: str, prompt: str, schema: dict) -> dict:
        key = _key(self.name, task, payload)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        self.calls += 1
        resp = self.client.messages.create(
            model=config.MODEL_GRADING,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        )
        text = next(b.text for b in resp.content if b.type == "text")
        out = json.loads(text)
        self.cache.put(key, out)
        return out

    # -- the two gated passes ---------------------------------------------
    def resolve(self, article: dict, candidates: list[dict]) -> dict:
        payload = {"mention": article["mentioned_entity_as_written"],
                   "headline": article["headline"], "body": article["body"],
                   "candidates": [{"id": c["id"], "name": c["name"], "kind": c["kind"],
                                   "sector": c.get("sector", ""), "city": c.get("city", "")}
                                  for c in candidates]}
        system = (
            "You match a company named in a news article to a list of known entities for a "
            "credit insurer. You are deliberately RELUCTANT: a wrong match puts a healthy "
            "company on a risk watchlist.\n"
            "Match only if the leading brand word matches AND every other distinguishing word "
            "in the mention also appears in that entity's own registered name. Abbreviations of "
            "legal form (Pvt, Ltd, Limited, LLP) and the generic 'Inds.' may be ignored.\n"
            "A different line of business is decisive: 'Arcline Media Pvt Ltd' is NOT "
            "'Arcline Fabricators Limited'. If in any doubt, answer none."
        )
        prompt = json.dumps(payload, indent=2)
        try:
            out = self._json_call("resolve", payload, system, prompt, self.RESOLVE_SCHEMA)
        except Exception as exc:                                     # noqa: BLE001
            self.degraded += 1
            print(f"  [llm] resolve degraded to fallback: {exc}", file=sys.stderr)
            return self.fallback.resolve(article, candidates)
        if out["kind"] == "none":
            return {"kind": "none", "id": "", "name": "", "reason": out["reason"]}
        match = next((c for c in candidates if c["id"] == out["id"]), None)
        if match is None:        # hallucinated id — treat as a refusal
            self.degraded += 1
            return {"kind": "none", "id": "", "name": "",
                    "reason": f"model returned unknown id {out['id']!r}; refused"}
        return {"kind": match["kind"], "id": match["id"], "name": match["name"],
                "reason": out["reason"]}

    def grade(self, article: dict, entity_name: str) -> dict:
        payload = {"entity": entity_name, "headline": article["headline"], "body": article["body"]}
        system = (
            "You grade a news article about a company for a credit insurer's early-warning "
            "system. Return exactly one severity:\n"
            "  0 - neutral or positive (appointments, expansion, tie-ups, higher volumes)\n"
            "  3 - mild negative (capacity cut, legal notice, contract loss)\n"
            "  4 - moderate negative (unpaid vendors, lenders reviewing exposure)\n"
            "  5 - severe negative (unpaid wages, debt restructuring, insolvency)\n"
            "Grade what the article says about THIS company only."
        )
        try:
            return self._json_call("grade", payload, system, json.dumps(payload, indent=2),
                                   self.GRADE_SCHEMA)
        except Exception as exc:                                     # noqa: BLE001
            self.degraded += 1
            print(f"  [llm] grade degraded to fallback: {exc}", file=sys.stderr)
            return self.fallback.grade(article, entity_name)

    # -- case file ---------------------------------------------------------
    def write_case_file(self, facts: dict) -> str | None:
        key = _key(self.name, "casefile", facts)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        system = (
            "You write a short case file for a trade credit underwriter.\n"
            "CRITICAL: use ONLY the numbers given to you. Never compute, round differently, "
            "estimate or invent a figure. Any number you write that is not in the input will "
            "cause your text to be discarded.\n"
            "Four short paragraphs, no headings, no bullet points: how the buyer is doing; "
            "why it is in this band; what the recommended limit action is; what would lift it."
        )
        try:
            self.calls += 1
            resp = self.client.messages.create(
                model=config.MODEL_CASEFILE,
                max_tokens=1200,
                system=system,
                messages=[{"role": "user", "content": json.dumps(facts, indent=2)}],
            )
            text = "".join(b.text for b in resp.content if b.type == "text").strip()
        except Exception as exc:                                     # noqa: BLE001
            self.degraded += 1
            print(f"  [llm] case file degraded to template: {exc}", file=sys.stderr)
            return None
        self.cache.put(key, text)
        return text


def get_llm(cache: bool = True):
    """EWS_LLM=claude|fallback. Defaults to Claude when it is actually usable."""
    want = os.environ.get("EWS_LLM", "auto").lower()
    if want == "fallback":
        return FallbackLLM(cache)
    try:
        llm = ClaudeLLM(cache)
        return llm
    except Exception as exc:                                         # noqa: BLE001
        if want == "claude":
            raise RuntimeError(f"EWS_LLM=claude but the Claude client is unavailable: {exc}") from exc
        return FallbackLLM(cache)
