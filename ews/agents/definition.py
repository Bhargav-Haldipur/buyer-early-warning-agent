"""Agent definitions live in agents/*.md, not in code.

Each file is Markdown with a small frontmatter block:

    ---
    name: news
    title: News Intelligence
    description: One line for the dashboard.
    tools:
      - search_entities: What the tool does, as the agent will read it.
      - submit_assessment: ...
    ---
    The system prompt, in plain Markdown.

The body is the agent's system prompt. `{w_payment}`-style placeholders are filled
from config so a threshold is written once. The tools listed are the only ones the
agent is offered, described in the file's words; their implementations and input
schemas stay in code, and exactly one of them must be a `submit_*` tool.

Model, effort, limits and guardrails come from ews/settings.py and are merged in here,
so an AgentSpec is everything one agent run needs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .. import config, settings

AGENTS_DIR = Path(__file__).resolve().parent.parent.parent / "agents"

PLACEHOLDERS = {
    "w_payment": config.W_PAYMENT, "w_news": config.W_NEWS,
    "band_watch": f"{config.BAND_WATCH:g}", "band_high": f"{config.BAND_HIGH:g}",
}
REQUIRED = ("name", "title", "description", "tools")
MOVED = ("model", "max_turns", "effort", "max_tokens")      # these belong in settings.py


class DefinitionError(ValueError):
    """An agent's .md file is malformed. Raised loudly - never a silent fallback."""


@dataclass(frozen=True)
class AgentSpec:
    name: str
    title: str
    description: str
    tools: dict[str, str]          # tool name -> description, in file order
    system: str
    path: Path
    # from ews/settings.py
    enabled: bool
    model: str
    effort: str
    max_turns: int
    max_tokens: int
    guardrails: dict

    @property
    def submit(self) -> str:
        return next(t for t in self.tools if t.startswith("submit_"))


def _frontmatter(text: str, path: Path) -> tuple[dict, str]:
    m = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n(.*)\Z", text, re.S)
    if not m:
        raise DefinitionError(f"{path.name}: must start with a --- frontmatter block ---")
    meta: dict = {}
    current = None
    for n, line in enumerate(m.group(1).splitlines(), 2):
        if not line.strip():
            continue
        item = re.match(r"\s+-\s+([\w-]+)\s*:\s*(.+)", line)
        if item and current == "tools":
            meta["tools"][item.group(1)] = item.group(2).strip()
            continue
        kv = re.match(r"([\w-]+)\s*:\s*(.*)", line)
        if not kv:
            raise DefinitionError(f"{path.name}:{n}: cannot read {line.strip()!r}")
        current, value = kv.group(1), kv.group(2).strip()
        meta[current] = {} if current == "tools" else value
    return meta, m.group(2)


def _fill(body: str, path: Path) -> str:
    def sub(m: re.Match) -> str:
        if m.group(1) not in PLACEHOLDERS:
            raise DefinitionError(f"{path.name}: unknown placeholder {{{m.group(1)}}}; "
                                  f"known: {sorted(PLACEHOLDERS)}")
        return str(PLACEHOLDERS[m.group(1)])
    return re.sub(r"\{(\w+)\}", sub, body).strip() + "\n"


def load(name: str) -> AgentSpec:
    """Read agents/<name>.md. Re-read on every call, so edits apply to the next run."""
    path = AGENTS_DIR / f"{name}.md"
    if not path.is_file():
        raise DefinitionError(f"no agent definition at {path}")
    meta, body = _frontmatter(path.read_text(encoding="utf-8"), path)
    missing = [k for k in REQUIRED if not meta.get(k)]
    if missing:
        raise DefinitionError(f"{path.name}: missing {missing}")
    if meta["name"] != name:
        raise DefinitionError(f"{path.name}: name is {meta['name']!r}, expected {name!r}")
    moved = [k for k in MOVED if k in meta]
    if moved:
        raise DefinitionError(f"{path.name}: {moved} are set in ews/settings.py, not here")
    submits = [t for t in meta["tools"] if t.startswith("submit_")]
    if len(submits) != 1:
        raise DefinitionError(f"{path.name}: needs exactly one submit_* tool, found {submits}")
    s = settings.agent(name)
    required = s["guardrails"]["required_before_submit"]
    unlisted = [t for t in required if t not in meta["tools"] or t in submits]
    if unlisted:
        raise settings.SettingsError(
            f"AGENTS[{name!r}] requires {unlisted} before submit, but {path.name} does not "
            f"offer them as read tools; offered: {list(meta['tools'])}")
    return AgentSpec(name=name, title=meta["title"], description=meta["description"],
                     tools=meta["tools"], system=_fill(body, path), path=path,
                     enabled=s["enabled"], model=s["model"], effort=s["effort"],
                     max_turns=s["max_turns"], max_tokens=s["max_tokens"],
                     guardrails=s["guardrails"])
