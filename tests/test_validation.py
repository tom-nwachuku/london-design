import json
import os
from pathlib import Path

import pytest

from london.cli import main
from london.validation import DEFAULT_CAPTURES_DIR, build_scenarios, run_chassis_validation


def _capture_dir_or_skip() -> Path:
    configured = os.environ.get("LONDON_VALIDATION_CAPTURES_DIR")
    captures_dir = Path(configured) if configured else DEFAULT_CAPTURES_DIR
    if captures_dir.is_dir():
        return captures_dir
    pytest.skip("Phase-4.6 validation captures are repo-local evidence and are not shipped in sdist.")


def test_chassis_validation_derives_capture_and_stress_ranges():
    report = run_chassis_validation(captures_dir=_capture_dir_or_skip())

    assert report["ok"] is True
    assert report["capture_count"] == 5
    assert report["scenario_count"] >= 9

    ranges = report["ranges"]
    assert 3 in ranges["conversation_counts"]
    assert 7 in ranges["conversation_counts"]
    assert 8 in ranges["conversation_counts"]
    assert 11 in ranges["recommendation_lengths"]
    assert 704 in ranges["recommendation_lengths"]
    assert 5 in ranges["route_palette_counts"]
    assert 8 in ranges["route_palette_counts"]
    assert 0 in ranges["brain_query_receipts"]
    assert 12 in ranges["brain_query_receipts"]
    assert 12 in ranges["consulted_source_receipts"]

    failed = [
        (scenario["name"], check)
        for scenario in report["scenarios"]
        for check in scenario["checks"]
        if not check["ok"]
    ]
    assert failed == []


def test_real_capture_scenarios_are_marked_as_range_evidence_not_templates():
    scenarios = build_scenarios(captures_dir=_capture_dir_or_skip())
    captures = [scenario for scenario in scenarios if scenario.kind == "capture"]

    assert len(captures) == 5
    assert {len(scenario.direction["conversation"]) for scenario in captures} == {3, 5, 6, 7}
    assert {len(str(scenario.direction["recommended_route"])) for scenario in captures} == {
        11,
        13,
        413,
        531,
        704,
    }
    assert all("validation-only recommended_route_ref" in scenario.note for scenario in captures)
    assert all(scenario.raw_capture_query_count is not None for scenario in captures)


def test_validate_chassis_cli_json_smoke(capsys, tmp_path):
    html_dir = tmp_path / "validation-html"
    main([
        "validate-chassis",
        "--json",
        "--captures-dir",
        str(_capture_dir_or_skip()),
        "--write-html-dir",
        str(html_dir),
    ])

    output = capsys.readouterr().out
    report = json.loads(output)

    assert report["ok"] is True
    assert report["capture_count"] == 5
    assert (html_dir / "capture-website.html").exists()
    assert (html_dir / "stress-receipts-12.html").exists()


def test_validate_chassis_default_error_is_source_checkout_specific(monkeypatch, tmp_path, capsys):
    import london.validation as validation

    monkeypatch.setattr(validation, "DEFAULT_CAPTURES_DIR", tmp_path / "missing-captures")

    with pytest.raises(SystemExit) as exc:
        main(["validate-chassis", "--json"])

    assert exc.value.code == 2
    error = capsys.readouterr().err
    assert "source checkout" in error
    assert "--captures-dir" in error


def test_validate_chassis_help(capsys):
    main(["validate-chassis", "--help"])

    output = capsys.readouterr().out

    assert "Usage: london validate-chassis" in output
    # --captures-dir is a real Typer option; the rich-formatted help breaks up
    # "--captures-dir PATH" with variable whitespace — assert the flag name alone.
    assert "--captures-dir" in output
