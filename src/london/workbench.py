from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any

from .assets import normalize_palette, normalize_tags, pack_routes, route_assets, slugify
from .image_generation import build_image_prompt
from .session import DIRECTION_RESULT_KEY
from .text import clean_brief_text, clean_title, display_text

# HERO-03: artifact_type → an honest hero TYPE label. Describes WHAT London designed
# (the artifact), strictly orthogonal to the visual STATE (generated vs local board).
# A legacy prompt-card with a "Website mockup" label is still honestly non-generated.
ARTIFACT_LABELS = {
    "website": "Website mockup",
    "app": "App screen",
    "product": "Packaging concept",
    "brand": "Brand identity board",
    "generic": "Concept image",
}

# A5 (ENG-05/ENG-07): stage 2 now consumes the SAME DirectionResult stage 1 produced
# (carried on the pack under DIRECTION_RESULT_KEY) so a single director.direct() call
# drives BOTH stages. font_options/conversation/route_comparison are re-keyed on the
# director's structured font output — NOT on the relocated route-mode phrase-matcher.
# This DEFUSES the identical-fonts regression: with route titles now model-produced,
# phrase-matching dead campaign words against them would silently route every brief to
# the same fallback font set. The phrase-matcher lives ONLY in the deterministic
# director (it runs inside that director to build font tiers for the --offline path).


def enrich_workbench_pack(pack: dict[str, Any]) -> dict[str, Any]:
    """Attach the Pack Reader / Workbench view-model to a London Pack.

    Stage 2 of two. Consumes the DirectionResult stage 1 stashed on the pack and POPS
    it so it never reaches the public, additionalProperties:false london-pack.json.
    """

    direction = pack.pop(DIRECTION_RESULT_KEY, None)
    if not isinstance(direction, Mapping):
        direction = {}

    pack["conversation"] = build_conversation(pack, direction)
    pack["route_comparison"] = build_route_comparison(pack, direction)
    pack["font_options"] = build_font_options(pack, direction)
    pack["moodboard_tiles"] = build_moodboard_tiles(pack)
    pack["copy_blocks"] = build_copy_blocks(pack)
    pack["next_steps"] = build_next_steps(pack)
    pack["evidence_summary"] = build_evidence_summary(pack)
    return pack


