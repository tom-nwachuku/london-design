from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .assets import slugify
from .text import display_text


def resolve_route_ref(ref: Any, routes: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """Resolve a model-authored route reference without matching recommendation prose.

    London may return a packed route id, a route title, or a raw model-style id such as
    ``route_toy_computer`` while the pack later prefixes route ids with the brief slug.
    This resolver accepts those id/title forms only; it never consults the prose
    recommendation because that was the old flattening failure.
    """

    ref_text = display_text(ref)
    if not ref_text:
        return None

    exact = [
        route
        for route in routes
        if display_text(route.get("id")) == ref_text or display_text(route.get("title")) == ref_text
    ]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return None

    aliases = _route_ref_aliases(ref_text)
    matches: list[Mapping[str, Any]] = []
    for route in routes:
        route_id = slugify(display_text(route.get("id")), fallback="")
        route_title = slugify(display_text(route.get("title")), fallback="")
        if _route_slugs_match(aliases, route_id, route_title):
            matches.append(route)

    unique: list[Mapping[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for route in matches:
        key = (display_text(route.get("id")), display_text(route.get("title")))
        if key not in seen:
            unique.append(route)
            seen.add(key)
    return unique[0] if len(unique) == 1 else None


def canonicalize_route_ref(ref: Any, routes: Sequence[Mapping[str, Any]]) -> str:
    """Return a launch-safe route ref while preserving exact title refs as valid."""

    ref_text = display_text(ref)
    matched = resolve_route_ref(ref_text, routes)
    if not matched:
        return ref_text
    matched_title = display_text(matched.get("title"))
    if matched_title and ref_text == matched_title:
        return matched_title
    return display_text(matched.get("id"), fallback=matched_title or ref_text)


def resolved_route_title(ref: Any, routes: Sequence[Mapping[str, Any]]) -> str:
    matched = resolve_route_ref(ref, routes)
    return display_text(matched.get("title")) if matched else display_text(ref)


def _route_ref_aliases(ref: str) -> set[str]:
    ref_slug = slugify(ref, fallback="")
    aliases = {ref_slug} if ref_slug else set()
    if ref_slug.startswith("route-"):
        suffix = ref_slug.removeprefix("route-")
        if suffix and not suffix.isdigit():
            aliases.add(suffix)
    return aliases


def _route_slugs_match(aliases: set[str], route_id: str, route_title: str) -> bool:
    if not aliases:
        return False
    if route_id in aliases or route_title in aliases:
        return True
    return any(bool(alias) and route_id.endswith(f"-{alias}") for alias in aliases)
