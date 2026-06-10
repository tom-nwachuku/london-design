from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .assets import slugify
from .text import display_text

# Prototype primary sections (overview-first) — preserves the prototype's nav
# output byte-for-byte. (anchor id, label) pairs fed to _link with eyebrow
# "Prototype" / kind "global".
_PROTOTYPE_PRIMARY: tuple[tuple[str, str], ...] = (
    ("overview", "Overview"),
    ("proof", "Palette and type"),
    ("moments", "Moments"),
    ("handoff", "Handoff"),
    ("routes", "Routes"),
    ("route-sections", "Route sections"),
)

# Dossier primary sections in the locked VISUAL-FIRST order (04-UI-SPEC §Section
# Order Contract): moodboard first, no standalone "overview" anchor (the
# command-center header is the top, not a nav section). (anchor id, label) pairs.
_DOSSIER_PRIMARY: tuple[tuple[str, str], ...] = (
    ("moodboard", "Moodboard"),
    ("routes", "Routes"),
    ("comparison", "Comparison"),
    ("font-lab", "Font Lab"),
    ("conversation", "Conversation"),
    ("constraints", "Constraints"),
    ("evidence", "Evidence"),
    ("grader", "Quality Check"),
    ("handoff", "Handoff"),
    ("receipts", "Audit"),
)


@dataclass(frozen=True)
class NavLink:
    id: str
    label: str
    eyebrow: str
    route_id: str
    route_title: str
    kind: str


@dataclass(frozen=True)
class RouteNav:
    id: str
    title: str
    panel: NavLink
    sections: tuple[NavLink, ...]


@dataclass(frozen=True)
class Navigation:
    current_route_id: str
    current_route_title: str
    primary_sections: tuple[NavLink, ...]
    current_moments: tuple[NavLink, ...]
    routes: tuple[RouteNav, ...]

    @property
    def all_links(self) -> tuple[NavLink, ...]:
        links: list[NavLink] = []
        links.extend(self.primary_sections)
        links.extend(self.current_moments)
        for route in self.routes:
            links.append(route.panel)
            links.extend(route.sections)
        return tuple(links)


def prototype_route_id(route: Mapping[str, Any]) -> str:
    return display_text(route.get("id"), fallback=slugify(display_text(route.get("title"), fallback="route")))


def prototype_section_id(route_id: str, index: int, title: str) -> str:
    return f"proto-route-{route_id}-section-{index}-{slugify(title, fallback='section')}"


def prototype_moment_id(index: int, title: str) -> str:
    return f"moment-{index}-{slugify(title, fallback='moment')}"


def build_navigation(
    routes: Sequence[Mapping[str, Any]],
    current_route: Mapping[str, Any],
    *,
    moment_titles: Sequence[str] = (),
    surface: str = "prototype",
) -> Navigation:
    current_route_id = prototype_route_id(current_route)
    current_route_title = _route_title(current_route)
    primary_sections = _primary_sections(surface, current_route_id, current_route_title)
    current_moments = tuple(
        _link(
            prototype_moment_id(index, title),
            title,
            f"Moment {index:02d}",
            current_route_id,
            current_route_title,
            "moment",
        )
        for index, title in enumerate(moment_titles, start=1)
    )

    route_nav: list[RouteNav] = []
    for route in routes:
        route_id = prototype_route_id(route)
        route_title = _route_title(route)
        panel = _link(
            f"proto-route-{route_id}",
            route_title,
            "Route",
            route_id,
            route_title,
            "route",
        )
        sections = tuple(
            _link(
                prototype_section_id(route_id, index, section_title),
                section_title,
                f"Section {index:02d}",
                route_id,
                route_title,
                "route-section",
            )
            for index, section_title in enumerate(_route_section_titles(route), start=1)
        )
        route_nav.append(RouteNav(id=route_id, title=route_title, panel=panel, sections=sections))

    return Navigation(
        current_route_id=current_route_id,
        current_route_title=current_route_title,
        primary_sections=primary_sections,
        current_moments=current_moments,
        routes=tuple(route_nav),
    )


def _primary_sections(surface: str, route_id: str, route_title: str) -> tuple[NavLink, ...]:
    if surface == "dossier":
        return tuple(
            _link(anchor, label, "Dossier", route_id, route_title, "global")
            for anchor, label in _DOSSIER_PRIMARY
        )
    return tuple(
        _link(anchor, label, "Prototype", route_id, route_title, "global")
        for anchor, label in _PROTOTYPE_PRIMARY
    )


def _link(id: str, label: str, eyebrow: str, route_id: str, route_title: str, kind: str) -> NavLink:
    return NavLink(id=id, label=label, eyebrow=eyebrow, route_id=route_id, route_title=route_title, kind=kind)


def _route_title(route: Mapping[str, Any]) -> str:
    return display_text(route.get("title") or route.get("name"), fallback="Prototype Route")


def _route_section_titles(route: Mapping[str, Any]) -> list[str]:
    sections = route.get("sections")
    if not isinstance(sections, Sequence) or isinstance(sections, (str, bytes, bytearray)):
        return []
    return [
        display_text(section.get("title"), fallback=f"Section {index}")
        for index, section in enumerate(sections, start=1)
        if isinstance(section, Mapping)
    ]


# Back-compat aliases: the nav model is now shared (dossier + prototype), but
# `prototype.py` still imports the original Prototype*-prefixed names. These
# module-level aliases keep that importer green with zero edits to prototype.py.
# A drift between an alias and its neutral target is asserted against in
# tests/test_navigation.py (see threat T-04-02).
PrototypeNavLink = NavLink
PrototypeRouteNav = RouteNav
PrototypeNavigation = Navigation
build_prototype_navigation = build_navigation
