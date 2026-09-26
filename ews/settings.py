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


def agent(name: str) -> dict:
    """The validated settings for one agent."""
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
