"""The agent loop shared by all four agents.

Each agent is defined in agents/<name>.md (definition.py): its system prompt, model,
turn limit, and which tools it may use. Code supplies the tool implementations - read-
only views over the engine's own data - and the `submit_*` check. Claude decides which
tools to call, in what order, and when it has seen enough; the run ends when it calls
the submit tool.

Every run is cached to disk by content hash (same as llm.py), so a re-run with the
same inputs replays the recorded conclusion and costs nothing. Any failure -
refusal, truncation, no submission, API error - raises AgentError and the caller
falls back to its rule-based path for that one item.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any, Callable

from ..settings import TRACE_PREVIEW_CHARS
from .definition import AgentSpec, DefinitionError



class AgentError(RuntimeError):
    """The agent did not reach a usable conclusion."""


@dataclass
class Tool:
    """A tool's implementation. Its description comes from the agent's .md file."""
    name: str
    properties: dict
    fn: Callable[..., Any]

    def spec(self, description: str) -> dict:
        return {
            "name": self.name,
            "description": description,
            "strict": True,
            "input_schema": {"type": "object", "properties": self.properties,
                             "required": list(self.properties), "additionalProperties": False},
        }


def _dump(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, default=str)


def _offered(spec: AgentSpec, tools: list[Tool]) -> list[Tool]:
    """The implementations the .md file lists, in its order."""
    impls = {t.name: t for t in tools}
    unknown = [n for n in spec.tools if n not in impls]
    if unknown:
        raise DefinitionError(f"{spec.path.name} lists {unknown}, which the {spec.name} agent "
                              f"does not implement; available: {sorted(impls)}")
    return [impls[n] for n in spec.tools]


def run_agent(llm, *, spec: AgentSpec, task: str, tools: list[Tool],
              cache_payload: dict) -> dict:
    """Run one agent to completion. Returns {"result", "trace", "turns", "cached"}.

    The submit tool's fn validates the submission and returns the accepted result, or
    raises ValueError with a message the agent sees and can correct.
    """
    from ..llm import _key                                   # shared content hash

    offered = _offered(spec, tools)
    submit = next(t for t in offered if t.name == spec.submit)
    # the definition is part of the key, so editing an agent's .md re-runs it
    key = _key(llm.name, f"agent:{spec.name}", {
        "model": spec.model, "effort": spec.effort, "max_tokens": spec.max_tokens,
        "guardrails": spec.guardrails, "system": spec.system, "tools": spec.tools,
        "task": task, "data": cache_payload})
    cached = llm.cache.get(key)
    if cached is not None:
        return {**cached, "cached": True}
    if getattr(llm, "disabled", False):
        raise AgentError("Claude unavailable for this run")

    by_name = {t.name: t for t in offered if t is not submit}
    specs = [t.spec(spec.tools[t.name]) for t in offered]
    messages: list[dict] = [{"role": "user", "content": task}]
    trace: list[dict] = []
    nudged = False

    for turn in range(1, spec.max_turns + 1):
        resp = llm.create(model=spec.model, effort=spec.effort, system=spec.system,
                          tools=specs, messages=messages, max_tokens=spec.max_tokens)
        if resp.stop_reason == "refusal":
            raise AgentError("model declined the request")
        if resp.stop_reason == "max_tokens":
            raise AgentError("response truncated at max_tokens")

        calls = [b for b in resp.content if b.type == "tool_use"]
        messages.append({"role": "assistant", "content": resp.content})

        if not calls:
            if nudged:
                raise AgentError("agent stopped without submitting")
            nudged = True
            messages.append({"role": "user",
                             "content": f"Call {submit.name} with your conclusion."})
            continue

        results = []
        for call in calls:
            args = dict(call.input or {})
            if call.name == submit.name:
                called = {t["tool"] for t in trace if "result" in t}
                skipped = [t for t in spec.guardrails["required_before_submit"]
                           if t not in called]
                try:
                    if skipped:
                        raise ValueError(f"call {', '.join(skipped)} before submitting")
                    accepted = submit.fn(**args)
                except (TypeError, ValueError) as exc:
                    trace.append({"tool": call.name, "input": args, "error": str(exc)})
                    results.append({"type": "tool_result", "tool_use_id": call.id,
                                    "content": f"Rejected: {exc}", "is_error": True})
                    continue
                trace.append({"tool": call.name, "input": args})
                out = {"result": accepted, "trace": trace, "turns": turn}
                llm.cache.put(key, out)
                return {**out, "cached": False}

            tool = by_name.get(call.name)
            try:
                if tool is None:
                    raise ValueError(f"unknown tool {call.name!r}")
                text = _dump(tool.fn(**args))
                is_error = False
            except (TypeError, ValueError, KeyError) as exc:
                text, is_error = f"Error: {exc}", True
            if not is_error:
                trace.append({"tool": call.name, "input": args,
                              "result": text[:TRACE_PREVIEW_CHARS]})
            else:
                trace.append({"tool": call.name, "input": args, "error": text})
            results.append({"type": "tool_result", "tool_use_id": call.id,
                            "content": text, **({"is_error": True} if is_error else {})})

        messages.append({"role": "user", "content": results})

    raise AgentError(f"no submission after {spec.max_turns} turns")


def attempt(llm, rules: Callable[[], Any], *, spec: AgentSpec, **agent_kwargs) -> dict:
    """Run the agent when Claude is available; otherwise, or on failure, the rules.

    Returns {"mode", "result", "trace", "turns", "cached", "error"} where mode is
    "agent", "rules" (no Claude configured), "disabled" (turned off in settings.py) or
    "rules-after-error".
    """
    _offered(spec, agent_kwargs["tools"])          # a broken .md fails on every path
    if not spec.enabled:
        return {"mode": "disabled", "result": rules(), "trace": [], "turns": 0,
                "cached": False, "error": None}
    if not getattr(llm, "agentic", False):
        return {"mode": "rules", "result": rules(), "trace": [], "turns": 0,
                "cached": False, "error": None}
    try:
        run = run_agent(llm, spec=spec, **agent_kwargs)
        return {"mode": "agent", "error": None, **run}
    except (AgentError, *llm.api_errors) as exc:
        llm.degraded += 1
        if llm.degraded == 1 or not getattr(llm, "disabled", False):   # say "no Claude" once
            print(f"  [agent:{spec.name}] fell back to rules: {exc}", file=sys.stderr)
        return {"mode": "rules-after-error", "result": rules(), "trace": [], "turns": 0,
                "cached": False, "error": str(exc)}
