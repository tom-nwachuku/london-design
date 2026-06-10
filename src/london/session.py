from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
from pathlib import Path
from typing import Any

from london.assets import fallback_routes, slugify
from london import brain_loader
from london.brain import LondonBrain
from london.director import (
    CreativeDirector,
    DirectionRequest,
    DirectionResult,
    OfflineDirector,
    ROUTE_SYNTHESIS_PROVIDER,
    CreativeLane,
    RunTelemetry,
    SessionLane,
)
from london import grader
from london.library import DEFAULT_BRAIN_DB, QueryHit
from london.models import GATE_IDS, GATE_NAMES
from london.persona import (
    GATE_QUERY_TEMPLATES,
    INTAKE_QUESTIONS,
    PERSONA_LABEL,
)
from london.route_refs import canonicalize_route_ref
from london.source_packs import SourcePlan, build_source_plan

PACK_VERSION = "0.3.0"
BRAIN_FINDINGS_CAP = 10
FOCUSED_FINDINGS_CAP = 6

# A5 (ENG-05/ENG-07): the default path is now director-driven. The resolved director
# (ClaudeCodeDirector by default / OfflineDirector for --offline / FakeDirector in
# tests) is threaded in from write_london_pack and produces ALL creative text as one
# DirectionResult (D-07). The deterministic gate plumbing (brain RAG queries, intake
# structure, source plan, the 7-gate loop) STAYS here and FEEDS the DirectionRequest;
# it no longer authors any public creative prose.
#
# When no director is injected (the offline parity oracle — direct run_london_session
# calls in tests, and the labeled --offline path), it defaults to OfflineDirector so
# the deterministic suite stays green byte-for-byte. The default model path NEVER
# reaches this default — write_london_pack always threads an explicit director.
_OFFLINE_DIRECTOR = OfflineDirector()

# The lane dataclasses are re-imported from director.py because the STAYING gate
# plumbing reads lane fields (product_noun/aesthetic/label/audience/...) to build the
# brain-RAG queries and intake answers — those are deterministic facts, NOT public
# creative prose, so they continue to come from the deterministic lane synthesis.

# GATE_QUERY_TEMPLATES and INTAKE_QUESTIONS are single-sourced in persona.py (WALK-01)
# and imported above. GENERAL_BRAIN_CATEGORIES stays here: it is a brain-category filter,
# not persona/gate data.
#
# SCOPE after the 04.6-05 real-engine wiring (ENGINE-02): this 5-of-9 filter NO LONGER
# constrains the default model path. The default director (ClaudeCodeDirector) lets the
# host model query its OWN brain adaptively through the brain MCP (london_brain_query),
# which returns the FULL 10-field findings across ALL 9 categories with NO category
# pre-filter and NO title truncation — the rewired build_seed_prompt deliberately ignores
# request.brain_findings, so this filter never reaches the model.
#
# The filter now governs ONLY the DETERMINISTIC offline gate RAG below (_query_brain ->
# _general_brain_hits -> the per-gate findings the OfflineDirector's gate_rationale reads).
# It is kept intact there on purpose: the existing deterministic suite is the OfflineDirector
# parity oracle (byte-for-byte), so removing the filter would change offline behavior and
# break parity. The default path is unfiltered (via the MCP); the offline path keeps its
# deterministic 5-of-9 behavior. See 04.6-05-SUMMARY.md.
GENERAL_BRAIN_CATEGORIES = {"principles", "critique_approaches", "workflow_steps", "tools", "resources"}

# GATE-01/02: the constrained artifact set (website|app|product|brand|generic). Single-
# sourced here for the brief front-matter parse + resolution; the CLI flag parse, the
# DirectionResult Literal, and the schema enum all carry the SAME 5 values. generic is the
# honest floor (a deterministic path / unknown signal never guesses a specific type).
ARTIFACT_TYPES = ("website", "app", "product", "brand", "generic")

# Private pack key carrying the resolved artifact_type RESOLUTION SOURCE
# (flag | brief | model | generic-default) forward to write_london_pack so it can build the
# auditable artifact-resolution receipt. Like DIRECTION_RESULT_KEY this is popped before the
# pack is validated/written (the schema is additionalProperties:false).
ARTIFACT_RESOLUTION_KEY = "_artifact_resolution"

