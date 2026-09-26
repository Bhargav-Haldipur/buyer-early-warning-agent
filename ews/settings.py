"""Per-agent settings: model, effort, limits and guardrails. Edit here.

What each agent is told lives in agents/<name>.md. How it runs, and what it is
allowed to submit, lives here. Every value is checked when the agent loads; a typo
or an out-of-range value stops the run with a clear error rather than being ignored.

Guardrails apply when an agent runs on Claude. They decide whether a submission is
accepted; a rejected submission goes back to the agent with the reason, so it can
look again. The rule-based fallback does not need them. None of them can let an
agent set the risk score - that is always the formula in ews/config.py.
"""

# Effort levels the Claude API accepts on the models below. Lower effort means fewer
# tool calls and less thinking - cheaper and faster, less thorough.
import os

EFFORTS = ("low", "medium", "high", "xhigh", "max")

AGENTS = {
    "payment": {
        "enabled": True,              # False: always use the rule-based review
        "model": "claude-sonnet-5",
        "effort": "high",
        "max_turns": 12,              # model calls before the run gives up and falls back
        "max_tokens": 16000,          # per model call
        "guardrails": {
            # tools the agent must have called before submit_* is accepted
            "required_before_submit": ["get_open_invoices"],
            # the worst open invoice it reports must be the ledger's own
            "must_match_ledger": True,
            "max_concerns": 5,
        },
    },
    "news": {
        "enabled": True,
        "model": "claude-sonnet-5",
        "effort": "high",
        "max_turns": 12,
        "max_tokens": 16000,
        "guardrails": {
            "required_before_submit": ["search_entities"],
            # a matched entity id must have come back from search_entities or get_entity
            # in this run - the agent cannot guess an id it has not looked up
            "entity_must_be_looked_up": True,
            # severities the agent may submit; must be a subset of 0, 3, 4, 5
            "allowed_severities": [0, 3, 4, 5],
        },
    },
    "adjudicator": {
        "enabled": True,
        "model": "claude-opus-5",
        "effort": "high",
        "max_turns": 12,
        "max_tokens": 16000,
        "guardrails": {
            "required_before_submit": ["get_evidence"],
            # every concern must cite an evidence id recorded for this buyer
            "require_real_citations": True,
            # every number in the rationale and concerns must appear in the data
            "verify_figures": True,
            "max_concerns": 5,
        },
    },
    "casefile": {
        "enabled": True,
        "model": "claude-opus-5",
        "effort": "high",
        "max_turns": 12,
        "max_tokens": 16000,
        "guardrails": {
            "required_before_submit": ["get_verdict", "get_limits"],
            # every number in the draft must appear in the data (D10)
            "verify_figures": True,
            # how far a written figure may sit from the data value and still match
            "figure_tolerance": 0.051,
            # bands that get an agent-written case file; the rest get the template
            "run_for_bands": ["Watch", "High Risk"],
        },
    },
}

# On Opus models, re-run a request Claude declines on Anthropic's recommended
# fallback model instead of failing the agent (server-side, one call).
# Hard ceiling on model calls in one engine run. The agents are sequential, so this
# is a spend cap, not a rate limit: once it is hit the LLM switches itself off and
# every remaining item falls back to its rule-based path. A full pass is ~94 agent
# runs; most submit in 2-5 turns, so 400 leaves headroom without letting a pathological
# loop run up a bill.
MAX_MODEL_CALLS = 400

# Retries the SDK may make per call (429s and 5xx, with backoff). Each retry is a
# billable call, so this is deliberately low.
MAX_RETRIES = 2

# Published per-million-token prices, for turning usage into a number on the screen.
# An unlisted model falls back to the most expensive row, so a new model is never
# reported as cheaper than it is.
PRICING = {
    "claude-opus-5":    (5.0, 25.0),
    "claude-opus-4-8":  (5.0, 25.0),
    "claude-sonnet-5":  (2.0, 10.0),
    "claude-haiku-4-5": (1.0,  5.0),
}
DEFAULT_PRICE = (10.0, 50.0)

# A call budget is a crude proxy for spend: one call with 80k input tokens costs far
# more than fifty with 1.5k. This caps the tokens as well.
MAX_MODEL_TOKENS = 4_000_000

REFUSAL_FALLBACK = True

# Characters of each tool result kept in the trace shown on the dashboard.
TRACE_PREVIEW_CHARS = 400


# --------------------------------------------------------------------------
# validation - nothing to edit below this line
# --------------------------------------------------------------------------
_COMMON = {"enabled": bool, "model": str, "effort": str, "max_turns": int,
           "max_tokens": int, "guardrails": dict}
