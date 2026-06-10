from __future__ import annotations

import json

import pytest

from london.cli import write_london_pack
from london.director import FakeDirector
from london.session import _apply_direction_to_gates, run_london_session

from conftest import BANNED_TEMPLATE_NAMES, BRIEFS


def test_london_session_varies_across_unrelated_briefs():
    packs = {name: run_london_session(brief) for name, brief in BRIEFS.items()}

    assert _unique(pack["category_assumption"] for pack in packs.values())
    assert _unique(pack["london_reframe"] for pack in packs.values())
    assert _unique(pack["routes"][0]["title"] for pack in packs.values())
    assert _unique(tuple(color["hex"] for color in pack["routes"][0]["palette"]) for pack in packs.values())
    assert _unique(pack["routes"][0]["type"] for pack in packs.values())
    assert _unique(tuple(lens["slug"] for lens in pack["source_plan"]["lenses"]) for pack in packs.values())
    assert _unique(tuple(section["title"] for section in pack["routes"][0]["sections"]) for pack in packs.values())

    for pack in packs.values():
        rendered = json.dumps(pack)
        assert "Joy Object System" not in rendered
        assert "Utility With A Wink" not in rendered
        assert ".mp4" not in rendered
        assert "source_video" not in rendered
        assert len(pack["gates"]) == 7
        for gate in pack["gates"]:
            assert gate["brain_queries"]
            assert gate["brain_findings"]
            assert gate["decisions"][0]["evidence"]


def test_empty_optional_conversation_rationale_preserves_gate_rationale():
    gates = [
        {
            "gate_name": "Quality",
            "decisions": [
                {
                    "summary": "Template decision",
                    "rationale": "Keep this schema-valid fallback rationale.",
                }
            ]
        }
    ]
    creative = {
        "conversation": [
            {
                "gate": "Quality",
                "decision": "London's live decision",
                "rationale": "",
            }
        ]
    }

    _apply_direction_to_gates(gates, creative)

    decision = gates[0]["decisions"][0]
    assert decision["summary"] == "London's live decision"
    assert decision["rationale"] == "Keep this schema-valid fallback rationale."


def test_direction_reads_match_gates_by_label_without_offline_bank_leakage():
    from london.models import GATE_IDS, GATE_NAMES

    gates = [
        {
            "gate_id": gate_id,
            "gate_name": GATE_NAMES[gate_id],
            "decisions": [
                {
                    "summary": f"OFFLINE BANK SUMMARY {gate_id}",
                    "rationale": f"OFFLINE BANK RATIONALE {gate_id}",
                }
            ],
        }
        for gate_id in GATE_IDS
    ]
    creative = {
        "conversation": [
            {
                "gate": GATE_NAMES["research"],
                "decision": "London names the lunch ritual tension.",
                "rationale": "The parent/kid split is the project brief.",
            },
            {
                "gate": GATE_NAMES["creative_direction"].lower(),
                "decision": "London makes choice feel like the product.",
                "rationale": "The system needs one repeatable daily moment.",
            },
            {
                "gate": GATE_NAMES["image_direction"],
                "decision": "London asks for object-kit boards, not stock lunch shots.",
                "rationale": "The visual proof should show parent setup and kid agency.",
            },
            {
                "gate": GATE_NAMES["build_motion"],
                "decision": "London keeps the prototype around the reveal loop.",
                "rationale": "Motion should explain the ritual, not decorate it.",
            },
        ]
    }

    _apply_direction_to_gates(gates, creative)

    by_id = {gate["gate_id"]: gate["decisions"][0] for gate in gates}
    assert by_id["research"]["summary"] == "London names the lunch ritual tension."
    assert by_id["creative_direction"]["summary"] == "London makes choice feel like the product."
    assert (
        by_id["image_direction"]["summary"]
        == "London asks for object-kit boards, not stock lunch shots."
    )
    assert by_id["build_motion"]["summary"] == "London keeps the prototype around the reveal loop."

    for gate_id in ("typography_color", "layout_mockups", "quality_review"):
        decision = by_id[gate_id]
        rendered = json.dumps(decision)
        assert decision["summary"].startswith("No model read for this gate:")
        assert "honest open checkpoint" in decision["rationale"]
        assert "OFFLINE BANK SUMMARY" not in rendered
        assert "OFFLINE BANK RATIONALE" not in rendered