# Private pack key carrying the stage-1 DirectionResult forward to stage 2
# (enrich_workbench_pack) so a single director.direct() call drives BOTH stages
# (D-07). enrich_workbench_pack POPS this before the pack is validated/written, so it
# never reaches the public london-pack.json (the schema is additionalProperties:false).
DIRECTION_RESULT_KEY = "_direction_result"


def run_london_session(
    brief: str | Path | Mapping[str, Any],
    *,
    brain: LondonBrain | None = None,
    fixture: bool = False,
    director: CreativeDirector | None = None,
    artifact_type: str | None = None,
    visual_selection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the canonical London seven-gate session and return a public pack.

    Stage 1 of two (the other is :func:`workbench.enrich_workbench_pack`). The
    deterministic plumbing — ``_coerce_brief``, the per-gate brain-RAG loop, and the
    source plan — STAYS and feeds a :class:`DirectionRequest`; the resolved ``director``
    then produces ALL creative text in ONE :meth:`CreativeDirector.direct` call (D-07).
    Every public lane/route prose field is sourced from that ``DirectionResult``; no
    template bank authors creative text on the default path (ENG-05/ENG-07).

    ``director`` defaults to the deterministic :class:`OfflineDirector` so direct
    test calls (and the labeled ``--offline`` path) keep byte-for-byte parity; the
    default model path always threads an explicit director from ``write_london_pack``.
    """

    director = director or _OFFLINE_DIRECTOR
    brief_input = _read_brief_once(brief)
    brief_record = _coerce_brief(brief_input)
    # GATE-02 resolution (flag > brief > model > generic). The flag value (CLI --artifact)
    # arrives as the artifact_type param; the brief value was parsed off the front-matter in
    # _coerce_brief (unknown -> "generic", never crash — V5). Both are CLI-time facts known
    # BEFORE direct(), so thread the flag/brief value onto the DirectionRequest below so the
    # in-session model can HONOR a declared type. The model declaration + final precedence
    # are resolved AFTER direct() returns.
    # A flag/brief value counts as a signal only when it coerces to a SPECIFIC type; an
    # unknown value (coerced to "generic") is NOT a specific assertion, so it falls through
    # to the honest generic-default (never a faked specific type — GATE-02). The brief value
    # is read off the front-matter separately (NEVER on the schema-pure brief record).
    flag_coerced = _coerce_artifact_value(artifact_type) if artifact_type is not None else None
    flag_value = flag_coerced if flag_coerced and flag_coerced != "generic" else None
    brief_value = _parse_brief_artifact(brief_input)
    declared_for_model = flag_value or brief_value or "generic"
    # Deterministic gate plumbing: a lane drives the brain-RAG queries + intake
    # structure (facts, not public prose). This stays regardless of which director
    # authors the creative text below.
    lane = _OFFLINE_DIRECTOR.synthesize_lane(brief_record)
    brain = brain or LondonBrain(brain_loader.resolve_brain_path())
    source_plan = build_source_plan(f"{brief_record['text']}\n{lane.source_terms}")
    gates = [_run_gate(index + 1, gate_id, brief_record, lane, source_plan, brain) for index, gate_id in enumerate(GATE_IDS)]

    # ONE structured call (D-07): the deterministic facts feed the request; the
    # director returns every creative-text field as a DirectionResult AND a
    # structurally-separate RunTelemetry side-channel (GRADE-01 / D-05). The telemetry is
    # the OBJECTIVE record of what the engine actually did (real brain queries + the source
    # IDs the brain returned) — London does not grade his own homework, so it is returned
    # ALONGSIDE the DirectionResult, never fused into it.
    request = _direction_request(
        brief_record,
        lane,
        gates,
        source_plan,
        artifact_type=declared_for_model,
        visual_selection=visual_selection,
    )
    direction, telemetry = _direct_with_telemetry(director, request)
    creative = direction.model_dump()

    # GATE-02 final resolution + provenance. flag beats brief beats model beats generic; a
    # deterministic path emits "generic" so a no-signal offline run resolves to
    # "generic-default". The model declaration counts only when it is a SPECIFIC type (the
    # deterministic floor "generic" is never treated as a model assertion).
    model_value = creative.get("artifact_type") or "generic"
    if flag_value:
        resolved_artifact_type, artifact_source = flag_value, "flag"
    elif brief_value:
        resolved_artifact_type, artifact_source = brief_value, "brief"
    elif model_value != "generic":
        resolved_artifact_type, artifact_source = model_value, "model"
    else:
        resolved_artifact_type, artifact_source = "generic", "generic-default"

    routes = (
        fallback_routes({"title": brief_record["title"], "brief": brief_record})
        if fixture
        else _routes_from_direction(creative, brief_record)
    )
    creative["recommended_route_ref"] = canonicalize_route_ref(creative["recommended_route_ref"], routes)
    route_titles = [route["title"] for route in routes]

    # Fold the director's per-gate conversation decision/rationale into the gate
    # decisions so stage-2 build_conversation reads model prose, not template banks.
    _apply_direction_to_gates(gates, creative)

    gates_by_id = {str(gate.get("gate_id")): gate for gate in gates}
    image_gate = gates_by_id.get("image_direction", {})
    critique_gate = gates_by_id.get("quality_review", {})

    pack: dict[str, Any] = {
        "pack_id": f"london-pack-{brief_record['digest']}",
        "version": PACK_VERSION,
        "mode": "scripted-local",
        "title": brief_record["title"],
        "summary": brief_record["text"],
        "brief": brief_record,
        "session_lane": _lane_to_dict(lane, creative),
        "reference_packs": [],
        "gates": gates,
        "research": {
            "audience": creative["audience"],
            "category_tension": creative["aesthetic_void"],
            "evidence_plan": _source_references(source_plan),
        },
        "creative_direction": {
            "positioning": creative["london_reframe"],
            "voice": creative["voice"],
            "concept_routes": route_titles,
        },
        "typography_color": {
            "type_system": creative["type_system"],
            "color_system": creative["color_system"],
            "accessibility_notes": [
                "Every palette includes an ink/paper contrast pair for readable exports.",
                "Accent colors are assigned to product states before decorative use.",
                "Type choices must be checked against real applied references before a live build.",
            ],
        },
        "image_direction": {
            "art_direction": lane.image_direction,
            "shot_list": list(lane.shot_list),
            "generation_constraints": list(lane.generation_constraints),
        },
        "layout_mockups": {
            "routes": route_titles,
            "wireframes": [section["title"] for route in routes for section in route.get("sections", [])][:6],
            "components": _components_from_direction(creative),
        },
        "build_motion": {
            "prototype_plan": f"Render a static first-pass prototype for {creative['label']} from the approved route sections.",
            "motion_principles": list(lane.motion_principles),
            "handoff_assets": ["london-pack.json", "visual-routes.json", "index.html", "prototype/index.html", "DESIGN.md"],
        },
        "quality_review": {
            "checks": [
                "Every gate has brain queries and evidence receipts.",
                "Routes differ by category and avoid generic modern-clean filler.",
                "Public outputs use sanitized source_ref identifiers only.",
            ],
            "risks": list(lane.risks),
            "approval_summary": "Locally approved for deterministic handoff; live provider exploration remains optional and secret-safe.",
        },
        "category_assumption": creative["category_assumption"],
        # D-04: carry BOTH split recommendation fields AS GIVEN — the renderer resolves the
        # machine reference deterministically (never by title-matching the prose) and renders
        # the verbatim prose argument unmodified. The deterministic floor is
        # recommended_route_ref=routes[0] / recommended_route="" (set by the directors).
        "recommended_route_ref": creative["recommended_route_ref"],
        "recommended_route": creative["recommended_route"],
        # GATE-01/02: carry the RESOLVED artifact_type AS GIVEN (a real top-level key admitted
        # by the strict write-gate). Resolution order flag > brief > model > generic is applied
        # above; the schema marks this field required, so it is emitted on EVERY run (RESEARCH
        # Pitfall 1: schema-admit + emit land in the same wave). NEVER a faked specific type.
        "artifact_type": resolved_artifact_type,
        "aesthetic_void": creative["aesthetic_void"],
        "london_reframe": creative["london_reframe"],
        "vessel_interface_expression": creative["vessel_expression"],
        "recurring_loop": creative["recurring_loop"],
        "unboxing_first_moment": creative["unboxing"],
        "anti_position": creative["anti_position"],
        "routes": routes,
        "brain_findings": _dedupe_hits(
            hit for gate in gates for hit in gate.get("brain_findings", [])
        )[:BRAIN_FINDINGS_CAP],
        "image_findings": _dedupe_hits(image_gate.get("brain_findings", []))[:FOCUSED_FINDINGS_CAP],
        "critique_findings": _dedupe_hits(critique_gate.get("brain_findings", []))[:FOCUSED_FINDINGS_CAP],
        "source_plan": source_plan_to_dict(source_plan),
        "receipts": _session_receipts(brief_record, gates, fixture=fixture),
        # Carry the DirectionResult forward to stage 2 so ONE direct() call drives
        # both stages; enrich_workbench_pack POPS this before validation/write.
        DIRECTION_RESULT_KEY: creative,
        # GATE-02 provenance: HOW artifact_type resolved (flag|brief|model|generic-default).
        # write_london_pack POPS this to build the auditable artifact-resolution receipt; it
        # is a private key (the schema is additionalProperties:false), never public prose.
        ARTIFACT_RESOLUTION_KEY: {"resolved": resolved_artifact_type, "source": artifact_source},
        # GRADE-02 / D-05..D-09: the engine grader is the keystone honesty instrument. London
        # does NOT grade his own homework: grader.grade() audits his CLAIM (the DirectionResult
        # dump, `creative`) against the OBJECTIVE transcript (`telemetry`, Plan 02) and returns
        # a STRUCTURALLY-SEPARATE block — composite + 4 inspectors + claim-integrity audit +
        # the scrubbed telemetry receipts + the two-layer headline/detail copy. The grading
        # LOGIC lives ENTIRELY in grader.py (one input, one output); session.py only
        # orchestrates: get telemetry, grade it, attach the block. It is kept structurally
        # separate from `creative` (the objective audit, never London's output — D-05), threaded
        # under the schema-admitted `grader` property (Plan 01's $def). It flows through the
        # single scrub_pack chokepoint (grader.telemetry.brain_queries[].query scrubbed) BEFORE
        # validate_pack; source IDs + counts are public-safe and raw finding bodies never enter.
        "grader": grader.grade(creative, telemetry),
    }
    return pack


def _direction_request(
    brief_record: Mapping[str, Any],
    lane: CreativeLane,
    gates: Sequence[Mapping[str, Any]],
    source_plan: SourcePlan,
    *,
    artifact_type: str = "generic",
    visual_selection: Mapping[str, Any] | None = None,
) -> DirectionRequest:
    """Assemble the deterministic FACTS the director consumes (never creative text).

    The brief, the per-gate brain-RAG findings, the source plan and the salient
    product tokens are the model's INPUT; the model writes the prose. (RESEARCH
    §DirectionResult Contract: the plumbing/intelligence split.)
    """

    brain_findings = {
        str(gate["gate_id"]): list(gate.get("brain_findings", []))
        for gate in gates
        if gate.get("gate_id")
    }
    product_tokens = _product_tokens(brief_record, lane)
    return DirectionRequest(
        brief=dict(brief_record),
        brain_findings=brain_findings,
        source_plan=source_plan_to_dict(source_plan),
        product_tokens=product_tokens,
        # GATE-02: the resolved flag/brief type the in-session model may HONOR; "generic"
        # when no signal so the model is free to declare honestly from the brief.
        artifact_type=artifact_type,
        visual_selection=dict(visual_selection or {}),
    )


def _direct_with_telemetry(
    director: CreativeDirector, request: DirectionRequest
) -> tuple[DirectionResult, RunTelemetry]:
    """Call the director's GRADE-01 telemetry seam, degrading gracefully (Pitfall 4).

    The default + every shipped director (Fake/Offline/ClaudeCode) implement
    ``direct_with_telemetry``; this helper guards the ONE additive seam so a minimal
    test/3rd-party director that only implements ``direct()`` still works — it falls back
    to ``direct()`` plus HONEST ``captured=False`` telemetry (an unavailable transcript,
    never a faked one). This keeps the seam truly additive: switching the production caller
    to telemetry breaks no existing ``direct()``-only mock.
    """

    method = getattr(director, "direct_with_telemetry", None)
    if callable(method):
        direction, telemetry = method(request)
        return direction, telemetry
    return director.direct(request), RunTelemetry(engine_mode="unknown", captured=False)


def _product_tokens(brief_record: Mapping[str, Any], lane: CreativeLane) -> list[str]:
    """Salient brief tokens (deterministic) — the echo seed the FakeDirector needs and
    the keyword material the model anchors on. Drawn from the lane facts + brief title."""

    tokens: list[str] = []
    for value in (lane.product_noun, *lane.rituals, *lane.surfaces):
        for word in str(value).replace("-", " ").split():
            cleaned = word.strip().lower()
            if cleaned and cleaned not in tokens:
                tokens.append(cleaned)
    for word in str(brief_record.get("title", "")).split():
        cleaned = word.strip().lower()
        if cleaned and cleaned not in tokens:
            tokens.append(cleaned)
    return tokens[:12]


def _routes_from_direction(creative: Mapping[str, Any], brief_record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Build the pack route dicts from the director's routes (creative text), keeping
    the route SHAPE the rest of the pipeline expects (id/type/sections/eyebrow).

    Structure (ids, eyebrow, approval_state, build_implications) is Python plumbing;
    the title/headline/palette/rationale/etc. prose comes from the DirectionResult.
    """

    routes: list[dict[str, Any]] = []
    for index, route in enumerate(creative.get("routes", []), start=1):
        title = str(route["title"])
        route_id = f"{slugify(brief_record['title']) or 'route'}-{slugify(title) or f'route-{index}'}"
        routes.append(
            {
                "id": route_id,
                "title": title,
                "headline": route["headline"],
                "subhead": route["subhead"],
                "palette": [dict(color) for color in route["palette"]],
                "assets": [],
                "tags": list(route.get("tags", [])),
                "lore": route["lore"],
                "mood": route["mood"],
                "type": route["type_note"],
                "rationale": route["rationale"],
                "steal": list(route.get("steal", [])),
                "do_not_copy": list(route.get("do_not_copy", [])),
                "sections": [
                    {
                        "title": section["title"],
                        "body": section["body"],
                        "eyebrow": f"{brief_record['title']} / Route {index:02d}",
                    }
                    for section in route.get("sections", [])
                ],
                "source_inspiration": [],
                "build_implications": [
                    "Render this route from current session-lane decisions, not another project pack.",
                    "Keep the first screen brief-specific enough to fail a borrowed skeleton test.",
                    "Attach brain and source receipts before public handoff.",
                ],
                "approval_state": "session-local-approved",
            }
        )
    return routes


