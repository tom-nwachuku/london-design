"""Unit coverage for the shared navigation model (src/london/navigation.py).

This is the data-model half of NAV-01/TPL-06: ONE nav model serves both the
dossier renderer and the prototype. These tests assert on the model shape
(not internal symbol churn) and are fully keyless — no API key, no browser,
no fixtures beyond an inline routes list.
"""

from london.navigation import (
    Navigation,
    PrototypeNavigation,
    build_navigation,
    build_prototype_navigation,
    prototype_route_id,
)


def sample_routes():
    """A minimal two-route list: each a mapping with id/title/sections."""
    return [
        {
            "id": "route-alpha",
            "title": "Route Alpha",
            "sections": [{"title": "Open"}, {"title": "Close"}],
        },
        {
            "id": "route-beta",
            "title": "Route Beta",
            "sections": [{"title": "Brief"}],
        },
    ]


# The locked VISUAL-FIRST dossier primary-section anchors (04-UI-SPEC
# §Section Order Contract). Order matters; "overview" is intentionally absent
# (the command-center header is the top, not a nav section).
# DELIBERATELY UPDATED for RENDER-07: the NEW #grader section is registered between
# evidence and handoff across _SECTIONS, render_dossier's _section_helpers, and
# navigation._DOSSIER_PRIMARY — so the shared dossier nav now emits "grader" too.
DOSSIER_ANCHORS = [
    "moodboard",
    "routes",
    "comparison",
    "font-lab",
    "conversation",
    "constraints",
    "evidence",
    "grader",
    "handoff",
    "receipts",
]


def test_dossier_surface_emits_visual_first_sections():
    routes = sample_routes()
    nav = build_navigation(routes, routes[0], surface="dossier")

    assert isinstance(nav, Navigation)
    ids = [link.id for link in nav.primary_sections]
    labels = {link.id: link.label for link in nav.primary_sections}
    # First anchor is the moodboard (visual-first), and there is NO standalone
    # overview anchor for the dossier surface.
    assert ids[0] == "moodboard"
    assert "overview" not in ids
    # Every locked visual-first anchor is present, in the locked order.
    assert ids == DOSSIER_ANCHORS
    assert labels["grader"] == "Quality Check"
    assert labels["receipts"] == "Audit"


def test_prototype_surface_is_unchanged():
    routes = sample_routes()
    # Default surface is "prototype"; the prototype keeps its overview-first set.
    nav = build_navigation(routes, routes[0])
    ids = [link.id for link in nav.primary_sections]

    assert ids[0] == "overview"
    # The prototype-specific anchors stay intact (overview/proof/moments/...).
    assert "proof" in ids
    assert "moments" in ids


def test_back_compat_aliases_resolve_to_neutral_names():
    # The Prototype*-prefixed names are now aliases for the neutral model.
    # A future drift between an alias and its target fails here (threat T-04-02).
    assert PrototypeNavigation is Navigation
    assert build_prototype_navigation is build_navigation


def test_all_links_cover_route_panels_and_sections_with_id_parity():
    routes = sample_routes()
    nav = build_navigation(routes, routes[0], surface="dossier")

    link_ids = {link.id for link in nav.all_links}
    # Each route contributes a panel link plus one link per section.
    for route in routes:
        route_id = prototype_route_id(route)
        # Route-id parity: the panel link id is derived from prototype_route_id,
        # the same scheme render._route_id uses (the shared anchor seam).
        assert any(link.route_id == route_id for link in nav.all_links)
        panel_id = f"proto-route-{route_id}"
        assert panel_id in link_ids

    # all_links includes the primary sections too.
    assert "moodboard" in link_ids
