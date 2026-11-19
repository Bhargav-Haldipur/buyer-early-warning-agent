"""Load secrets and per-machine values from .env at the project root.

    cp .env.example .env        # then put your key in .env

.env is git-ignored: an API key typed into it never reaches the repository.
Standard library only - the project runs without installing anything, and this must
not change that.

A variable already set in the shell wins over the file, so a one-off
`ANTHROPIC_API_KEY=... python -m ews.run` still works, and the test suite's own
settings (tests/__init__.py) cannot be overridden by a developer's .env.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / ".env"
_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def parse(text: str) -> dict[str, str]:
    """KEY=value lines. Blank lines and # comments are skipped; quotes are optional."""
    out: dict[str, str] = {}
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE.match(line)
        if not m:
            raise ValueError(f".env line {n} is not KEY=value: {raw!r}")
        key, value = m.groups()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]                      # quoted: keep everything inside
        else:
            value = re.sub(r"\s+#.*$", "", value)    # unquoted: drop a trailing comment
        out[key] = value
    return out


def load(path: Path | None = None) -> list[str]:
    """Set every variable from .env that the environment does not already have.

    Returns the names it set (never the values). A missing file is not an error.
    """
    path = path or PATH
    if not path.exists():
        return []
    applied = []
    for key, value in parse(path.read_text(encoding="utf-8")).items():
        if value and key not in os.environ:
            os.environ[key] = value
            applied.append(key)
    return applied