def _components_from_direction(creative: Mapping[str, Any]) -> list[str]:
    """First product surfaces/output moments — view-model components from the director."""

    components: list[str] = [surface for surface in creative.get("surfaces", [])[:4] if surface]
    if len(components) < 4:
        components.extend(moment for moment in creative.get("output_moments", []) if moment not in components)
    return components[:4] or ["brief proof", "route panel", "state system", "handoff receipt"]


def _apply_direction_to_gates(gates: list[dict[str, Any]], creative: Mapping[str, Any]) -> None:
    """Overwrite each gate decision's summary/rationale with the director's per-gate
    conversation prose, so stage-2 build_conversation reads model text (not banks).

    Conversation reads are matched by their model-authored ``gate`` label, not by list
    index. The structural plumbing (evidence, approvals, brain queries) stays
    Python-computed. Conversation rationale is optional, so an omitted/empty model
    rationale must not erase the non-empty gate-rationale fallback required by the
    pack schema.
    """

    conversation = list(creative.get("conversation", []))
    reads_by_gate = _conversation_reads_by_gate(conversation)
    for gate in gates:
        read = _read_for_gate(gate, reads_by_gate)
        decisions = gate.get("decisions")
        if isinstance(decisions, list) and decisions and isinstance(decisions[0], dict):
            if read is None:
                gate_label = str(gate.get("gate_name") or gate.get("gate_id") or "this gate")
                decisions[0]["summary"] = f"No model read for this gate: {gate_label}."
                decisions[0]["rationale"] = (
                    "London did not author a conversation read for this gate, so the pack "
                    "leaves it as an honest open checkpoint."
                )
                continue
            decisions[0]["summary"] = read.get("decision", decisions[0].get("summary", ""))
            rationale = str(read.get("rationale") or "").strip()
            if rationale:
                decisions[0]["rationale"] = rationale


