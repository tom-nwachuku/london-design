from __future__ import annotations

import json

import pytest

from london.director import FakeDirector
from london.persona import WORKBENCH_GATE_CRITIQUE_FALLBACK, WORKBENCH_GATE_QUESTION_FALLBACK
from london.session import run_london_session
from london.workbench import build_conversation, build_font_options, build_moodboard_tiles, enrich_workbench_pack

from conftest import BANNED_TEMPLATE_NAMES, BRIEFS


def _pack(brief: str):
    pack = run_london_session(brief)
    enrich_workbench_pack(pack)
    return pack


def _model_pack(brief: str):
    """Build a workbench pack on the MODEL path (FakeDirector) — used by the anti-relapse
    font-lab tests whose deleted exact-string asserts are flipped to ∉ BANNED. The default
    ``_pack`` runs the OfflineDirector parity oracle, which reproduces memorized names."""

    pack = run_london_session(brief, director=FakeDirector())
    enrich_workbench_pack(pack)
    return pack


def test_workbench_pack_fields_are_populated():
    pack = _pack(BRIEFS["fragrance"])

    for key in (
        "conversation",
        "route_comparison",
        "font_options",
        "moodboard_tiles",
        "copy_blocks",
        "next_steps",
        "evidence_summary",
    ):
        assert pack[key]

    # D-01 / Q7: the conversation count is DERIVED from the director's as-authored
    # decisions (count = len), never hard-coded to 7. The displayed count must equal the
    # number of decisions London (here the OfflineDirector parity oracle) actually wrote.
    assert len(pack["conversation"]) >= 1
    assert all(entry["decision"] and entry["critique"] for entry in pack["conversation"])
    assert all(entry["answer_label"] == "London's read" for entry in pack["conversation"])
    assert all("Local inference" in entry["honesty_badges"] for entry in pack["conversation"])
    assert all(entry["evidence_classes"]["london_brain_findings"] > 0 for entry in pack["conversation"])
    assert all(entry["evidence_classes"]["source_targets"] > 0 for entry in pack["conversation"])
    assert all(len(group["options"]) >= 3 for group in pack["font_options"])
    assert all(option["why_this_route_not_other_route"] for group in pack["font_options"] for option in group["options"])
    assert all(len(group["tiles"]) >= 6 for group in pack["moodboard_tiles"])
    assert any(block["kind"] == "image_prompt" and block["text"] for block in pack["copy_blocks"])
    assert any(block["kind"] == "builder_prompt" and block["text"] for block in pack["copy_blocks"])
    assert pack["evidence_summary"]["source_claim"]
    assert "London Brain Findings" in pack["evidence_summary"]["source_claim"]
    assert {group["evidence_class"] for group in pack["evidence_summary"]["brain"]} == {"London Brain Finding"}
    assert {source["evidence_class"] for source in pack["evidence_summary"]["sources"]} == {"Source Target"}


def test_route_comparison_palette_logic_is_public_read_not_raw_palette_variables():
    pack = _pack(BRIEFS["kids"])

    for row in pack["route_comparison"]:
        text = row["palette_logic"].lower()
        assert "#" not in text
        assert "receipt" not in text
        assert "proof:" not in text
        assert "evidence:" in text


def test_route_comparison_thesis_filters_prompt_shaped_brief_text():
    pack = _pack(BRIEFS["kids"])

    for row in pack["route_comparison"]:
        thesis = row["thesis"].lower()
        assert "answer the first real decision" not in thesis
        assert "route people can compare" not in thesis
        assert not ("product brief" in thesis and thesis.startswith(("make ", "turn ")))


