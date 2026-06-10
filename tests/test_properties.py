"""Property / contract catalogue (TST-02) with PAIRED negative controls (TST-03).

These are the anti-relapse exit controls. Each property asserts a RELATIONSHIP (not an
exact string) over the model-path pack produced by ``FakeDirector`` — the keyless source
of every property assertion (TST-04, no live model). Crucially, EACH property is paired
with a negative-control fixture (``generic_pack`` / ``memorized_name_pack`` /
``qa_vocab_pack``) that the SAME predicate provably REJECTS: a property with no negative
control that can fail it is too loose and proves nothing (Pitfall 8).

The predicates themselves live in ``conftest`` so the positive assertion and the
negative-control rejection call the identical boolean — the rejection is real, not a
parallel re-implementation that could drift.

Catalogue (RESEARCH §Test Design):
  1 title ∉ BANNED            → memorized_name_pack rejects
  2 title contains brief vocab → generic_pack rejects
  3 two routes distinct        → generic_pack rejects (collapses to one route)
  4 unrelated briefs distinct  → _unique titles/reframes across ≥2 unrelated briefs
  5 rationale cites brief+brain → generic_pack rejects (empty brain, filler rationale)
  6 no-generic-filler          → generic_pack rejects (pure "modern clean" prose)

Property 7 (no-QA-vocab) + property 8 (mode-blind render) live in ``test_honesty.py``.
"""

from __future__ import annotations

from london.director import FakeDirector
from london.session import run_london_session
from london.workbench import enrich_workbench_pack

from conftest import (
    BANNED_TEMPLATE_NAMES,
    BRIEFS,
    prop_no_generic_filler,
    prop_rationale_cites_brief_and_brain,
    prop_title_contains_brief_vocab,
    prop_titles_not_banned,
    prop_two_routes_distinct,
    tokenize,
)

# A spread of semantically unrelated briefs so each property is exercised across the
# whole FakeDirector echo surface (RESEARCH: run each property a few times for stability),
# not a single happy-path brief.
_UNRELATED_BRIEFS: dict[str, str] = {
    "fragrance": BRIEFS["fragrance"],
    "kids": BRIEFS["kids"],
    "hr": BRIEFS["hr"],
    "horoscope": """# Public Horoscope App

    Create a public-facing horoscope app for daily astrology readings, birth-chart
    onboarding, compatibility moments, push-notification rituals, and shareable cards.
    """,
    "pet_weather": """# Weather App for Pet Owners

    Design a weather app for pet owners that helps decide when it is safe, comfortable,
    and worth it to walk, play outside, or plan around alerts.
    """,
}


def _model_pack(brief: str) -> dict:
    """A full workbench pack on the MODEL path (FakeDirector) — keyless (TST-04)."""

    pack = run_london_session(brief, director=FakeDirector())
    enrich_workbench_pack(pack)
    pack.setdefault("brief", {})
    # ``run_london_session`` already records a sanitized brief; ensure the raw text is
    # present for the brief-vocab predicate (the public brief carries title + snapshot).
    if "text" not in pack["brief"]:
        pack["brief"]["text"] = brief
    return pack


def _packs() -> dict[str, dict]:
    return {name: _model_pack(brief) for name, brief in _UNRELATED_BRIEFS.items()}


def _unique(values) -> bool:
    realized = list(values)
    return len(set(realized)) == len(realized)


# --- Property 1: title ∉ BANNED -----------------------------------------------------


def test_property_1_titles_not_in_banned_template_names():
    for name, pack in _packs().items():
        assert prop_titles_not_banned(pack), f"{name}: a route title is a banned memorized name"
        for route in pack["routes"]:
            assert route["title"] not in BANNED_TEMPLATE_NAMES


def test_property_1_negative_control_memorized_name_pack_is_rejected(memorized_name_pack):
    # The known-bad pack titles routes straight from BANNED_TEMPLATE_NAMES — the exact
    # relapse the deleted exact-string asserts kept alive. The property MUST fail it.
    assert prop_titles_not_banned(memorized_name_pack) is False


# --- Property 2: title contains brief vocab -----------------------------------------


def test_property_2_titles_contain_brief_vocabulary():
    for name, pack in _packs().items():
        assert prop_title_contains_brief_vocab(pack), f"{name}: a route title echoes no brief token"


def test_property_2_negative_control_generic_pack_is_rejected(generic_pack):
    # "Modern Clean Route" shares no token with the fragrance brief — the property fails.
    assert prop_title_contains_brief_vocab(generic_pack) is False


# --- Property 3: two routes distinct -------------------------------------------------


def test_property_3_two_routes_are_distinct():
    for name, pack in _packs().items():
        assert prop_two_routes_distinct(pack), f"{name}: the two routes are not distinct"


def test_property_3_negative_control_generic_pack_is_rejected(generic_pack):
    # Both generic routes are identical "Modern Clean Route" clones — the property fails.
    assert prop_two_routes_distinct(generic_pack) is False


# --- Property 4: unrelated briefs distinct ------------------------------------------


def test_property_4_unrelated_briefs_produce_distinct_output():
    packs = _packs()
    assert _unique(pack["routes"][0]["title"] for pack in packs.values())
    assert _unique(pack["london_reframe"] for pack in packs.values())
    assert _unique(pack["category_assumption"] for pack in packs.values())


def test_property_4_negative_control_two_identical_briefs_collapse():
    # The negative control for "unrelated briefs distinct": feeding the SAME brief twice
    # must collapse (titles identical), proving the distinctness check has teeth and is
    # not trivially true for any pair of packs.
    same = [_model_pack(BRIEFS["fragrance"]) for _ in range(2)]
    assert not _unique(pack["routes"][0]["title"] for pack in same)


# --- Property 5: rationale cites brief + brain --------------------------------------


def test_property_5_rationale_cites_brief_and_non_empty_brain():
    for name, pack in _packs().items():
        # RAG must actually reach the director (Pitfall 4): the pack carries brain findings.
        assert any(gate.get("brain_findings") for gate in pack["gates"]), f"{name}: empty RAG"
        assert prop_rationale_cites_brief_and_brain(pack), f"{name}: rationale cites no brief token"


def test_property_5_negative_control_generic_pack_is_rejected(generic_pack):
    # Generic pack has empty brain_findings AND filler rationale citing no brief token.
    assert prop_rationale_cites_brief_and_brain(generic_pack) is False


# --- Property 6: no generic "modern clean" filler -----------------------------------


def test_property_6_no_generic_modern_clean_filler():
    for name, pack in _packs().items():
        assert prop_no_generic_filler(pack), f"{name}: route prose collapsed into stock filler"


def test_property_6_negative_control_generic_pack_is_rejected(generic_pack):
    # "modern clean / sleek minimal / bold vibrant" filler — the property fails.
    assert prop_no_generic_filler(generic_pack) is False


# --- Stability: the FakeDirector echo is deterministic per brief --------------------


def test_property_echo_is_stable_across_repeats():
    # Run the same brief several times; the echoing FakeDirector is deterministic, so the
    # title set is stable AND always brief-derived (no flaky property pass/fail).
    titles = [
        tuple(route["title"] for route in _model_pack(BRIEFS["kids"])["routes"])
        for _ in range(5)
    ]
    assert len(set(titles)) == 1
    vocab = tokenize(BRIEFS["kids"])
    for title in titles[0]:
        assert tokenize(title) & vocab