def _conversation_reads_by_gate(
    conversation: Sequence[Any],
) -> tuple[dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    exact: dict[str, Mapping[str, Any]] = {}
    folded: dict[str, Mapping[str, Any]] = {}
    for read in conversation:
        if not isinstance(read, Mapping):
            continue
        gate_label = str(read.get("gate") or "").strip()
        if not gate_label:
            continue
        exact.setdefault(gate_label, read)
        folded.setdefault(gate_label.lower(), read)
    return exact, folded


def _read_for_gate(
    gate: Mapping[str, Any],
    reads_by_gate: tuple[dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]]],
) -> Mapping[str, Any] | None:
    exact, folded = reads_by_gate
    for raw_label in (gate.get("gate_name"), gate.get("gate_id")):
        label = str(raw_label or "").strip()
        if not label:
            continue
        if label in exact:
            return exact[label]
        match = folded.get(label.lower())
        if match is not None:
            return match
    return None


def source_plan_to_dict(plan: SourcePlan) -> dict[str, object]:
    return {
        "packs": [
            {
                "slug": pack.slug,
                "label": pack.label,
                "description": pack.description,
                "local_prompts": list(pack.local_prompts),
            }
            for pack in plan.packs
        ],
        "lenses": [
            {
                "slug": lens.slug,
                "label": lens.label,
                "question": lens.question,
                "sources": list(lens.source_slugs),
            }
            for lens in plan.lenses
        ],
        "sources": [
            {
                "slug": source.slug,
                "name": source.name,
                "homepage": source.homepage,
                "use_for": source.use_for,
                "avoid": source.avoid,
            }
            for source in plan.sources
        ],
    }


