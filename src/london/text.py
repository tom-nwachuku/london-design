from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any


def clean_brief_text(pack: Mapping[str, Any], fallback: str = "A public London Pack rendered locally.") -> str:
    """Return display-safe brief text without leaking Python mapping reprs."""

    summary = _clean(pack.get("summary"))
    if summary:
        return summary

    brief = pack.get("brief")
    if isinstance(brief, Mapping):
        for key in ("text", "summary", "description", "title"):
            value = _clean(brief.get(key))
            if value:
                return value
        return fallback

    value = _clean(brief)
    return value or fallback


def clean_title(pack: Mapping[str, Any], fallback: str = "London Pack") -> str:
    """Return a display-safe title from top-level or structured brief fields."""

    title = _clean(pack.get("title") or pack.get("name"))
    if title:
        return title

    brief = pack.get("brief")
    if isinstance(brief, Mapping):
        title = _clean(brief.get("title"))
        if title:
            return title

    return fallback


def display_text(value: Any, fallback: str = "") -> str:
    """Return UI-safe text from strings, mappings, or small sequences."""

    if value is None:
        return fallback
    if isinstance(value, Mapping):
        for key in ("text", "body", "summary", "title", "name", "label", "headline", "subhead"):
            cleaned = _clean(value.get(key))
            if cleaned:
                return cleaned
        return fallback
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        parts = [display_text(item) for item in value]
        joined = "; ".join(part for part in parts if part)
        return joined or fallback
    return _clean(value) or fallback


def _clean(value: Any) -> str:
    if value is None or isinstance(value, Mapping):
        return ""
    return str(value).strip()