def build_conversation(pack: Mapping[str, Any], direction: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    # D-01 / BODY-01: ONE pack entry per London decision — the conversation is London's
    # as-authored N (observed 3–7, treat as unbounded), count = len(reads). The cage that
    # iterated a FIXED 7 ``pack["gates"]``, index-mapped the reads onto those slots, and
    # filled the gaps with ``_gate_question``/``_gate_critique`` template banks is GONE.
    #
    # The model writes its OWN gate label (``read["gate"]``) and prose; rationale/critique/
    # answer are optional (D-02) and carried verbatim (empty stays empty — never backfilled
    # from a bank on the real path). The structural plumbing (evidence counts/findings/
    # sources/receipts) is Python-computed from the corresponding deterministic gate IF one
    # exists at the same ordinal (the offline RAG gates), else honest-empty — it never pads
    # the conversation and never injects bank text. This is the same open-list discipline as
    # ``build_route_comparison`` below (count = len, model prose, no fixed cardinality).
    reads = _as_mappings((direction or {}).get("conversation"))
    gates = _as_mappings(pack.get("gates"))
    entries: list[dict[str, Any]] = []
    for index, read in enumerate(reads):
        order = index + 1
        gate_label = display_text(read.get("gate"), fallback=f"Decision {order}")
        gate_id = slugify(gate_label) or f"gate-{order}"

        # Evidence is attached from the deterministic gate at the same ordinal when present
        # (the offline RAG plumbing builds those); a real model run with no aligned gate
        # carries honest-empty evidence rather than a fabricated or padded one.
        gate = gates[index] if index < len(gates) else {}
        findings = _dedupe_findings(_as_mappings(gate.get("brain_findings")))
        sources = _as_mappings(gate.get("sources_inspected"))
        receipts = _as_mappings(gate.get("receipts"))
        approval = _as_mappings(gate.get("approvals"))
        live_artifacts = [receipt for receipt in receipts if _is_live_artifact_receipt(receipt)]

        entries.append(
            {
                "id": gate_id,
                "order": order,
                "gate": gate_label,
                "answer": display_text(read.get("answer")),
                "decision": display_text(read.get("decision")),
                "rationale": display_text(read.get("rationale")),
                "critique": display_text(read.get("critique")),
                # `status` stays per-decision plumbing for the offline/deterministic path
                # (NOT a 7-cap, NOT template-bank text). The grader's measured signal
                # REPLACES the "approval ceremony" as the confidence source in Phase 5.1;
                # until then render.py reads this honest deterministic status.
                "status": display_text((approval[0] if approval else {}).get("status"), fallback="approved"),
                "answer_label": "London's read",
                "honesty_badges": ["Local inference", "No live interview"],
                "evidence_classes": {
                    "london_brain_findings": len(findings),
                    "source_targets": len(sources),
                    "live_artifacts": len(live_artifacts),
                },
                "evidence_count": len(findings) + len(sources) + len(live_artifacts),
                "brain_queries": [
                    {
                        "intent": display_text(query.get("intent"), fallback="brain query"),
                        "query": display_text(query.get("query")),
                    }
                    for query in _as_mappings(gate.get("brain_queries"))
                ],
                "brain_findings": [_finding_summary(finding) for finding in findings[:4]],
                "sources": [_source_summary(source) for source in sources[:4]],
                "receipts": [_receipt_summary(receipt) for receipt in receipts],
            }
        )
    return entries


def build_route_comparison(pack: Mapping[str, Any], direction: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    # The comparison prose (thesis/best_for/visual_world/type/palette_logic/steal/
    # do_not_copy/first_build_move/risk) is sourced from the director's route_comparison
    # when present; route_id stays Python-computed plumbing. The route-derived values are
    # the fallback (also model prose, since the route dict carries DirectionResult text).
    comparisons = _as_mappings((direction or {}).get("route_comparison"))
    risks = _as_strings(_nested(pack, "quality_review", "risks"))
    audience = display_text(_nested(pack, "research", "audience"), fallback="the first audience that must care")
    rows: list[dict[str, Any]] = []
    for index, route in enumerate(pack_routes(pack), start=1):
        palette = normalize_palette(route.get("palette"))
        sections = _as_mappings(route.get("sections"))
        first_section = sections[0] if sections else {}
        steal = _as_strings(route.get("steal") or route.get("steal_this"), fallback=("Steal the structural idea, not the surface.",))
        do_not = _as_strings(route.get("do_not_copy") or route.get("dont_copy"), fallback=("Do not copy exact styling, assets, or source composition.",))
        cmp = comparisons[index - 1] if index - 1 < len(comparisons) else {}

        rows.append(
            {
                "route_id": display_text(route.get("id"), fallback=slugify(display_text(route.get("title"), fallback=f"route-{index}"))),
                "title": display_text(cmp.get("title") or route.get("title"), fallback=f"Route {index}"),
                "thesis": _public_comparison_thesis(cmp, route, pack, first_section),
                "best_for": display_text(
                    cmp.get("best_for"),
                    fallback=f"{audience} when the first build needs {display_text(first_section.get('title'), fallback='a clear product proof').lower()}.",
                ),
                "visual_world": display_text(cmp.get("visual_world") or route.get("mood") or route.get("lore"), fallback="Specific, product-led, and evidence-aware."),
                "type": display_text(cmp.get("type") or route.get("type") or route.get("typography"), fallback=display_text(_nested(pack, "typography_color", "type_system"))),
                "palette_logic": _public_palette_logic(cmp.get("palette_logic"), palette),
                "steal": display_text(cmp.get("steal"), fallback=steal[0]),
                "do_not_copy": display_text(cmp.get("do_not_copy"), fallback=do_not[0]),
                "first_build_move": display_text(
                    cmp.get("first_build_move"),
                    fallback=f"{display_text(first_section.get('title'), fallback='First proof')}: {display_text(first_section.get('body'), fallback=display_text(route.get('rationale')))}",
                ),
                "risk": display_text(cmp.get("risk"), fallback=risks[(index - 1) % len(risks)] if risks else "The route gets weaker if it becomes generic decoration."),
            }
        )
    return rows


def _public_comparison_thesis(
    comparison: Mapping[str, Any],
    route: Mapping[str, Any],
    pack: Mapping[str, Any],
    first_section: Mapping[str, Any],
) -> str:
    for value in (
        comparison.get("thesis"),
        route.get("public_thesis"),
        route.get("visual_read"),
        route.get("visualRead"),
        route.get("rationale"),
        route.get("subhead"),
        first_section.get("body"),
        route.get("headline"),
        route.get("thesis"),
        route.get("title"),
    ):
        text = display_text(value)
        if text and not _is_promptish_public_line(text, pack):
            return text
    return display_text(route.get("title"), fallback="Route direction")


def _is_promptish_public_line(value: Any, pack: Mapping[str, Any]) -> bool:
    text = display_text(value)
    if not text:
        return False
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    brief_title = display_text(pack.get("title") or pack.get("brief")).lower()
    brief_title = re.sub(r"[^a-z0-9]+", " ", brief_title).strip()
    promptish_start = normalized.startswith(("make ", "turn "))
    briefish = "product brief" in normalized or (brief_title and brief_title in normalized)
    harness_tail = "answer the first real decision" in normalized or "route people can compare" in normalized
    return promptish_start and (briefish or harness_tail)


def _public_palette_logic(value: Any, palette: Sequence[Mapping[str, Any]]) -> str:
    text = display_text(value)
    lowered = text.lower()
    if text and not any(marker in lowered for marker in ("#", "receipt", "proof", "sha", "provider", "fallback")):
        return text
    parts = []
    for color in palette:
        role = display_text(color.get("role"))
        name = display_text(color.get("name"))
        if not role and not name:
            continue
        public_role = "evidence" if role.lower() in {"proof", "receipt"} else role
        public_name = name.replace("Receipt", "Evidence").replace("receipt", "evidence")
        parts.append(f"{public_role}: {public_name}" if public_role else public_name)
    return "; ".join(parts)


def build_font_options(pack: Mapping[str, Any], direction: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Re-keyed (A5) on the director's ``font_options`` (3 tiers/route), NOT on the
    deterministic route-mode phrase-matcher.

    The director already returns schema-shaped font tiers (each carrying the required
    ``why_this_route_not_other_route``); workbench KEEPS the public OUTPUT SHAPE by
    adding the Python-plumbing fields the public schema requires but the model does not
    write (``route_id``, per-option ``id``/``label``/``sample_headline``/``sample_body``).

    This DEFUSES the fallback-to-manual regression: with route titles now model-produced,
    phrase-matching dead campaign words against them would collapse every brief to the
    same fallback font set. Keying on the model's per-route font tiers gives unrelated
    routes genuinely distinct fonts. The phrase-matcher survives ONLY inside the
    deterministic director (it runs there to build the --offline font tiers).
    """

    font_groups = _as_mappings((direction or {}).get("font_options"))
    routes = pack_routes(pack)
    # Map each route by title so the model's per-route font group attaches to the right
    # route_id / sample text even if ordering differs.
    routes_by_title = {display_text(route.get("title")): route for route in routes}

    groups: list[dict[str, Any]] = []
    for index, group in enumerate(font_groups):
        route_title = display_text(group.get("route_title"), fallback=f"Route {index + 1}")
        route = routes_by_title.get(route_title) or (routes[index] if index < len(routes) else {})
        route_id = display_text(route.get("id"), fallback=slugify(route_title))
        sections = _as_mappings(route.get("sections"))
        first_section = sections[0] if sections else {}
        sample_headline = display_text(route.get("title"), fallback=route_title)
        sample_body = display_text(route.get("subhead") or route.get("rationale"), fallback=clean_brief_text(pack))
        sample_label = display_text(first_section.get("title"), fallback="Route label")
        options: list[dict[str, Any]] = []
        for option in _as_mappings(group.get("options")):
            tier = display_text(option.get("tier"), fallback="safe_local")
            name = display_text(option.get("name"), fallback=f"{route_title} {tier.replace('_', ' ').title()}")
            option_payload = {
                "id": f"{slugify(route_title)}-{tier}",
                "tier": tier,
                "label": display_text(option.get("label"), fallback=tier.replace("_", " ").title()),
                "name": name,
                "headline_font": display_text(option.get("headline_font"), fallback=name),
                "body_font": display_text(option.get("body_font"), fallback=name),
                "label_font": display_text(option.get("label_font"), fallback=name),
                "fallback_stack": display_text(option.get("fallback_stack"), fallback="system-ui, sans-serif"),
                "sample_headline": sample_headline,
                "sample_body": sample_body,
                "sample_label": sample_label,
                "best_use": display_text(option.get("best_use")),
                "why_london_chose_it": display_text(option.get("why_london_chose_it")),
                "why_this_route_not_other_route": display_text(
                    option.get("why_this_route_not_other_route"),
                    fallback=f"{route_title} needs this voice; the other route reads too differently to share it.",
                ),
                "what_makes_it_wrong": display_text(option.get("what_makes_it_wrong")),
                "import_hint": display_text(option.get("import_hint")),
            }
            if isinstance(option.get("font_preview"), Mapping):
                option_payload["font_preview"] = dict(option["font_preview"])
            options.append(option_payload)
        groups.append(
            {
                "route_id": route_id,
                "route_title": route_title,
                "options": options,
            }
        )
    return groups


def build_moodboard_tiles(pack: Mapping[str, Any]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    motion = _as_strings(_nested(pack, "build_motion", "motion_principles"), fallback=("One deliberate motion beat should prove the product ritual.",))
    for route in pack_routes(pack):
        route_id = display_text(route.get("id"), fallback=slugify(display_text(route.get("title"), fallback="route")))
        route_title = display_text(route.get("title"), fallback="Route")
        palette = normalize_palette(route.get("palette"))
        assets = route_assets(route)
        hero_asset = assets[0]
        is_live_asset = bool(hero_asset.get("live_artifact")) or not bool(hero_asset.get("deterministic", True))
        hero_kind_raw = display_text(hero_asset.get("kind"))
        sections = _as_mappings(route.get("sections"))
        hero_title = _public_moodboard_hero_title(route, hero_asset)
        hero_caption = _public_moodboard_hero_caption(route, hero_asset, sections)
        hero_tags = ["visual direction", "route language"]
        if hero_kind_raw == "visual-direction-board":
            hero_kind = "visual-direction-board"
        elif hero_kind_raw in {"manual-prompt-card", "generation-unavailable"}:
            hero_kind = hero_kind_raw
        elif hero_kind_raw == "fixture-system-sketch":
            hero_kind = "fixture-system-sketch"
            hero_tags = ["visual direction", "system sketch"]
        elif is_live_asset:
            hero_kind = "generated-concept-image"
            hero_tags = ["visual direction", "image route"]
        else:
            hero_kind = "manual-prompt-card"
        steal = _as_strings(route.get("steal"), fallback=("Use the strongest structural behavior as the visual rule.",))
        avoid = _as_strings(route.get("do_not_copy"), fallback=("Avoid copying the source surface.",))
        first = sections[0] if sections else {}
        second = sections[1] if len(sections) > 1 else first

        tiles = [
            {
                "id": f"{route_id}-hero",
                "kind": hero_kind,
                "title": hero_title,
                "caption": hero_caption,
                **(
                    {"honesty_note": "Visual direction board, not generated concept art."}
                    if hero_kind == "visual-direction-board"
                    else {}
                ),
                "span": "hero",
                "annotation": display_text(route.get("rationale"), fallback=display_text(route.get("headline"))),
                "constraint_tags": list(normalize_tags(route.get("tags"), defaults=("route direction", "visual system"))) + hero_tags,
                "tension_pair": {"wants": steal[0], "avoid": avoid[0]},
                "prompt": display_text(hero_asset.get("prompt")),
                "copy_label": display_text(hero_asset.get("copy_label"), fallback="Copy image prompt"),
            },
            {
                "id": f"{route_id}-palette",
                "kind": "palette-strip",
                "title": "Palette as product state",
                "caption": display_text(_nested(pack, "typography_color", "color_system")),
                "colors": palette,
                "span": "rail",
                "annotation": display_text(_nested(pack, "typography_color", "color_system"), fallback="Use color as state language before decoration."),
                "constraint_tags": ["state color", "contrast check"],
            },
            {
                "id": f"{route_id}-type",
                "kind": "type-specimen",
                "title": "Type specimen",
                "caption": display_text(route.get("type"), fallback=display_text(_nested(pack, "typography_color", "type_system"))),
                "sample": route_title,
                "span": "medium",
                "annotation": display_text(_nested(pack, "typography_color", "type_system")),
                "constraint_tags": ["headline", "body", "label"],
            },
            {
                "id": f"{route_id}-product-moment",
                "kind": "product-moment",
                "title": display_text(first.get("title"), fallback="Product moment"),
                "caption": display_text(first.get("body"), fallback=display_text(route.get("subhead"))),
                "span": "wide",
                "annotation": "",
                "constraint_tags": ["first build move", "object proof"],
            },
            {
                "id": f"{route_id}-interface-frame",
                "kind": "interface-frame",
                "title": display_text(second.get("title"), fallback="Interface frame"),
                "caption": display_text(second.get("body"), fallback=display_text(route.get("mood"))),
                "span": "medium",
                "annotation": "",
                "constraint_tags": ["desktop frame", "mobile frame"],
            },
            {
                "id": f"{route_id}-object",
                "kind": "object-packaging",
                "title": "Object / packaging cue",
                "caption": display_text(route.get("lore"), fallback=display_text(pack.get("vessel_interface_expression"))),
                "span": "small",
                "annotation": "",
                "constraint_tags": ["material", "ritual", "scale"],
            },
            {
                "id": f"{route_id}-motion",
                "kind": "motion-idea",
                "title": "Motion beat",
                "caption": motion[0],
                "span": "small",
                "annotation": "",
                "constraint_tags": ["scroll", "hover", "state"],
            },
        ]
        if hero_asset.get("src"):
            tiles[0]["asset_src"] = hero_asset["src"]
            tiles[0]["asset_alt"] = display_text(hero_asset.get("alt"), fallback=hero_title)
        # HERO-03: the hero tile carries an honest artifact TYPE label read AS GIVEN from
        # pack["artifact_type"] (orthogonal to hero "kind"/visual-state — the label never
        # alters the 3-state honesty). moodboardTile has no additionalProperties:false.
        tiles[0]["artifact_label"] = ARTIFACT_LABELS.get(display_text(pack.get("artifact_type")), "Concept image")
        groups.append({"route_id": route_id, "route_title": route_title, "tiles": tiles})
    return groups


def _public_moodboard_hero_title(route: Mapping[str, Any], asset: Mapping[str, Any]) -> str:
    for value in (
        asset.get("title"),
        route.get("title"),
        route.get("headline"),
    ):
        text = _public_moodboard_copy(value)
        if text:
            return text
    return "Route visual direction"


def _public_moodboard_hero_caption(
    route: Mapping[str, Any], asset: Mapping[str, Any], sections: Sequence[Mapping[str, Any]]
) -> str:
    section = sections[0] if sections else {}
    for value in (
        asset.get("caption"),
        asset.get("alt"),
        route.get("visual_read"),
        route.get("visualRead"),
        route.get("image_direction"),
        route.get("rationale"),
        route.get("headline"),
        section.get("body"),
        route.get("subhead"),
    ):
        text = _public_moodboard_copy(value)
        if text:
            return text
    return ""


def _public_moodboard_copy(value: Any) -> str:
    text = display_text(value)
    if not text:
        return ""
    lowered = text.lower()
    status_markers = (
        "actual font loaded",
        "asset_sha256",
        "copy the prompt",
        "fallback",
        "fixture",
        "gemini pro",
        "generated gemini",
        "generated openai",
        "generated proof",
        "generated route visual",
        "generated_live",
        "gpt-image",
        "image generation was disabled",
        "image generation was requested",
        "local_fallback",
        "manual prompt",
        "manual-prompt",
        "no real image generator",
        "not generated",
        "provider",
        "public proof",
        "receipt",
        "requested:",
        "sha256",
        "status:",
        "direction board",
        "visual direction board",
    )
    if any(marker in lowered for marker in status_markers):
        return ""
    return text


def build_copy_blocks(pack: Mapping[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [
        {
            "id": "ask-london-next",
            "scope": "global",
            "kind": "ask_london",
            "label": "Ask London Next",
            "text": (
                f"Review this London Pack for {clean_title(pack)}. Push on the category assumption, name the route that feels least generic, "
                "and tell me which visual proof should be built first."
            ),
        },
        {
            "id": "source-research-prompt",
            "scope": "global",
            "kind": "source_research",
            "label": "Source Research Prompt",
            "text": (
                f"Find actual showcased work for {clean_title(pack)}. Prioritize detail pages and artifact pages over gallery chrome. "
                f"Use this reframe: {display_text(pack.get('london_reframe'))}"
            ),
        },
    ]

    for route in pack_routes(pack):
        route_id = display_text(route.get("id"), fallback=slugify(display_text(route.get("title"), fallback="route")))
        route_title = display_text(route.get("title"), fallback="Route")
        palette = normalize_palette(route.get("palette"))
        font_stack = _first_font_stack(route, pack)
        blocks.extend(
            [
                {
                    "id": f"{route_id}-image-prompt",
                    "scope": "route",
                    "route_id": route_id,
                    "kind": "image_prompt",
                    "label": f"{route_title} Image Prompt",
                    "text": _image_prompt(route, pack),
                },
                {
                    "id": f"{route_id}-builder-prompt",
                    "scope": "route",
                    "route_id": route_id,
                    "kind": "builder_prompt",
                    "label": f"{route_title} Builder Prompt",
                    "text": _builder_prompt(route, pack),
                },
                {
                    "id": f"{route_id}-css-vars",
                    "scope": "route",
                    "route_id": route_id,
                    "kind": "css_variables",
                    "label": f"{route_title} CSS Variables",
                    "text": _css_variables(palette, font_stack),
                },
                {
                    "id": f"{route_id}-route-summary",
                    "scope": "route",
                    "route_id": route_id,
                    "kind": "route_summary",
                    "label": f"{route_title} Summary",
                    "text": f"{route_title}: {display_text(route.get('headline'))}\n\n{display_text(route.get('rationale'))}",
                },
                {
                    "id": f"{route_id}-critique-prompt",
                    "scope": "route",
                    "route_id": route_id,
                    "kind": "critique_prompt",
                    "label": f"{route_title} Critique Prompt",
                    "text": (
                        f"Critique {route_title} for {clean_title(pack)}. Reject anything that feels like {display_text(pack.get('anti_position'))}. "
                        f"Check the first build move, type system, palette logic, and whether the route proves: {display_text(route.get('headline'))}"
                    ),
                },
            ]
        )
    return blocks


def build_next_steps(pack: Mapping[str, Any]) -> list[dict[str, Any]]:
    steps = [
        {
            "id": "compare-routes",
            "label": "Compare routes",
            "description": "Use the matrix to pick the route with the strongest product case, not the prettiest surface.",
            "action_type": "local-workbench",
        },
        {
            "id": "inspect-evidence",
            "label": "Inspect evidence",
            "description": "Open the evidence drawer and verify the source trail before presenting the pack.",
            "action_type": "local-workbench",
        },
        {
            "id": "refine-type",
            "label": "Refine type",
            "description": "Use Font Lab to choose a safe local stack now and a public/premium direction for later art direction.",
            "action_type": "handoff",
        },
    ]
    for route in pack_routes(pack):
        route_id = display_text(route.get("id"), fallback=slugify(display_text(route.get("title"), fallback="route")))
        route_title = display_text(route.get("title"), fallback="Route")
        sections = _as_mappings(route.get("sections"))
        first_section = sections[0] if sections else {}
        first_section_title = display_text(first_section.get("title"), fallback=route_title)
        steps.append(
            {
                "id": f"build-{route_id}",
                "label": f"Build {route_title}",
                "description": f"Start with {first_section_title} and make the {route_title} route concrete.",
                "action_type": "prototype",
                "target_route_id": route_id,
            }
        )
    steps.append(
        {
            "id": "reject-generic",
            "label": "Reject generic output",
            "description": f"Kill any direction that collapses into: {display_text(pack.get('anti_position'), fallback='generic modern-clean filler')}.",
            "action_type": "quality-review",
        }
    )
    return steps


def build_evidence_summary(pack: Mapping[str, Any]) -> dict[str, Any]:
    source_map: dict[str, dict[str, Any]] = {}
    brain_groups = []
    for gate in _as_mappings(pack.get("gates")):
        deduped_findings = _dedupe_findings(_as_mappings(gate.get("brain_findings")))
        findings = [_finding_summary(finding) for finding in deduped_findings[:4]]
        brain_groups.append(
            {
                "gate_id": display_text(gate.get("gate_id")),
                "gate": display_text(gate.get("gate_name")),
                "finding_count": len(deduped_findings),
                "evidence_class": "London Brain Finding",
                "findings": findings,
            }
        )
        for source in _as_mappings(gate.get("sources_inspected")):
            summary = _source_summary(source)
            source_map[summary["source_id"]] = summary | {
                "status": "planned-reference",
                "evidence_class": "Source Target",
                "claim": "Registry/source-plan evidence; provider browsing receipt not present.",
            }

    source_plan = pack.get("source_plan") if isinstance(pack.get("source_plan"), Mapping) else {}
    for source in _as_mappings(source_plan.get("sources") if isinstance(source_plan, Mapping) else []):
        source_id = display_text(source.get("slug") or source.get("source_id"), fallback=slugify(display_text(source.get("name"), fallback="source")))
        source_map.setdefault(
            source_id,
            {
                "source_id": source_id,
                "title": display_text(source.get("name") or source.get("title"), fallback=source_id),
                "path": display_text(source.get("homepage") or source.get("path")),
                "notes": [display_text(source.get("use_for")), f"Avoid: {display_text(source.get('avoid'))}"],
                "status": "planned-reference",
                "evidence_class": "Source Target",
                "claim": "Source registry entry; extraction must target actual detail/artifact pages.",
            },
        )

    receipts = [_receipt_summary(receipt) for receipt in _as_mappings(pack.get("receipts"))]
    providers = sorted(
        {
            display_text(receipt.get("provider"), fallback="local")
            for receipt in _as_mappings(pack.get("receipts"))
            if display_text(receipt.get("provider"))
        }
    )
    return {
        "brain": brain_groups,
        "sources": list(source_map.values()),
        "providers": [
            {
                "provider": provider,
                "status": "receipt-recorded",
                "notes": "Deterministic local provider or optional capability; no secret value is exposed.",
            }
            for provider in providers
        ],
        "receipts": receipts,
        "live_artifacts": [
            receipt | {"evidence_class": "Live Artifact", "status": "receipt-recorded"}
            for receipt in receipts
            if _is_live_artifact_receipt(receipt)
        ],
        "source_claim": "This pack separates London Brain Findings, Source Targets, and Live Artifacts. Source targets are planned unless a live receipt proves fetched or generated work.",
    }


def _is_live_artifact_receipt(receipt: Mapping[str, Any]) -> bool:
    live_providers = {
        "gemini",
        "bfl",
        "openai",
        "fal",
        "replicate",
        "pollinations",
        "automatic1111",
        "comfyui",
        "draw-things",
        "external-cmd",
    }
    return (
        display_text(receipt.get("status")) == "generated_live"
        and display_text(receipt.get("generation_mode")) == "provider-backed"
        and display_text(receipt.get("provider")) in live_providers
    )


def _image_prompt(route: Mapping[str, Any], pack: Mapping[str, Any]) -> str:
    # GATE-03: read artifact_type AS GIVEN from the pack (no re-derivation).
    return build_image_prompt(pack, route, artifact_type=pack.get("artifact_type", "generic"))


def _builder_prompt(route: Mapping[str, Any], pack: Mapping[str, Any]) -> str:
    sections = "; ".join(display_text(section.get("title")) for section in _as_mappings(route.get("sections"))[:3])
    return (
        f"Build a static first-pass web prototype for {clean_title(pack)} using the {display_text(route.get('title'))} route. "
        f"Use the thesis '{display_text(route.get('headline'))}', sections: {sections}, palette as state language, and this anti-position: {display_text(pack.get('anti_position'))}."
    )


def _css_variables(palette: Sequence[Mapping[str, Any]], font_stack: str) -> str:
    lines = [":root {"]
    for index, color in enumerate(palette, start=1):
        role = slugify(display_text(color.get("role"), fallback=f"color-{index}"))
        lines.append(f"  --london-{role}: {display_text(color.get('hex'))};")
    lines.append(f"  --london-headline-font: {font_stack};")
    lines.append("}")
    return "\n".join(lines)


def _first_font_stack(route: Mapping[str, Any], pack: Mapping[str, Any]) -> str:
    # Safe-local stack for CSS-variable copy blocks. A5: sourced from the director's
    # font tiers, read off the pack's already-built font_options (set by
    # enrich_workbench_pack before build_copy_blocks runs). The first tier (safe_local)
    # carries the local fallback stack — no phrase-matcher on the default path.
    route_id = display_text(route.get("id"), fallback=slugify(display_text(route.get("title"), fallback="route")))
    route_title = display_text(route.get("title"))
    for group in _as_mappings(pack.get("font_options")):
        if display_text(group.get("route_id")) == route_id or display_text(group.get("route_title")) == route_title:
            options = _as_mappings(group.get("options"))
            if options:
                stack = display_text(options[0].get("fallback_stack"))
                if stack:
                    return stack
    return "system-ui, -apple-system, Segoe UI, Roboto, sans-serif"


def _finding_summary(finding: Mapping[str, Any]) -> dict[str, Any]:
    title = _strip_markdown(display_text(finding.get("title")))
    body = _strip_markdown(display_text(finding.get("body")))
    category = display_text(finding.get("category"))
    source_ref = display_text(finding.get("source_ref"))
    return {
        "id": display_text(finding.get("id")),
        "category": category,
        "title": title,
        "body": body,
        "source_ref": source_ref,
        "evidence_class": f"London Brain Finding / {_friendly_category(category)}",
        "insight_title": title,
        "why_london_used_this": _why_london_used_finding(title, body),
        "matched_terms": _as_strings(finding.get("matched_terms"), fallback=()),
        "debug": {
            "source_ref": source_ref,
            "category": category,
            "score": display_text(finding.get("score")),
        },
    }


def _source_summary(source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_id": display_text(source.get("source_id") or source.get("slug")),
        "title": display_text(source.get("title") or source.get("name")),
        "path": display_text(source.get("path") or source.get("homepage")),
        "notes": _as_strings(source.get("notes"), fallback=()),
        "evidence_class": "Source Target",
        "status": display_text(source.get("status"), fallback="planned-reference"),
        "why_london_used_this": "Planned target for actual showcased work; not treated as live evidence without a receipt.",
    }


def _receipt_summary(receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "receipt_id": display_text(receipt.get("receipt_id")),
        "kind": display_text(receipt.get("kind")),
        "summary": display_text(receipt.get("summary")),
        "provider": display_text(receipt.get("provider")),
        "status": display_text(receipt.get("status")),
        "generation_mode": display_text(receipt.get("generation_mode")),
        "deterministic": bool(receipt.get("deterministic", True)),
    }


def _dedupe_findings(findings: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    deduped: list[Mapping[str, Any]] = []
    seen_ids: set[str] = set()
    seen_keys: set[tuple[str, str, str]] = set()
    seen_near: set[tuple[str, str, str]] = set()
    for finding in findings:
        finding_id = display_text(finding.get("id"))
        if finding_id:
            if finding_id in seen_ids:
                continue
            seen_ids.add(finding_id)

        source_ref = display_text(finding.get("source_ref"))
        title = _normal_key(display_text(finding.get("title")))
        category = _normal_key(display_text(finding.get("category")))
        exact_key = (source_ref, title, category)
        if exact_key in seen_keys:
            continue
        seen_keys.add(exact_key)

        body = _normal_key(display_text(finding.get("body")))[:160]
        near_key = (title, body, category)
        if near_key in seen_near:
            continue
        seen_near.add(near_key)
        deduped.append(finding)
    return deduped


def _normal_key(value: str) -> str:
    return re.sub(r"\s+", " ", _strip_markdown(value).lower()).strip()


def _strip_markdown(value: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    text = re.sub(r"[*_`#>]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _friendly_category(category: str) -> str:
    return {
        "principles": "Principle",
        "resources": "Resource",
        "visual_examples": "Visual Example",
        "critique_approaches": "Critique Approach",
        "product_concepts": "Product Concept",
        "tools": "Tool",
        "workflow_steps": "Workflow Step",
        "lessons": "Lesson",
    }.get(category, category.replace("_", " ").title() or "Finding")


def _why_london_used_finding(title: str, body: str) -> str:
    if body:
        return body if len(body) <= 220 else f"{body[:217].rstrip()}..."
    if title:
        return f"London used this because it gives the route a specific design constraint: {title}."
    return "London used this as a brain finding attached to the gate decision."


def _as_mappings(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _as_strings(value: Any, fallback: Sequence[str] = ()) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else list(fallback)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        strings = [display_text(item) for item in value if display_text(item)]
        return strings or list(fallback)
    text = display_text(value)
    return [text] if text else list(fallback)


def _nested(mapping: Mapping[str, Any], *keys: str) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current