def _run_gate(
    order: int,
    gate_id: str,
    brief: Mapping[str, Any],
    profile: CreativeLane,
    source_plan: SourcePlan,
    brain: LondonBrain,
) -> dict[str, Any]:
    query_specs = _gate_queries(gate_id, brief, profile)
    hits_by_query = [_query_brain(brain, query["query"], limit=3) for query in query_specs]
    findings = _dedupe_hits(hit.as_dict() for hits in hits_by_query for hit in hits)
    inspected_sources = _gate_sources(gate_id, source_plan)
    evidence = _decision_evidence(brief, findings, inspected_sources)

    return {
        "gate_id": gate_id,
        "gate_name": GATE_NAMES[gate_id],
        "order": order,
        "user_answers": _intake_answers(gate_id, profile),
        "brain_queries": query_specs,
        "brain_findings": findings,
        "sources_inspected": inspected_sources,
        "decisions": [
            {
                "decision_id": f"{gate_id}-{profile.slug}",
                "summary": _OFFLINE_DIRECTOR.gate_summary(gate_id, profile),
                "rationale": _OFFLINE_DIRECTOR.gate_rationale(gate_id, profile, findings),
                "artifacts": [f"gate:{gate_id}", f"session_lane:{profile.slug}"],
                "evidence": evidence,
            }
        ],
        "approvals": [
            {
                "status": "approved",
                "approver": PERSONA_LABEL,
                "notes": "Gate approved because it has brief-derived questions, brain findings, source evidence, and a recorded decision.",
            }
        ],
        "receipts": [
            {
                "receipt_id": f"{brief['digest']}-{gate_id}-brain",
                "kind": "brain-query",
                "summary": f"Ran {len(query_specs)} brief-derived London brain queries for {GATE_NAMES[gate_id]}.",
                "deterministic": True,
                "provider": "local-sqlite",
            },
            {
                "receipt_id": f"{brief['digest']}-{gate_id}-sources",
                "kind": "source-plan",
                "summary": f"Attached {len(inspected_sources)} source-plan references for {GATE_NAMES[gate_id]}.",
                "deterministic": True,
                "provider": "local-registry",
            },
        ],
    }