@pytest.mark.real_director
def test_london_pack_exports_session_decisions_without_fixture_routes(tmp_path):
    # Anti-relapse: run on the MODEL path (FakeDirector) — NOT the OfflineDirector parity
    # oracle. The flipped ∉ BANNED assertion is only meaningful on the model path; the
    # offline banks deliberately reproduce the memorized names (they ARE the parity
    # oracle), so this test opts out of the autouse offline pin and injects FakeDirector.
    brief = tmp_path / "brief.md"
    brief.write_text(BRIEFS["fragrance"], encoding="utf-8")
    out = tmp_path / "pack"

    pack = write_london_pack(brief, out, director=FakeDirector())
    rendered_json = (out / "london-pack.json").read_text(encoding="utf-8")
    dossier = (out / "index.html").read_text(encoding="utf-8")
    prototype = (out / "prototype" / "index.html").read_text(encoding="utf-8")

    assert pack["session_lane"]["origin"] == "current_brief"
    assert pack["reference_packs"] == []
    # Anti-relapse (TST-01): the route title must NOT be a memorized template name. The
    # deleted exact-string assert (it pinned the title to a fixed memorized name) is what
    # kept the memorized engine alive; it is flipped to a negative assertion against the
    # 20 banned names.
    assert pack["routes"][0]["title"] not in BANNED_TEMPLATE_NAMES
    assert "fresh session lane" in rendered_json
    assert "Joy Object System" not in rendered_json
    assert "Utility With A Wink" not in rendered_json
    assert ".mp4" not in rendered_json
    assert "source_video" not in rendered_json
    assert "source_path" not in rendered_json
    assert pack["brief"]["source_label"] == "brief.md"
    assert pack["brief"]["source_ref"] == "input:brief"
    assert "{'title'" not in dossier
    assert "{'title'" not in prototype
    assert pack["routes"][0]["title"] in dossier
    assert pack["routes"][0]["sections"][0]["title"] in prototype
    assert "prototype-nav" in prototype
    assert "prototype-route-panel" in prototype


@pytest.mark.real_director
def test_unknown_brief_gets_fresh_lane_not_general_product_profile_or_hr_compliance():
    # Lane-isolation on the MODEL path: an unrelated brief must not inherit a memorized
    # template name or contaminate with another category's vocabulary. The deleted
    # exact-string title assert is flipped to ∉ BANNED.
    pack = run_london_session(
        """# Ceramic Tea Service

        Design a ceramic tea service for slow hospitality, table ritual, glaze details, and gift packaging.
        """,
        director=FakeDirector(),
    )

    assert pack["session_lane"]["origin"] == "current_brief"
    assert pack["routes"][0]["title"] not in BANNED_TEMPLATE_NAMES
    assert "Compliance software" not in pack["category_assumption"]
    assert "Signal Object Manual" not in json.dumps(pack)
    assert "HR" not in json.dumps(pack)


@pytest.mark.real_director
def test_public_horoscope_app_gets_fresh_consumer_app_lane_not_static_profile():
    # Lane-isolation on the MODEL path: the horoscope brief must echo its OWN tokens and
    # carry NONE of the memorized static-profile names. The two deleted exact-string
    # route-title asserts are flipped to ∉ BANNED.
    pack = run_london_session(
        """# Public Horoscope App

        Create a public-facing horoscope app for daily astrology readings, birth-chart onboarding,
        compatibility moments, push-notification rituals, and shareable visual cards.
        """,
        director=FakeDirector(),
    )
    rendered = json.dumps(pack)

    assert pack["session_lane"]["origin"] == "current_brief"
    assert pack["reference_packs"] == []
    assert all(route["title"] not in BANNED_TEMPLATE_NAMES for route in pack["routes"])
    assert "daily astrology readings" in rendered
    assert "Morning Sign-In" not in rendered
    assert "Compatibility Card Studio" not in rendered
    assert "Signal Object Manual" not in rendered
    assert "Collector Utility" not in rendered


