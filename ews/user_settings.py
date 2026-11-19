"""settings.json - the switches a person edits, at the project root.

    {
      "news": {
        "auto_refresh": false,        # fetch and re-score on a timer (SBI book)
        "refresh_minutes": 15,        # how often, while auto_refresh is on
        "lookback_days": 180,         # how far back each fetch looks
        "stories_per_company": 12     # most press stories kept per company
      }
    }

The file is the source of truth. The dashboard re-reads it every few seconds, so an
edit takes effect without a restart, and the dashboard's own switch writes back to it
- the two never disagree. A missing file means the defaults; a broken one is reported
and the last good values stay in force, never silently replaced.

(Agent models, effort and guardrails are code-level settings and live in
ews/settings.py; this file is for switches.)
"""
from __future__ import annotations

import json
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "settings.json"

DEFAULTS = {
    "news": {
        "auto_refresh": False,
        "refresh_minutes": 15,
        "lookback_days": 180,
        "stories_per_company": 12,
    }
}

# key -> (type, low, high); bounds are inclusive
_RULES = {
    "auto_refresh": (bool, None, None),
    "refresh_minutes": (int, 1, 1440),
    "lookback_days": (int, 1, 730),
    "stories_per_company": (int, 1, 100),
}


class SettingsFileError(ValueError):
    """settings.json exists but cannot be used as written."""


def _validate(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise SettingsFileError("settings.json must hold a JSON object")
    unknown_sections = set(raw) - set(DEFAULTS)
    if unknown_sections:
        raise SettingsFileError(f"unknown section(s): {sorted(unknown_sections)}; "
                                f"known: {sorted(DEFAULTS)}")
    news = raw.get("news", {})
    if not isinstance(news, dict):
        raise SettingsFileError('"news" must be an object')
    unknown = set(news) - set(_RULES)
    if unknown:
        raise SettingsFileError(f"unknown news setting(s): {sorted(unknown)}; "
                                f"known: {sorted(_RULES)}")
    out = dict(DEFAULTS["news"])
    for key, value in news.items():
        kind, lo, hi = _RULES[key]
        # bool is a subclass of int: "refresh_minutes": true must not read as 1
        if kind is int and (isinstance(value, bool) or not isinstance(value, int)):
            raise SettingsFileError(f'news.{key} must be a whole number, got {value!r}')
        if kind is bool and not isinstance(value, bool):
            raise SettingsFileError(f'news.{key} must be true or false, got {value!r}')
        if lo is not None and not lo <= value <= hi:
            raise SettingsFileError(f"news.{key} must be between {lo} and {hi}, got {value}")
        out[key] = value
    return {"news": out}


def load(path: Path | None = None) -> dict:
    """The settings in force. Missing file -> defaults; unusable file -> raises."""
    path = path or PATH
    if not path.exists():
        return json.loads(json.dumps(DEFAULTS))
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SettingsFileError(f"settings.json is not valid JSON: line {exc.lineno}, "
                                f"column {exc.colno}: {exc.msg}") from exc
    return _validate(raw)


def save(settings: dict, path: Path | None = None) -> None:
    """Validate, then write through a temp file so a crash never leaves half a file."""
    path = path or PATH
    clean = _validate(settings)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(clean, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def set_auto_refresh(on: bool, path: Path | None = None) -> dict:
    current = load(path)
    current["news"]["auto_refresh"] = bool(on)
    save(current, path)
    return current