def _gate_queries(gate_id: str, brief: Mapping[str, Any], profile: CreativeLane) -> list[dict[str, str]]:
    values = {
        "title": brief["title"],
        "product_noun": profile.product_noun,
        "aesthetic": profile.aesthetic,
        "category": profile.label,
    }
    return [
        {
            "query": f"{template.format(**values)} {brief['title']}",
            "intent": intent,
        }
        for intent, template in GATE_QUERY_TEMPLATES[gate_id]
    ]


def _query_brain(brain: LondonBrain, query: str, *, limit: int) -> list[QueryHit]:
    hits = _general_brain_hits(brain.query(query, limit=limit * 4), limit)
    if hits:
        return hits
    return _general_brain_hits(
        brain.query("London taste critique method typography source proof anti generic", limit=limit * 4),
        limit,
    )


def _general_brain_hits(hits: Sequence[QueryHit], limit: int) -> list[QueryHit]:
    # OFFLINE-ONLY filter (see GENERAL_BRAIN_CATEGORIES note above): this is the deterministic
    # gate RAG that feeds the OfflineDirector parity oracle. The DEFAULT model path does not
    # reach here — it pulls the full, unfiltered brain via the brain MCP (ENGINE-02).
    filtered = [hit for hit in hits if hit.entry.category in GENERAL_BRAIN_CATEGORIES]
    return filtered[:limit]


