from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from london.models import (
    BrainQuery,
    Decision,
    GATE_NAMES,
    GateApproval,
    GateState,
    LondonPack,
    Receipt,
    SourceInspection,
)
from london.persona import PERSONA_PROSE

PACK_VERSION = "0.1.0"


@dataclass(frozen=True)
class GateSpec:
    gate_id: str
    question_keys: tuple[str, ...]
    brain_query_templates: tuple[str, ...]
    decision_summary: str
    section_focus: tuple[str, ...]


GATE_SPECS: tuple[GateSpec, ...] = (
    GateSpec(
        gate_id="research",
        question_keys=("audience", "category", "proof"),
        brain_query_templates=(
            "Find category tensions, audience cues, and proof points for {title}.",
            "Surface London-grade precedents for {title}: useful, specific, not generic-clean.",
        ),
        decision_summary="Frame the brief around a specific audience tension and evidence plan.",
        section_focus=("audience", "category_tension", "evidence_plan"),
    ),
    GateSpec(
        gate_id="creative_direction",
        question_keys=("promise", "voice", "routes"),
        brain_query_templates=(
            "Translate the {title} brief into a creative point of view with named routes.",
            "Find opinionated language patterns that make {title} feel designed, not decorated.",
        ),
        decision_summary="Choose a public, design-literate creative stance with three usable routes.",
        section_focus=("positioning", "voice", "concept_routes"),
    ),
    GateSpec(
        gate_id="typography_color",
        question_keys=("type_mood", "palette_mood", "accessibility"),
        brain_query_templates=(
            "Identify typography systems for {title} that carry tone before ornament.",
            "Find color systems for {title} with contrast, hierarchy, and memorable restraint.",
        ),
        decision_summary="Set type and color rules before imagery so the system has a spine.",
        section_focus=("type_system", "color_system", "accessibility_notes"),
    ),
    GateSpec(
        gate_id="image_direction",
        question_keys=("visual_world", "shots", "avoid"),
        brain_query_templates=(
            "Gather image-direction references for {title}: lighting, composition, and subject rules.",
            "Define what {title} imagery must avoid so the work stays public-safe and ownable.",
        ),
        decision_summary="Define image rules that describe the world, not just the surface style.",
        section_focus=("art_direction", "shot_list", "generation_constraints"),
    ),
    GateSpec(
        gate_id="layout_mockups",
        question_keys=("primary_route", "screens", "density"),
        brain_query_templates=(
            "Map {title} into page routes, content hierarchy, and reusable layout patterns.",
            "Find mockup conventions for {title} that make inspection and handoff easy.",
        ),
        decision_summary="Convert direction into routes, frames, and component-level layout intent.",
        section_focus=("routes", "wireframes", "components"),
    ),
    GateSpec(
        gate_id="build_motion",
        question_keys=("stack", "motion", "handoff"),
        brain_query_templates=(
            "Translate {title} into build handoff notes, tokens, assets, and motion principles.",
            "Identify deterministic prototype steps for {title} that work without provider keys.",
        ),
        decision_summary="Plan a deterministic prototype and restrained motion system.",
        section_focus=("prototype_plan", "motion_principles", "handoff_assets"),
    ),
    GateSpec(
        gate_id="quality_review",
        question_keys=("checks", "risks", "approval"),
        brain_query_templates=(
            "Review {title} for public-package safety, specificity, and missing receipts.",
            "Find quality checks that protect {title} from generic design output.",
        ),
        decision_summary="Approve the pack only after every gate has receipts and a useful caveat list.",
        section_focus=("checks", "risks", "approval_summary"),
    ),
)

DEFAULT_SOURCES: tuple[SourceInspection, ...] = (
    SourceInspection(
        source_id="brief",
        title="User brief",
        path="input:brief",
        notes=["Primary public-safe brief text supplied to the workflow."],
    ),
    SourceInspection(
        source_id="sanitized-london-brain",
        title="Sanitized London brain",
        path="brain:normalized-local",
        notes=["Local deterministic stand-in for retrieval; provider keys are not required."],
    ),
)


def run_scripted_workflow(
    brief: str | Path | Mapping[str, Any],
    *,
    user_answers: Mapping[str, Mapping[str, str]] | None = None,
    sources: Sequence[SourceInspection | Mapping[str, Any]] | None = None,
) -> LondonPack:
    """Run the seven-gate London workflow with deterministic local state."""

    brief_record = _coerce_brief(brief)
    source_records = _coerce_sources(sources)
    answers_by_gate = user_answers or {}
    gates = [
        _run_gate(order=index + 1, spec=spec, brief=brief_record, sources=source_records, user_answers=answers_by_gate.get(spec.gate_id, {}))
        for index, spec in enumerate(GATE_SPECS)
    ]

    sections = _build_pack_sections(brief_record, gates)
    receipts = [
        Receipt(
            receipt_id=f"pack-{brief_record['digest']}-workflow",
            kind="workflow",
            summary="Scripted local seven-gate workflow completed without provider keys.",
        ),
        Receipt(
            receipt_id=f"pack-{brief_record['digest']}-state",
            kind="state",
            summary="Every gate wrote answers, brain queries, sources, decisions, approvals, and receipts.",
        ),
    ]

    return LondonPack(
        pack_id=f"london-pack-{brief_record['digest']}",
        version=PACK_VERSION,
        mode="scripted-local",
        brief=brief_record,
        gates=gates,
        receipts=receipts,
        **sections,
    )


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

    normalized = text.strip()
    digest = sha256(normalized.encode("utf-8")).hexdigest()[:12]
    title = _extract_title(normalized)
    return {
        "title": title,
        "text": normalized,
        "digest": digest,
        "source_label": source_label,
        "source_ref": "input:brief",
    }


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