_GUARDRAILS = {
    "payment": {"required_before_submit": list, "must_match_ledger": bool,
                "max_concerns": int},
    "news": {"required_before_submit": list, "entity_must_be_looked_up": bool,
             "allowed_severities": list},
    "adjudicator": {"required_before_submit": list, "require_real_citations": bool,
                    "verify_figures": bool, "max_concerns": int},
    "casefile": {"required_before_submit": list, "verify_figures": bool,
                 "figure_tolerance": float, "run_for_bands": list},
}


class SettingsError(ValueError):
    """ews/settings.py holds a value the engine cannot use."""


def apply_overrides(agents: str | None = None, max_calls: int | None = None) -> None:
    """Narrow which agents use Claude, and cap the run's model calls.

    Read from EWS_AGENTS / EWS_MAX_CALLS as well as from arguments, because an
    override that only one entry point honours is worse than none: `--agents news`
    used to apply to `ews.run` and silently not to the harness, which then ran every
    agent - including the expensive ones - on the default settings.
    """
    global MAX_MODEL_CALLS
    agents = agents if agents is not None else os.environ.get("EWS_AGENTS")
    if agents is not None:
        wanted = {a.strip() for a in agents.split(",") if a.strip()}
        unknown = wanted - set(AGENTS)
        if unknown:
            raise SettingsError(f"unknown agent(s): {sorted(unknown)}; known: {sorted(AGENTS)}")
        for name, spec in AGENTS.items():
            spec["enabled"] = name in wanted
    raw = max_calls if max_calls is not None else os.environ.get("EWS_MAX_CALLS")
    if raw is not None:
        try:
            MAX_MODEL_CALLS = int(raw)
        except (TypeError, ValueError) as exc:
            raise SettingsError(f"EWS_MAX_CALLS must be an integer, got {raw!r}") from exc
    limits()


def enabled_agents() -> list[str]:
    return sorted(n for n, s in AGENTS.items() if s["enabled"])


def _check(where: str, got: dict, schema: dict) -> None:
    missing = sorted(set(schema) - set(got))
    unknown = sorted(set(got) - set(schema))
    if missing or unknown:
        raise SettingsError(f"{where}: missing {missing}, unknown {unknown}")
    for key, typ in schema.items():
        value = got[key]
        if typ is float:                  # a whole number is a fine tolerance
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        elif typ is int:                  # True is an int in Python; not here
            ok = isinstance(value, int) and not isinstance(value, bool)
        else:
            ok = isinstance(value, typ)
        if not ok:
            raise SettingsError(f"{where}.{key} must be {typ.__name__}, got {value!r}")


def limits() -> None:
    """The spend controls are settings too, and a bad value must fail loudly."""
    for label, value, floor in (("MAX_MODEL_CALLS", MAX_MODEL_CALLS, 1),
                                ("MAX_MODEL_TOKENS", MAX_MODEL_TOKENS, 1),
                                ("MAX_RETRIES", MAX_RETRIES, 0)):
        if isinstance(value, bool) or not isinstance(value, int) or value < floor:
            raise SettingsError(f"{label} must be an int >= {floor}, got {value!r}")


def agent(name: str) -> dict:
    """The validated settings for one agent."""
    limits()
    if name not in AGENTS:
        raise SettingsError(f"no settings for agent {name!r}; known: {sorted(AGENTS)}")
    s = AGENTS[name]
    _check(f"AGENTS[{name!r}]", s, _COMMON)
    _check(f"AGENTS[{name!r}]['guardrails']", s["guardrails"], _GUARDRAILS[name])
    if not s["model"].startswith("claude-"):
        raise SettingsError(f"AGENTS[{name!r}]['model'] must be a Claude model id")
    if s["effort"] not in EFFORTS:
        raise SettingsError(f"AGENTS[{name!r}]['effort'] must be one of {EFFORTS}")
    if s["max_turns"] < 1 or s["max_tokens"] < 256:
        raise SettingsError(f"AGENTS[{name!r}]: max_turns must be >= 1, max_tokens >= 256")
    g = s["guardrails"]
    if "allowed_severities" in g and (not g["allowed_severities"]
                                      or not set(g["allowed_severities"]) <= {0, 3, 4, 5}):
        raise SettingsError("news allowed_severities must be a non-empty subset of 0, 3, 4, 5")
    if "run_for_bands" in g and not set(g["run_for_bands"]) <= {"Healthy", "Watch", "High Risk"}:
        raise SettingsError("casefile run_for_bands may only name Healthy, Watch, High Risk")
    if g.get("max_concerns", 1) < 0 or g.get("figure_tolerance", 0) < 0:
        raise SettingsError(f"AGENTS[{name!r}]: limits must not be negative")
    return s