def _intake_answers(gate_id: str, profile: CreativeLane) -> dict[str, str]:
    answers = {
        "research": (profile.audience, profile.aesthetic_void, "Use brain findings plus artifact-shaped source references."),
        "creative_direction": (profile.category_assumption, profile.london_reframe, profile.anti_position),
        "typography_color": (profile.type_system, profile.color_system),
        "image_direction": (profile.image_direction, "; ".join(profile.generation_constraints)),
        "layout_mockups": (profile.route_seeds[0].title, "; ".join(title for title, _ in profile.route_seeds[0].sections)),
        "build_motion": ("Static HTML dossier/prototype first; live providers optional.", "; ".join(profile.motion_principles)),
        "quality_review": ("Generic output or copied source chrome.", "Variation tests, sanitized source refs, and gate receipts."),
    }[gate_id]
    return {question: answer for question, answer in zip(INTAKE_QUESTIONS[gate_id], answers, strict=False)}


def _gate_sources(gate_id: str, source_plan: SourcePlan) -> list[dict[str, Any]]:
    if gate_id == "typography_color":
        preferred = ("fonts-in-use", "branding-style-guides", "the-brand-identity", "bpando")
    elif gate_id == "image_direction":
        preferred = ("death-to-stock", "the-dieline", "cosmos", "arena")
    elif gate_id == "layout_mockups":
        preferred = ("land-book", "godly", "commerce-cream", "mobbin")
    elif gate_id == "quality_review":
        preferred = ("bpando", "the-brand-identity", "godly", "land-book")
    else:
        preferred = tuple(source.slug for source in source_plan.sources)

    selected = [source for source in source_plan.sources if source.slug in preferred]
    if len(selected) < 3:
        selected.extend(source for source in source_plan.sources if source not in selected)
    return [
        {
            "source_id": source.slug,
            "title": source.name,
            "path": source.homepage,
            "notes": [source.use_for, f"Avoid: {source.avoid}"],
        }
        for source in selected[:4]
    ]


def _source_references(source_plan: SourcePlan) -> list[dict[str, str]]:
    return [
        {
            "source_id": source.slug,
            "title": source.name,
            "path": source.homepage,
        }
        for source in source_plan.sources[:6]
    ]