def test_build_font_options_preserves_nested_font_preview_metadata():
    pack = run_london_session(BRIEFS["kids"])
    route_title = pack["routes"][0]["title"]
    base_option = {
        "name": "Kiddo Local",
        "headline_font": "Kiddo Local",
        "body_font": "Kiddo Sans",
        "label_font": "Kiddo Label",
        "fallback_stack": "Arial, Helvetica, sans-serif",
        "best_use": "Lunchbox route proof.",
        "why_london_chose_it": "It keeps the object playful and legible.",
        "why_this_route_not_other_route": "The other route needs a calmer family-dashboard read.",
        "what_makes_it_wrong": "Wrong if the route needs premium editorial tension.",
        "import_hint": "@import url('https://fonts.example/kiddo.css');",
    }
    direction = {
        "font_options": [
            {
                "route_title": route_title,
                "options": [
                    {
                        **base_option,
                        "tier": "open_public",
                        "font_preview": {
                            "status": "actual_loaded",
                            "delivery": "local_asset",
                            "rendered_family": "Kiddo Local",
                            "source_label": "Bundled test font",
                            "license_note": "Local test asset supplied with this pack.",
                            "asset_href": "assets/fonts/kiddo-local.woff2",
                        },
                    },
                    {**base_option, "tier": "safe_local", "name": "Kiddo Safe"},
                    {**base_option, "tier": "premium_inspiration", "name": "Kiddo Premium"},
                ],
            }
        ]
    }

    groups = build_font_options(pack, direction)

    assert groups[0]["options"][0]["font_preview"]["status"] == "actual_loaded"
    assert groups[0]["options"][0]["font_preview"]["asset_href"] == "assets/fonts/kiddo-local.woff2"


def test_moodboard_tiles_include_required_canvas_parts():
    pack = _pack(BRIEFS["kids"])

    kinds = {tile["kind"] for group in pack["moodboard_tiles"] for tile in group["tiles"]}

    assert {"manual-prompt-card", "visual-direction-board"} & kinds
    assert "local-system-sketch" not in kinds
    assert "fixture-system-sketch" not in kinds
    assert "palette-strip" in kinds
    assert "type-specimen" in kinds
    assert "product-moment" in kinds
    assert "interface-frame" in kinds
    assert "object-packaging" in kinds
    assert "motion-idea" in kinds
    assert all(group["tiles"][0]["tension_pair"]["wants"] for group in pack["moodboard_tiles"])
    assert all(group["tiles"][0]["tension_pair"]["avoid"] for group in pack["moodboard_tiles"])
    for group in pack["moodboard_tiles"]:
        type_tiles = [tile for tile in group["tiles"] if tile["kind"] == "type-specimen"]
        assert type_tiles
        assert type_tiles[0]["sample"] == group["route_title"]
        assert "brief" not in type_tiles[0]["sample"].lower()


def test_moodboard_hero_public_copy_is_not_provider_status_copy():
    pack = _pack(BRIEFS["kids"])

    hero_tiles = [group["tiles"][0] for group in pack["moodboard_tiles"]]
    assert hero_tiles
    for tile in hero_tiles:
        public_blob = json.dumps(
            {
                "title": tile["title"],
                "caption": tile["caption"],
                "constraint_tags": tile["constraint_tags"],
            }
        ).lower()
        for marker in (
            "actual font loaded",
            "asset_sha256",
            "fallback",
            "generated_live",
            "image generation was disabled",
            "local_fallback",
            "manual prompt",
            "manual-prompt",
            "provider",
            "receipt",
            "requested:",
            "sha256",
            "status:",
        ):
            assert marker not in public_blob
        assert tile["title"]
        assert tile["caption"]


def test_moodboard_hero_replaces_live_provider_caption_with_london_copy():
    pack = _pack(BRIEFS["kids"])
    route = pack["routes"][0]
    route["visual_read"] = "London reads this route as a durable, object-first product ritual."
    route["assets"] = [
        {
            "title": "Provider status should not surface",
            "caption": "Generated Gemini Pro route visual with provider-backed receipt.",
            "alt": "Generated Gemini Pro route visual.",
            "kind": "generated-concept-image",
            "src": "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg'></svg>",
            "deterministic": False,
        }
    ]

    groups = build_moodboard_tiles(pack)
    hero = groups[0]["tiles"][0]

    assert hero["caption"] == "London reads this route as a durable, object-first product ritual."
    assert "gemini" not in hero["caption"].lower()
    assert "provider" not in hero["caption"].lower()


