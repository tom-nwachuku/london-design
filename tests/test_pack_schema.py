import json
from importlib.resources import files
from pathlib import Path


def test_packaged_schema_matches_authored_schema():
    source = Path(__file__).parents[1] / "schemas" / "london-pack.schema.json"
    packaged = files("london.data").joinpath("london-pack.schema.json")

    assert packaged.read_bytes() == source.read_bytes()


def test_schema_describes_enriched_london_pack_outputs():
    schema = json.loads((Path(__file__).parents[1] / "schemas" / "london-pack.schema.json").read_text())
    properties = schema["properties"]
    route_def = schema["$defs"]["visualRoute"]

    assert "routes" in properties
    assert "brain_findings" in properties
    assert "source_plan" in properties
    assert "london_reframe" in properties
    assert "anti_position" in properties
    assert "source_path" not in properties["brief"]["properties"]
    assert {"source_label", "source_ref"}.issubset(properties["brief"]["required"])
    assert properties["brief"]["properties"]["source_label"]["not"]["pattern"].startswith("^(/Users/")
    assert "session_lane" in properties
    assert "session_lane" in schema["required"]
    assert properties["session_lane"]["properties"]["origin"]["const"] == "current_brief"
    assert "reference_packs" in properties
    assert "reference_packs" in schema["required"]
    assert properties["reference_packs"]["maxItems"] == 0
    for key in (
        "conversation",
        "route_comparison",
        "font_options",
        "moodboard_tiles",
        "copy_blocks",
        "next_steps",
        "evidence_summary",
    ):
        assert key in properties
        assert key in schema["required"]
    assert {"id", "title", "headline", "palette", "assets", "approval_state"}.issubset(route_def["required"])
    assert schema["$defs"]["paletteColor"]["properties"]["hex"]["pattern"] == "^#[0-9a-fA-F]{6}$"
    assert schema["$defs"]["fontRouteGroup"]["properties"]["options"]["minItems"] == 3
    assert "why_this_route_not_other_route" in schema["$defs"]["fontOption"]["required"]
    assert "font_preview" in schema["$defs"]["fontOption"]["properties"]
    font_preview = schema["$defs"]["fontPreview"]
    assert font_preview["properties"]["status"]["enum"] == [
        "actual_loaded",
        "source_loaded",
        "fallback_approximation",
        "reference_capture",
        "reference_only",
    ]
    assert font_preview["properties"]["delivery"]["enum"] == [
        "local_asset",
        "remote_font_file",
        "system_fallback",
        "reference_image",
        "reference_only",
    ]
    assert "reference_preview" in font_preview["properties"]
    assert "buy_or_license_url" in font_preview["properties"]["reference_preview"]["properties"]
    assert font_preview["properties"]["asset_href"]["not"]["pattern"].startswith("^(?:[a-zA-Z]")
    assert schema["$defs"]["moodboardRouteGroup"]["properties"]["tiles"]["minItems"] == 6
    # Phase 5 Body-Fit (D-01/D-02/D-04/D-10): the cage is cut and the contract is widened.
    # additionalProperties:false discipline is RETAINED at the pack root.
    assert schema["additionalProperties"] is False
    # The conversation array is variable-N: minItems relaxed 7 -> 1, no maxItems ceiling.
    assert properties["conversation"]["minItems"] == 1
    assert "maxItems" not in properties["conversation"]
    # The quadruple is optionalized (D-02): gate+decision stay required; question/
    # answer_label/honesty_badges are dropped from REQUIRED.
    conversation = schema["$defs"]["conversationEntry"]
    assert "gate" in conversation["required"]
    assert "decision" in conversation["required"]
    assert "question" not in conversation["required"]
    assert "answer_label" not in conversation["required"]
    assert "honesty_badges" not in conversation["required"]
    # No order ceiling anywhere (the 7-cap is gone on both conversation + gateState order).
    assert "maximum" not in conversation["properties"]["order"]
    # BODY-02 (D-04): recommended_route_ref is a NEW machine field, required at the root.
    assert "recommended_route_ref" in properties
    assert "recommended_route_ref" in schema["required"]
    # The gates array is retained for offline RAG plumbing (Q6 minimal cut) but the
    # gate_id enum is OPENED so it can carry London's brief-specific labels.
    gate_id = schema["$defs"]["gateState"]["properties"]["gate_id"]
    assert "enum" not in gate_id
    assert gate_id["type"] == "string"
    # GRADE-01 contract dependency: the schema admits an optional grader block (Plan 03).
    assert "grader" in schema["$defs"]
    assert "TELEMETRY_UNAVAILABLE" in schema["$defs"]["grader"]["properties"]["audit"]["properties"]["verdict"]["enum"]
    receipt = schema["$defs"]["receipt"]
    assert "request_config" in receipt["properties"]
    assert "attempted_request_configs" in receipt["properties"]
    assert "estimated_cost_usd" in receipt["properties"]
    evidence = schema["$defs"]["evidenceSummary"]
    assert evidence["properties"]["brain"]["items"]["properties"]["evidence_class"]["const"] == "London Brain Finding"
    assert evidence["properties"]["sources"]["items"]["properties"]["evidence_class"]["const"] == "Source Target"
    assert evidence["properties"]["live_artifacts"]["items"]["properties"]["evidence_class"]["const"] == "Live Artifact"
    brain_finding = schema["$defs"]["brainFinding"]
    assert brain_finding["additionalProperties"] is False
    assert "source_ref" in brain_finding["required"]
    assert "source_video" not in brain_finding["properties"]
    assert brain_finding["properties"]["source_ref"]["not"]["pattern"] == "\\.mp4$"