def test_every_new_prompt_stays_in_its_own_lane():
    fresh_briefs = {
        "horoscope": """# Public Horoscope App

        Design a public facing horoscope app for daily astrology readings, birth-chart onboarding,
        compatibility moments, push notifications, and shareable cards.
        """,
        "pet_weather": """# Weather App for Pet Owners

        Design a weather app for pet owners that helps decide when it is safe, comfortable,
        and worth it to walk, play outside, or plan around alerts.
        """,
        "fragrance": BRIEFS["fragrance"],
    }
    packs = {name: run_london_session(brief) for name, brief in fresh_briefs.items()}

    assert _unique(pack["session_lane"]["id"] for pack in packs.values())
    assert _unique(pack["category_assumption"] for pack in packs.values())
    assert _unique(pack["london_reframe"] for pack in packs.values())
    assert _unique(tuple(route["title"] for route in pack["routes"]) for pack in packs.values())
    assert _unique(tuple(color["hex"] for color in pack["routes"][0]["palette"]) for pack in packs.values())
    assert _unique(pack["routes"][0]["type"] for pack in packs.values())
    assert _unique(pack["session_lane"]["source_terms"] for pack in packs.values())
    assert _unique(tuple(section["title"] for route in pack["routes"] for section in route["sections"]) for pack in packs.values())

    weather = json.dumps(packs["pet_weather"])
    assert "Weather App" in weather
    assert "pet owners" in weather
    assert "horoscope app is a daily content feed" not in weather
    assert "Morning Sign-In" not in weather
    assert "Compatibility Card Studio" not in weather
    assert "Quiet Atelier" not in weather
    assert all(pack["reference_packs"] == [] for pack in packs.values())
    assert all(len(pack["gates"]) == 7 for pack in packs.values())


def test_absolute_input_source_path_is_sanitized_from_public_brief():
    pack = run_london_session(
        {
            "title": "Path Brief",
            "text": "Design a product without leaking archive paths.",
            "source_path": "/Users/example/private/archive/source.md",  # EXPECTED-FIXTURE
        }
    )
    rendered = json.dumps(pack)

    assert "source_path" not in pack["brief"]
    assert pack["brief"]["source_label"] == "source.md"
    assert pack["brief"]["source_ref"] == "input:brief"
    assert "/Users/example/private/archive/source.md" not in rendered  # EXPECTED-FIXTURE


def test_windows_input_source_path_is_sanitized_from_public_brief():
    pack = run_london_session(
        {
            "title": "Windows Path Brief",
            "text": "Design a product without leaking archive paths.",
            "source_path": r"C:\Users\example\private\archive\source.md",
        }
    )
    rendered = json.dumps(pack)

    assert "source_path" not in pack["brief"]
    assert pack["brief"]["source_label"] == "source.md"
    assert pack["brief"]["source_ref"] == "input:brief"
    assert r"C:\Users\example\private\archive\source.md" not in rendered


def test_fixture_mode_is_the_only_path_for_legacy_generic_routes(tmp_path):
    brief = tmp_path / "brief.md"
    brief.write_text(BRIEFS["kids"], encoding="utf-8")
    out = tmp_path / "fixture-pack"

    pack = write_london_pack(brief, out, fixture=True)

    assert pack["routes"][0]["title"] == "Joy Object System"


def test_pack_carries_recommended_route(tmp_path):
    # D-04 floor (Q7): the OFFLINE/FAKE floor carries the machine reference
    # `recommended_route_ref` = the lead route title (routes[0]) and the verbatim PROSE
    # field `recommended_route` = "" (the floor never argues a case). Both are carried AS
    # GIVEN — the renderer resolves the ref deterministically, never by title-matching.
    pack = run_london_session(BRIEFS["fragrance"])

    assert pack["recommended_route_ref"] == pack["routes"][0]["title"]
    assert pack["recommended_route"] == ""  # prose floor is empty (D-04); never a faked argument


def test_full_pack_validates_with_recommended_route(tmp_path):
    # The write-gate schema has top-level additionalProperties:false, so the new pack
    # key must be admitted by schemas/london-pack.schema.json. write_london_pack runs
    # enrich_workbench_pack (pops DIRECTION_RESULT_KEY) then validate_pack — this passing
    # proves recommended_route survives enrichment AND is accepted by the gate.
    brief = tmp_path / "brief.md"
    brief.write_text(BRIEFS["fragrance"], encoding="utf-8")
    out = tmp_path / "validated-pack"

    pack = write_london_pack(brief, out)

    assert pack["recommended_route_ref"]


# =============================================================================
# Phase 5 Body-Fit (BODY-02 / D-04) — split recommended_route into a machine
# reference + verbatim prose. RED until Task 1 adds recommended_route_ref and
# Task 2 carries both AS GIVEN. The reference resolves to a route by a MACHINE
# field (never a title-match); the prose renders verbatim at BOTH bimodal ends
# (11-char bare AND >1000-char argued) — no truncation, no summarizer (D-11).
# =============================================================================


class _ProseRecommendationDirector:
    """A model-path director that emits a specific recommended_route_ref + verbatim prose.

    Wraps the OfflineDirector to produce a fully-valid DirectionResult, then overrides the
    two BODY-02 fields so the test can drive the bimodal recommendation through real pack
    assembly without coupling to any capture's brief prose.
    """

    def __init__(self, prose: str):
        from london.director import OfflineDirector

        self._inner = OfflineDirector()
        self._prose = prose

    def direct(self, request):
        result = self._inner.direct(request)
        # ref = a real route the director produced (machine-resolvable, NOT title-matched)
        return result.model_copy(
            update={
                "recommended_route_ref": result.routes[1].title,
                "recommended_route": self._prose,
            }
        )