def _coerce_sources(sources: Sequence[SourceInspection | Mapping[str, Any]] | None) -> list[SourceInspection]:
    if sources is None:
        return [SourceInspection(**source.to_dict()) for source in DEFAULT_SOURCES]

    source_records: list[SourceInspection] = []
    for index, source in enumerate(sources, start=1):
        if isinstance(source, SourceInspection):
            source_records.append(source)
            continue

        notes = source.get("notes", [])
        source_records.append(
            SourceInspection(
                source_id=str(source.get("source_id", f"source-{index}")),
                title=str(source.get("title", f"Source {index}")),
                path=str(source.get("path", "input:source")),
                notes=[str(note) for note in notes],
            )
        )
    return source_records


def _run_gate(
    *,
    order: int,
    spec: GateSpec,
    brief: Mapping[str, Any],
    sources: Sequence[SourceInspection],
    user_answers: Mapping[str, str],
) -> GateState:
    gate_name = GATE_NAMES[spec.gate_id]
    answers = _default_answers(spec, brief) | {key: str(value) for key, value in user_answers.items()}
    brain_queries = [
        BrainQuery(query=template.format(title=brief["title"]), intent=f"{gate_name} decision support")
        for template in spec.brain_query_templates
    ]
    source_receipts = [
        SourceInspection(
            source_id=source.source_id,
            title=source.title,
            path=source.path,
            notes=[f"{gate_name}: {note}" for note in source.notes],
        )
        for source in sources
    ]
    decision = Decision(
        decision_id=f"{order:02d}-{spec.gate_id}",
        summary=spec.decision_summary,
        rationale=_decision_rationale(spec, brief, answers),
        artifacts=[f"pack.{section}" for section in spec.section_focus],
    )

    return GateState(
        gate_id=spec.gate_id,
        gate_name=gate_name,
        order=order,
        user_answers=answers,
        brain_queries=brain_queries,
        sources_inspected=source_receipts,
        decisions=[decision],
        approvals=[
            GateApproval(
                status="approved",
                approver="scripted-local",
                notes=f"{gate_name} has deterministic state and can advance without provider keys.",
            )
        ],
        receipts=[
            Receipt(
                receipt_id=f"{brief['digest']}-{order:02d}-{spec.gate_id}",
                kind="gate-state",
                summary=f"{gate_name} recorded answers, retrieval intent, source inspections, decisions, and approval.",
            )
        ],
    )


def _default_answers(spec: GateSpec, brief: Mapping[str, Any]) -> dict[str, str]:
    title = str(brief["title"])
    defaults: dict[str, str] = {}
    for key in spec.question_keys:
        readable_key = key.replace("_", " ")
        defaults[key] = f"For {title}, London defaults {readable_key} to a public-safe, specific, design-literate direction."
    return defaults


def _decision_rationale(spec: GateSpec, brief: Mapping[str, Any], answers: Mapping[str, str]) -> str:
    answer_keys = ", ".join(answers)
    return (
        f"{GATE_NAMES[spec.gate_id]} uses the brief digest {brief['digest']} and answers "
        f"({answer_keys}) to keep the pack deterministic, inspectable, and provider-free."
    )


def _build_pack_sections(brief: Mapping[str, Any], gates: Sequence[GateState]) -> dict[str, dict[str, Any]]:
    gate_by_id = {gate.gate_id: gate for gate in gates}
    return {
        "research": {
            "audience": gate_by_id["research"].user_answers["audience"],
            "category_tension": "Name the real tension before choosing a visual treatment.",
            "evidence_plan": _section_evidence(gate_by_id["research"]),
        },
        "creative_direction": {
            "positioning": gate_by_id["creative_direction"].user_answers["promise"],
            # One London voice (D-01): reference the persona single source rather than
            # re-declaring a competing voice literal here (anti-Workstream-F-drift).
            "voice": PERSONA_PROSE,
            "concept_routes": ["editorial proof", "ritual system", "buildable campaign world"],
        },
        "typography_color": {
            "type_system": gate_by_id["typography_color"].user_answers["type_mood"],
            "color_system": gate_by_id["typography_color"].user_answers["palette_mood"],
            "accessibility_notes": ["Contrast is a design material, not an afterthought.", "Avoid palette choices that collapse into one-note mood."],
        },
        "image_direction": {
            "art_direction": gate_by_id["image_direction"].user_answers["visual_world"],
            "shot_list": ["hero proof image", "detail inspection", "human-context frame", "system or kit frame"],
            "generation_constraints": ["Use public-safe prompts.", "Do not leak archive-heavy source material.", "Keep provenance receipts with generated assets."],
        },
        "layout_mockups": {
            "routes": ["dossier", "prototype", "handoff"],
            "wireframes": ["desktop inspection frame", "mobile first-scroll frame"],
            "components": ["palette rail", "route card", "source receipt", "decision note"],
        },
        "build_motion": {
            "prototype_plan": f"Build a deterministic static prototype for {brief['title']}.",
            "motion_principles": ["Motion clarifies hierarchy.", "Default to reduced-motion-safe behavior.", "Never hide essential proof behind animation."],
            "handoff_assets": ["DESIGN.md", "BUILD-HANDOFF.md", "tokens.json", "receipts.json"],
        },
        "quality_review": {
            "checks": ["all seven gates wrote state", "required pack sections exist", "local mode needs no provider keys"],
            "risks": ["Live provider outputs still need separate receipts when enabled."],
            "approval_summary": gate_by_id["quality_review"].approvals[0].notes,
        },
    }


def _section_evidence(gate: GateState) -> list[dict[str, str]]:
    return [
        {
            "source_id": source.source_id,
            "title": source.title,
            "path": source.path,
        }
        for source in gate.sources_inspected
    ]
