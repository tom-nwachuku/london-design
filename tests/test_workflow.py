import json
from pathlib import Path

from london.models import GATE_IDS, REQUIRED_PACK_SECTIONS
from london.workflow import run_scripted_workflow


BRIEF = """# Joyful Retro-Futurist Product

Create a public-safe product system that feels optimistic, tactile, and ready
for a designer-developer handoff.
"""


def test_scripted_workflow_writes_state_for_every_gate():
    pack = run_scripted_workflow(BRIEF)

    assert [gate.gate_id for gate in pack.gates] == list(GATE_IDS)
    assert [gate.order for gate in pack.gates] == list(range(1, 8))

    for gate in pack.gates:
        assert gate.user_answers
        assert gate.brain_queries
        assert gate.sources_inspected
        assert gate.decisions
        assert gate.approvals
        assert gate.receipts
        assert gate.approvals[0].status == "approved"
        assert gate.receipts[0].deterministic is True


def test_scripted_pack_has_required_sections_and_is_deterministic():
    first = run_scripted_workflow(BRIEF).to_dict()
    second = run_scripted_workflow(BRIEF).to_dict()

    assert first == second
    assert set(REQUIRED_PACK_SECTIONS).issubset(first)
    assert first["mode"] == "scripted-local"
    assert first["brief"]["title"] == "Joyful Retro-Futurist Product"
    assert "source_path" not in first["brief"]
    assert first["brief"]["source_label"]
    assert first["brief"]["source_ref"] == "input:brief"
    assert first["research"]["evidence_plan"]
    assert first["creative_direction"]["concept_routes"]
    assert first["typography_color"]["accessibility_notes"]
    assert first["image_direction"]["generation_constraints"]
    assert first["layout_mockups"]["components"]
    assert first["build_motion"]["handoff_assets"]
    assert first["quality_review"]["checks"]

    json.dumps(first)


def test_schema_requires_gate_state_and_pack_sections():
    schema_path = Path(__file__).parents[1] / "schemas" / "london-pack.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert set(REQUIRED_PACK_SECTIONS).issubset(schema["required"])
    gate_required = set(schema["$defs"]["gateState"]["required"])
    assert {
        "user_answers",
        "brain_queries",
        "sources_inspected",
        "decisions",
        "approvals",
        "receipts",
    }.issubset(gate_required)