def test_moodboard_hero_replaces_disabled_generation_status_with_london_copy():
    pack = _pack(BRIEFS["kids"])
    route = pack["routes"][0]
    route["visual_read"] = "London keeps the product object visible before the route sells mood."
    route["assets"] = [
        {
            "title": "Visual board",
            "caption": "Image generation was disabled for this run.",
            "alt": "Image generation was disabled for this run.",
            "kind": "visual-direction-board",
            "src": "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg'></svg>",
            "deterministic": True,
        }
    ]

    groups = build_moodboard_tiles(pack)
    hero = groups[0]["tiles"][0]

    assert hero["caption"] == "London keeps the product object visible before the route sells mood."
    assert "image generation was disabled" not in hero["caption"].lower()


def test_workbench_outputs_vary_across_unrelated_briefs():
    packs = {name: _pack(brief) for name, brief in BRIEFS.items()}

    assert _unique(pack["route_comparison"][0]["title"] for pack in packs.values())
    assert _unique(pack["route_comparison"][0]["palette_logic"] for pack in packs.values())
    assert _unique(pack["font_options"][0]["options"][0]["name"] for pack in packs.values())
    assert _unique(pack["moodboard_tiles"][0]["tiles"][0]["caption"] for pack in packs.values())
    assert _unique(pack["copy_blocks"][2]["text"] for pack in packs.values())
    assert _unique(pack["next_steps"][-1]["description"] for pack in packs.values())

    for pack in packs.values():
        rendered = json.dumps(pack)
        assert "Joy Object System" not in rendered
        assert "Utility With A Wink" not in rendered
        assert ".mp4" not in rendered
        assert "source_video" not in rendered


@pytest.mark.real_director
def test_font_lab_varies_semantically_between_routes_in_same_brief():
    # Anti-relapse (TST-01): the two deleted exact-string route_title asserts are flipped
    # to ∉ BANNED and run on the MODEL path. The two routes still get distinct font
    # identities (the A5
    # distinct-fonts guarantee), proven via the per-route font name + the route-specific
    # "why this route not the other" rationale.
    pack = _model_pack(BRIEFS["kids"])
    first_route = pack["font_options"][0]["options"][0]
    second_route = pack["font_options"][1]["options"][0]

    assert pack["font_options"][0]["route_title"] not in BANNED_TEMPLATE_NAMES
    assert pack["font_options"][1]["route_title"] not in BANNED_TEMPLATE_NAMES
    assert pack["font_options"][0]["route_title"] != pack["font_options"][1]["route_title"]
    assert first_route["name"] != second_route["name"]
    assert first_route["why_this_route_not_other_route"] != second_route["why_this_route_not_other_route"]


@pytest.mark.real_director
def test_horoscope_font_lab_uses_ritual_and_social_card_semantics():
    # Anti-relapse (TST-01): the two deleted exact-string route_title asserts are flipped
    # to ∉ BANNED on the MODEL path; the routes echo the brief's OWN tokens, not
    # memorized names.
    pack = _model_pack(
        """# Public Horoscope App

        Create a public-facing horoscope app for daily astrology readings, birth-chart onboarding,
        compatibility moments, push-notification rituals, and shareable visual cards.
        """
    )
    first_route = pack["font_options"][0]["options"][0]
    second_route = pack["font_options"][1]["options"][0]

    assert pack["font_options"][0]["route_title"] not in BANNED_TEMPLATE_NAMES
    assert pack["font_options"][1]["route_title"] not in BANNED_TEMPLATE_NAMES
    assert pack["font_options"][0]["route_title"] != pack["font_options"][1]["route_title"]
    assert first_route["name"] != second_route["name"]
    assert first_route["why_this_route_not_other_route"] != second_route["why_this_route_not_other_route"]