class _RawRouteRefDirector:
    """A model-path-shaped director that emits the pre-pack raw route id form."""

    def __init__(self):
        from london.director import OfflineDirector

        self._inner = OfflineDirector()

    def direct(self, request):
        from london.assets import slugify

        result = self._inner.direct(request)
        picked = result.routes[1]
        raw_ref = f"route_{slugify(picked.title).replace('-', '_')}"
        return result.model_copy(update={"recommended_route_ref": raw_ref})


@pytest.mark.real_director
def test_recommended_route_ref_and_prose():
    from conftest import SYNTHETIC_RECOMMENDATION_BARE, SYNTHETIC_RECOMMENDATION_LONG

    for prose in (SYNTHETIC_RECOMMENDATION_BARE, SYNTHETIC_RECOMMENDATION_LONG):
        director = _ProseRecommendationDirector(prose)
        pack = run_london_session(BRIEFS["fragrance"], director=director)

        # The reference is a MACHINE field that resolves to an actual route by title-equality
        # of the reference value to a route — never by fuzzy-matching the prose to a title.
        route_titles = {route["title"] for route in pack["routes"]}
        assert pack["recommended_route_ref"] in route_titles, "ref must resolve to a real route"
        assert pack["recommended_route_ref"] == pack["routes"][1]["title"]

        # The prose renders VERBATIM — byte-for-byte, at both bimodal ends.
        assert pack["recommended_route"] == prose
        assert json.dumps(pack).count(prose) >= 1


@pytest.mark.real_director
def test_raw_model_route_ref_canonicalizes_after_route_packing():
    pack = run_london_session(BRIEFS["fragrance"], director=_RawRouteRefDirector())

    assert pack["recommended_route_ref"] == pack["routes"][1]["id"]
    assert pack["recommended_route_ref"].startswith("luxury-fragrance-compact-")
    assert not pack["recommended_route_ref"].startswith("route_")


# =============================================================================
# Phase 4.5 GATE-01 — artifact_type pack carry + write-gate (RED stubs; Wave 0).
# Clones of test_pack_carries_recommended_route (:199) and
# test_full_pack_validates_with_recommended_route (:210). They fail today because
# the pack assembled by run_london_session carries NO artifact_type key yet, and
# the write-gate schema does not admit it. Wave 2 drives them GREEN.
# =============================================================================

_ARTIFACT_ENUM = {"website", "app", "product", "brand", "generic"}


def test_pack_carries_artifact_type_as_given(tmp_path):
    # GATE-01: with no --artifact flag and no brief field the resolution falls through to
    # the honest "generic" default, and the pack carries it AS GIVEN (a real top-level key,
    # mirror of recommended_route). The deterministic paths never guess a specific type.
    pack = run_london_session(BRIEFS["fragrance"])

    assert pack["artifact_type"] == "generic"


def test_full_pack_validates_with_artifact_type(tmp_path):
    # The write-gate schema has top-level additionalProperties:false, so artifact_type must
    # be admitted by schemas/london-pack.schema.json AND survive enrich + scrub + validate.
    # Clone of test_full_pack_validates_with_recommended_route.
    brief = tmp_path / "brief.md"
    brief.write_text(BRIEFS["fragrance"], encoding="utf-8")
    out = tmp_path / "artifact-validated-pack"

    pack = write_london_pack(brief, out)

    assert pack["artifact_type"] in _ARTIFACT_ENUM


def test_path_brief_is_read_once_for_body_and_artifact(monkeypatch, tmp_path):
    brief = tmp_path / "brief.md"
    brief.write_text(
        "---\nartifact: product\n---\n# Lunchbox ritual kit\nA joyful retro-futurist lunchbox system.",
        encoding="utf-8",
    )
    original_read_text = type(brief).read_text
    reads = []

    def counted_read_text(self, *args, **kwargs):
        if self == brief:
            reads.append(self)
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(type(brief), "read_text", counted_read_text)

    pack = run_london_session(brief, director=FakeDirector())

    assert reads == [brief]
    assert pack["artifact_type"] == "product"
    assert pack["brief"]["title"] == "Lunchbox ritual kit"


def _unique(values) -> bool:
    realized = list(values)
    return len(set(realized)) == len(realized)
