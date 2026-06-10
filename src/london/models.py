from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

# GATE_IDS / GATE_NAMES are now single-sourced in persona.py (WALK-01). They are
# re-exported here so the established ``from london.models import GATE_IDS, GATE_NAMES``
# import sites keep working unchanged.
from london.persona import GATE_IDS, GATE_NAMES

# Re-export the single-sourced gate constants so existing import sites resolve them
# from ``london.models`` unchanged.
__all__ = ["GATE_IDS", "GATE_NAMES"]

GateApprovalStatus = Literal["approved", "needs_revision", "blocked"]
WorkflowMode = Literal["scripted-local", "live-provider"]

REQUIRED_PACK_SECTIONS: tuple[str, ...] = (
    "brief",
    "gates",
    "research",
    "creative_direction",
    "typography_color",
    "image_direction",
    "layout_mockups",
    "build_motion",
    "quality_review",
    "receipts",
)


@dataclass
class BrainQuery:
    query: str
    intent: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class SourceInspection:
    source_id: str
    title: str
    path: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Decision:
    decision_id: str
    summary: str
    rationale: str
    artifacts: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GateApproval:
    status: GateApprovalStatus
    approver: str
    notes: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class Receipt:
    receipt_id: str
    kind: str
    summary: str
    deterministic: bool = True
    provider: str = "local-scripted"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GateState:
    gate_id: str
    gate_name: str
    order: int
    user_answers: dict[str, str]
    brain_queries: list[BrainQuery]
    sources_inspected: list[SourceInspection]
    decisions: list[Decision]
    approvals: list[GateApproval]
    receipts: list[Receipt]
    brain_findings: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LondonPack:
    pack_id: str
    version: str
    mode: WorkflowMode
    brief: dict[str, Any]
    gates: list[GateState]
    research: dict[str, Any]
    creative_direction: dict[str, Any]
    typography_color: dict[str, Any]
    image_direction: dict[str, Any]
    layout_mockups: dict[str, Any]
    build_motion: dict[str, Any]
    quality_review: dict[str, Any]
    receipts: list[Receipt]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