def _decision_evidence(
    brief: Mapping[str, Any],
    findings: Sequence[Mapping[str, Any]],
    sources: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = [
        {"kind": "user-brief", "title": brief["title"], "digest": brief["digest"]},
    ]
    evidence.extend(
        {
            "kind": "brain",
            "id": finding.get("id"),
            "title": finding.get("title"),
            "source_ref": finding.get("source_ref"),
        }
        for finding in findings[:3]
    )
    evidence.extend(
        {
            "kind": "source",
            "source_id": source.get("source_id"),
            "title": source.get("title"),
            "path": source.get("path"),
        }
        for source in sources[:2]
    )
    return evidence


def _lane_to_dict(lane: SessionLane, creative: Mapping[str, Any]) -> dict[str, Any]:
    # id/origin are deterministic plumbing (the session-lane identity); the public
    # lane prose (label/product_noun/audience/jobs/.../source_terms) is sourced from
    # the director's DirectionResult, and route_ids reflect the director's routes.
    return {
        "id": lane.slug,
        "origin": lane.origin,
        "label": creative["label"],
        "product_noun": creative["product_noun"],
        "audience": creative["audience"],
        "jobs": list(creative.get("jobs", [])),
        "rituals": list(creative.get("rituals", [])),
        "surfaces": list(creative.get("surfaces", [])),
        "tensions": list(creative.get("tensions", [])),
        "tone": list(creative.get("tone", [])),
        "avoid": list(creative.get("avoid", [])),
        "output_moments": list(creative.get("output_moments", [])),
        "source_terms": creative["source_terms"],
        "route_ids": [slugify(str(route.get("title", ""))) for route in creative.get("routes", [])],
    }


def _session_receipts(brief: Mapping[str, Any], gates: Sequence[Mapping[str, Any]], *, fixture: bool) -> list[dict[str, Any]]:
    return [
        {
            "receipt_id": f"{brief['digest']}-session",
            "kind": "session",
            "summary": f"Completed {len(gates)} London gates with brief-derived brain queries and source evidence.",
            "deterministic": True,
            "provider": "local-session",
        },
        {
            "receipt_id": f"{brief['digest']}-route-mode",
            "kind": "route-synthesis",
            "summary": "Used explicit fixture fallback routes." if fixture else "Synthesized a fresh session lane from the current brief; no reference packs were loaded.",
            "deterministic": True,
            "provider": "fixture" if fixture else ROUTE_SYNTHESIS_PROVIDER,
            # Offline origin marker (D-06 "no-model template preview"): carried on
            # the schema-allowed receipt `status` field — a receipt/debug surface,
            # NEVER a creative-prose field. The default model path (A5) will stamp
            # its own origin here instead.
            "status": OfflineDirector.origin if not fixture else "fixture",
        },
    ]


def _coerce_artifact_value(value: Any) -> str:
    """Coerce an untrusted artifact-type value (CLI flag / brief front-matter) to one of the
    constrained ARTIFACT_TYPES — unknown -> "generic" (honest floor, never crash; V5 input
    validation, threat T-045-03). Case/whitespace-insensitive."""

    normalized = str(value or "").strip().lower()
    return normalized if normalized in ARTIFACT_TYPES else "generic"


def _read_brief_once(brief: str | Path | Mapping[str, Any]) -> str | Mapping[str, Any]:
    if isinstance(brief, Path):
        return {
            "text": brief.read_text(encoding="utf-8"),
            "source_label": brief.name,
            "source_path": str(brief),
        }
    return brief


def _split_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Parse a leading ``---`` ... ``---`` YAML-style front-matter block into a flat
    key->value map and return (front_matter, body). No external YAML dep: only simple
    ``key: value`` lines are read (enough for ``artifact:``). When no front-matter is
    present the body is the original text unchanged."""

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    front: dict[str, str] = {}
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            body = "\n".join(lines[index + 1 :])
            return front, body
        if ":" in lines[index]:
            key, _, raw = lines[index].partition(":")
            front[key.strip().lower()] = raw.strip()
    # No closing fence -> treat the whole text as body (do not silently drop content).
    return {}, text


def _coerce_brief(brief: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(brief, Path):
        text = brief.read_text(encoding="utf-8")
        source_label = brief.name
    elif isinstance(brief, Mapping):
        text = str(brief.get("text", ""))
        source_label = _safe_source_label(
            brief.get("source_label") or brief.get("source_path") or brief.get("path")
        )
    else:
        text = str(brief)
        source_label = "input"

    # GATE-02: strip a leading front-matter block (if any) BEFORE title/digest so the fence
    # never becomes the title and the front-matter never pollutes the brief body. The
    # artifact field itself is read separately (_parse_brief_artifact) and NEVER stored on
    # the brief record — the brief sub-schema is additionalProperties:false (RESEARCH
    # Pitfall 6); only the 5 schema-allowed keys live here.
    _front_matter, body = _split_front_matter(text)

    normalized = body.strip()
    digest = sha256(normalized.encode("utf-8")).hexdigest()[:12]
    return {
        "title": _extract_title(normalized),
        "text": normalized,
        "digest": digest,
        "source_label": source_label,
        "source_ref": "input:brief",
    }


def _parse_brief_artifact(brief: str | Path | Mapping[str, Any]) -> str | None:
    """GATE-02: read a leading front-matter ``artifact: <type>`` off the brief WITHOUT
    touching the schema-pure brief record. Returns a coerced specific type, or None when the
    brief declares no (or an unknown / generic) artifact — so resolution falls through to the
    model declaration / honest generic default (never a faked specific type)."""

    if isinstance(brief, Path):
        text = brief.read_text(encoding="utf-8")
    elif isinstance(brief, Mapping):
        text = str(brief.get("text", ""))
    else:
        text = str(brief)
    front_matter, _body = _split_front_matter(text)
    raw = front_matter.get("artifact")
    if raw is None:
        return None
    coerced = _coerce_artifact_value(raw)
    return coerced if coerced != "generic" else None


def _safe_source_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text == "input:brief":
        return "input"
    return Path(text.replace("\\", "/")).name or "input"


def _extract_title(text: str) -> str:
    for line in text.splitlines():
        candidate = line.strip().lstrip("#").strip()
        if candidate:
            return candidate[:96]
    return "Untitled London brief"


def _dedupe_hits(items: Sequence[Mapping[str, Any]] | Any) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        key = str(item.get("id") or item.get("title") or item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(dict(item))
    return deduped