def test_evidence_dedupes_by_id_and_normalized_source_title_category():
    # Build a pack that STILL carries the DirectionResult (run_london_session, not the
    # already-enriched _pack) so enrich derives the variable-N conversation from London's
    # decisions; the evidence for conversation[0] is the deduped gate[0] findings.
    pack = run_london_session(BRIEFS["kids"])
    duplicate = dict(pack["gates"][0]["brain_findings"][0])
    near_duplicate = dict(pack["gates"][0]["brain_findings"][1])
    near_duplicate["id"] = "new-id-same-source-title-category"
    near_duplicate["body"] = near_duplicate["body"] + " Extra nuance that should not matter for exact source/title/category."
    pack["gates"][0]["brain_findings"].append(duplicate)
    pack["gates"][0]["brain_findings"].append(near_duplicate)

    enrich_workbench_pack(pack)
    gate = pack["conversation"][0]
    ids = [finding["id"] for finding in gate["brain_findings"]]
    normalized_keys = {
        (
            finding["debug"]["source_ref"],
            finding["insight_title"].lower(),
            finding["category"].lower(),
        )
        for finding in gate["brain_findings"]
    }

    assert len(ids) == len(set(ids))
    assert len(normalized_keys) == len(gate["brain_findings"])


# =============================================================================
# Phase 5 Body-Fit (BODY-01 / D-01, D-02) — variable-N conversation, no cage.
# RED until Task 2 rebuilds build_conversation to iterate direction["conversation"]
# (count = len), one card per London decision, no padding, no template banks.
# Expectations are DERIVED from each fixture's own gate count (anti-overfit) — never
# hard-coded to 5/6/7. Synthetic N=8 tests PAST the observed high end.
# =============================================================================


def test_conversation_is_variable_n(capture_directions, synthetic_n8_direction):
    # The displayed conversation count equals the director's as-authored decision count
    # for EVERY real capture (observed N = 3,5,6,7) AND for the synthetic N=8 — never
    # padded to 7, never clipped. Count is DERIVED from the fixture, not hard-coded.
    for name, direction in capture_directions.items():
        expected_n = len(direction["conversation"])
        entries = build_conversation({}, direction)
        assert len(entries) == expected_n, (
            f"capture {name}: expected {expected_n} conversation entries (London's authored N), "
            f"got {len(entries)} — the cage padded/clipped the real shape"
        )
        # gate label is the model's OWN label (carried verbatim), not a fixed scaffold.
        for index, read in enumerate(direction["conversation"]):
            assert entries[index]["gate"] == read["gate"]
            assert entries[index]["decision"] == read["decision"]

    # Past the observed high end (anti-overfit): an 8-decision direction yields 8 entries.
    n8_entries = build_conversation({}, synthetic_n8_direction)
    assert len(n8_entries) == 8, "an 8-decision synthetic must render 8 entries (never padded to 7)"


def test_no_template_banks_on_real_path(capture_directions):
    # Negative control (BODY-01): when a REAL direction["conversation"] is supplied, the
    # `_gate_question`/`_gate_critique` template-bank fallback strings must NEVER appear in
    # the built conversation — they are the deterministic relapse the pivot exists to kill.
    direction = capture_directions["product"]
    entries = build_conversation({}, direction)
    blob = json.dumps(entries)
    assert WORKBENCH_GATE_QUESTION_FALLBACK not in blob, "gate-question template bank leaked onto the real path"
    assert WORKBENCH_GATE_CRITIQUE_FALLBACK.split("{")[0].strip() not in blob, (
        "gate-critique template bank leaked onto the real path"
    )
    # Every critique on the real path is London's OWN prose (carried from the direction).
    for index, read in enumerate(direction["conversation"]):
        assert entries[index]["critique"] == read.get("critique", "")


def _unique(values) -> bool:
    realized = list(values)
    return len(set(realized)) == len(realized)
