import json
import urllib.parse
import urllib.request

import pytest

from london.cli import main, write_london_pack
from london.companion import (
    MODEL_PATH_UNAVAILABLE,
    SELECTION_FILENAME,
    TOKEN_COST_CAVEAT,
    build_options,
    gate_for_pack,
    render_companion_html,
    start_companion_server,
    wait_for_http,
)
from london.director import FakeDirector


def _pack(*, provider: str = "in_session", deterministic: bool = False) -> dict:
    return {
        "pack_id": "london-pack-test",
        "title": "Joyful Product System",
        "artifact_type": "product",
        "receipts": [
            {
                "receipt_id": "director-selection",
                "kind": "director",
                "provider": provider,
                "deterministic": deterministic,
            }
        ],
        "routes": [
            {
                "id": "route-a",
                "title": "Object Ritual",
                "headline": "A tactile object route with public proof.",
                "rationale": "The route turns use into a visible ritual.",
                "palette": [
                    {"role": "spark", "name": "Signal Orange", "hex": "#ff6b35"},
                    {"role": "paper", "name": "Warm Paper", "hex": "#f7f1df"},
                    {"role": "mint", "name": "Mint Circuit", "hex": "#56c7b6"},
                ],
                "sections": [
                    {"title": "Hero proof", "body": "Show the product being used."},
                    {"title": "Material detail", "body": "Zoom in before widening."},
                ],
            },
            {
                "id": "route-b",
                "title": "Shared Signal",
                "headline": "A social proof route built around shareable moments.",
                "rationale": "The route makes the public loop visible.",
                "palette": [
                    {"role": "ink", "name": "Soft Black", "hex": "#151515"},
                    {"role": "glow", "name": "Hardware Yellow", "hex": "#ffd447"},
                ],
                "sections": [{"title": "Share card", "body": "Make the user's next action visible."}],
            },
        ],
    }


def _write_pack(tmp_path, pack: dict):
    out = tmp_path / "pack"
    out.mkdir()
    (out / "london-pack.json").write_text(json.dumps(pack), encoding="utf-8")
    return out


class _RecordingDirector:
    def __init__(self):
        self.visual_selection = {}

    def direct(self, request):
        self.visual_selection = dict(request.visual_selection)
        return FakeDirector().direct(request)


def test_show_me_requires_token_cost_ack_before_server_start(tmp_path):
    gate = gate_for_pack(_pack(), ack_token_cost=False)

    assert gate.started is False
    assert gate.reason == "ack_required"
    assert "this is token-intensive" in gate.caveat
    with pytest.raises(ValueError, match="Acknowledge"):
        start_companion_server(_pack(), tmp_path, ack_token_cost=False)


def test_show_me_cli_offline_degrades_without_fake_interactivity(tmp_path, capsys):
    pack_dir = _write_pack(
        tmp_path,
        _pack(provider="offline-template-preview", deterministic=True),
    )

    main(["show-me", str(pack_dir), "--ack-token-cost", "--json", "--dry-run"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["started"] is False
    assert payload["reason"] == "model_path_required"
    assert MODEL_PATH_UNAVAILABLE in payload["message"]
    assert not (pack_dir / "show-me-selection.json").exists()


def test_show_me_cli_no_ack_reports_caveat_without_starting(tmp_path, capsys):
    pack_dir = _write_pack(tmp_path, _pack())

    main(["show-me", str(pack_dir), "--json", "--dry-run"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["started"] is False
    assert payload["reason"] == "ack_required"
    assert TOKEN_COST_CAVEAT in payload["caveat"]
    assert not (pack_dir / "show-me-selection.json").exists()


def test_show_me_server_records_real_click_and_shuts_down(tmp_path):
    running = start_companion_server(_pack(), tmp_path, ack_token_cost=True)
    try:
        assert wait_for_http(running.url)
        html = urllib.request.urlopen(running.url, timeout=2).read().decode("utf-8")  # noqa: S310 - local server
        assert "London, Show Me" in html
        assert "this is token-intensive" in html
        assert "Choose this option" in html

        option = running.options[1]
        body = urllib.parse.urlencode({"option_id": option.option_id}).encode("utf-8")
        request = urllib.request.Request(
            urllib.parse.urljoin(running.url, "/select"),
            data=body,
            method="POST",
        )
        response = urllib.request.urlopen(request, timeout=2)  # noqa: S310 - local server
        assert response.status == 200
        assert running.wait_until_stopped(timeout=2)
        running.httpd.server_close()

        record = json.loads(running.selection_path.read_text(encoding="utf-8"))
        assert record["selected_option_id"] == option.option_id
        assert record["selected_route_ref"] == option.route_ref
        assert record["selection_source"] == "local_companion_click"
        assert record["flows_back_to_london"] is True
        assert record["secrets_printed"] is False
        assert record["local_paths_written"] is False
        blob = json.dumps(record)
        assert str(tmp_path) not in blob
        assert "/Users/" not in blob
        assert "sk-" not in blob
    finally:
        if running.thread.is_alive():
            running.stop()


def test_show_me_start_clears_stale_selection_without_a_click(tmp_path):
    stale = tmp_path / SELECTION_FILENAME
    stale.write_text(json.dumps({"old": True}), encoding="utf-8")

    running = start_companion_server(_pack(), tmp_path, ack_token_cost=True)
    try:
        assert wait_for_http(running.url)
        assert not stale.exists()
    finally:
        if running.thread.is_alive():
            running.stop()


def test_show_me_options_preserve_route_palette_and_section_range():
    pack = _pack()
    pack["routes"][0]["palette"] = [
        {"role": f"role-{index}", "name": f"Color {index}", "hex": f"#{index:06x}"}
        for index in range(1, 10)
    ]
    pack["routes"][0]["sections"] = [
        {"title": f"Section cue {index}", "body": "Keep the cue."}
        for index in range(1, 7)
    ]

    option = build_options(pack)[0]
    html = render_companion_html(pack, (option,), acknowledged=True)

    assert len(option.palette) == 9
    assert len(option.layout_cues) == 6
    assert html.count('class="swatch"') == 9
    assert "Section cue 6" in html


def test_show_me_selection_file_flows_through_pack_writer_sanitized(tmp_path):
    brief = tmp_path / "brief.md"
    brief.write_text("# Pocket Weather Ritual\n\nA desk object for anxious pet owners.", encoding="utf-8")
    selection = tmp_path / "show-me-selection.json"
    selection.write_text(
        json.dumps(
            {
                "selected_option_id": "option-1-object-ritual",
                "selected_route_ref": "/tmp/london-pack/route-a",
                "selected_route_title": "Object Ritual",
                "selected_artifact_type": "product",
                "reasoning_input": "Continue from /Users/example/private-pack with sk-secret-token.",  # EXPECTED-FIXTURE
            }
        ),
        encoding="utf-8",
    )
    director = _RecordingDirector()

    write_london_pack(
        brief,
        tmp_path / "out",
        director=director,
        image_provider="none",
        show_me_selection=selection,
    )

    assert director.visual_selection["selected_option_id"] == "option-1-object-ritual"
    assert director.visual_selection["selected_route_title"] == "Object Ritual"
    blob = json.dumps(director.visual_selection)
    assert "[redacted-local-path]" in blob
    assert "sk-secret-token" not in blob
    assert str(tmp_path) not in blob
