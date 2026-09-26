"""One interface, two implementations (D11).

  ClaudeLLM    - drives the autonomous agents (agents/runtime.py); needs
                 `pip install anthropic` and an API key
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
    agentic = False

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
    """Transport for the agent loop in agents/runtime.py.

    Holds the SDK client and the disk cache. The first authentication failure
    disables it for the rest of the run, so a missing key costs one failed call
    rather than one per article.
    """
    name = "claude"
    agentic = True

    def __init__(self, cache: bool = True):
        import anthropic                                   # import error is caught by get_llm
        self._anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.api_errors = (anthropic.APIError,)
        self.cache = _Cache(cache)
        self.calls = 0
        self.degraded = 0
        self.disabled = False

    def create(self, *, model: str, effort: str, **params):
        from .settings import REFUSAL_FALLBACK
        self.calls += 1
        params["output_config"] = {"effort": effort}
        try:
            if REFUSAL_FALLBACK and model.startswith("claude-opus-5"):
                # server-side refusal fallback: a declined request is re-run on
                # Anthropic's recommended model instead of failing the agent
                return self.client.beta.messages.create(
                    model=model, betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default", **params)
            return self.client.messages.create(model=model, **params)
        except self._anthropic.AuthenticationError:
            self.disabled = True
            raise
        except TypeError as exc:
            # the SDK raises TypeError when it finds no credentials at all
            if "authentication" not in str(exc).lower():
                raise
            self.disabled = True
            from .agents.runtime import AgentError
            raise AgentError(f"no Anthropic credentials: {exc}") from exc


def _has_credentials() -> bool:
    """Whether the SDK can authenticate: a key or token, a federation rule, or a profile."""
    if any(os.environ.get(v) for v in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
                                       "ANTHROPIC_FEDERATION_RULE_ID", "ANTHROPIC_PROFILE")):
        return True
    return (Path.home() / ".config" / "anthropic").is_dir()


def get_llm(cache: bool = True):
    """EWS_LLM=claude|fallback. Defaults to Claude when it is actually usable."""
    want = os.environ.get("EWS_LLM", "auto").lower()
    if want == "fallback" or (want == "auto" and not _has_credentials()):
        return FallbackLLM(cache)
    try:
        llm = ClaudeLLM(cache)
        return llm
    except Exception as exc:                                         # noqa: BLE001
        if want == "claude":
            raise RuntimeError(f"EWS_LLM=claude but the Claude client is unavailable: {exc}") from exc
        return FallbackLLM(cache)
