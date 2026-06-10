import json
from pathlib import Path

import pytest

from london.cli import main
from london.launch import LAUNCH_GATE_IDS, evaluate_launch_gates


def _write_gate_pack(
    tmp_path: Path,
    *,
    blocked: bool = False,
    generated_image: bool = True,
    actual_font: bool = True,
    route_ref: str = "route_signal_kiosk",
    chip_text: str = "Signal Kiosk",
) -> Path:
    out = tmp_path / "pack"
    assets = out / "assets"
    fonts = assets / "fonts"
    prototype = out / "prototype"
    assets.mkdir(parents=True)
    fonts.mkdir()
    prototype.mkdir()
    (assets / "route-1.svg").write_text("<svg><text>Route one</text></svg>", encoding="utf-8")
    (assets / "route-2.svg").write_text("<svg><text>Route two</text></svg>", encoding="utf-8")
    (fonts / "launch-test.woff2").write_bytes(b"test-font-placeholder")
    status = "images_disabled" if blocked else "manual_prompt_ready"
    director_provider = "FakeDirector" if blocked else "ClaudeCodeDirector"
    route_1_kind = "generated-concept-image" if generated_image else "visual-direction-board"
    route_1_status = "generated_live" if generated_image else status
    route_1_provider = "gemini" if generated_image else "manual-prompt"
    pack = {
        "mode": "scripted-local",
        "recommended_route_ref": route_ref,
        "routes": [
            {
                "id": "launch-pilot-signal-kiosk",
                "title": "Signal Kiosk",
                "palette": [{"hex": "#ff4f1f"}],
                "assets": [{"kind": route_1_kind, "src": "assets/route-1.svg"}],
            },
            {
                "id": "launch-pilot-quiet-console",
                "title": "Quiet Console",
                "palette": [{"hex": "#204a87"}],
                "assets": [{"kind": "visual-direction-board", "src": "assets/route-2.svg"}],
            },
        ],
        "receipts": [
            {
                "kind": "image-generation",
                "receipt_id": "launch-pilot-signal-kiosk-image-generation",
                "provider": route_1_provider,
                "requested_provider": "auto",
                "resolved_provider": route_1_provider,
                "route_id": "launch-pilot-signal-kiosk",
                "status": route_1_status,
                "deterministic": not generated_image,
            },
            {
                "kind": "image-generation",
                "receipt_id": "launch-pilot-quiet-console-image-generation",
                "provider": "manual-prompt",
                "requested_provider": "auto",
                "resolved_provider": "manual-prompt",
                "route_id": "launch-pilot-quiet-console",
                "status": status,
                "deterministic": True,
            },
            {
                "kind": "director",
                "receipt_id": "director-selection",
                "provider": director_provider,
                "deterministic": blocked,
            },
        ],
    }
    font_html = (
        """
    <style>
      @font-face { font-family: "Launch Test"; src: url("assets/fonts/launch-test.woff2") format("woff2"); font-display: swap; }
    </style>
    <article class="font-option font-option--actual_loaded" data-font-preview-status="actual_loaded" data-font-preview-delivery="local_asset" data-font-preview-family="Launch Test" data-font-asset-href="assets/fonts/launch-test.woff2">
      <p class="font-specimen" style="font-family:&quot;Launch Test&quot;, system-ui, sans-serif" data-font-preview-status="actual_loaded" data-font-preview-family="Launch Test">Specimen</p>
      <div><dt>Asset</dt><dd>assets/fonts/launch-test.woff2</dd></div>
    </article>
    """
        if actual_font
        else """
    <article data-font-preview-status="fallback_approximation" data-font-preview-family="safe local stack">
      <span>fallback approximation</span>
      <p class="font-specimen">Specimen</p>
    </article>
    """
    )
    visual_state = "generated" if generated_image else "visual-direction-board"
    html = f"""
    <span class="recommended-chip">{chip_text}</span>
    <section class="prototype-hero">
      <figure class="prototype-visual" data-visual-state="{visual_state}"></figure>
    </section>
    {font_html}
    <script>
      window.londonVerifyFontPreviews = async function() {{ await document.fonts.ready; }};
    </script>
    """
    (out / "london-pack.json").write_text(json.dumps(pack), encoding="utf-8")
    (out / "index.html").write_text(html, encoding="utf-8")
    (prototype / "index.html").write_text(html, encoding="utf-8")
    return out


def test_launch_gate_accepts_launch_grade_visual_pack(tmp_path):
    report = evaluate_launch_gates(_write_gate_pack(tmp_path))

    assert report["ok"] is True
    assert tuple(report["gate_ids"]) == LAUNCH_GATE_IDS
    assert all(gate["ok"] for gate in report["gates"].values())
    assert report["gates"]["recommended_route_resolves"]["resolved_route_title"] == "Signal Kiosk"
    assert report["gates"]["image_artifact_present"]["asset_kind"] == "generated-concept-image"
    assert report["gates"]["actual_image_or_blocked"]["asset_kind"] == "generated-concept-image"
    assert report["gates"]["actual_image_or_blocked"]["public_gallery_eligible_route_ids"] == [
        "launch-pilot-signal-kiosk"
    ]
    assert report["gates"]["actual_image_or_blocked"]["public_gallery_blocked_route_ids"] == [
        "launch-pilot-quiet-console"
    ]
    assert report["gates"]["actual_font_or_blocked"]["actual_loaded_claims"] >= 1


@pytest.mark.parametrize("gate_id", LAUNCH_GATE_IDS)
def test_each_launch_gate_can_fail(tmp_path, gate_id):
    root = _write_gate_pack(tmp_path / gate_id)
    pack_path = root / "london-pack.json"
    pack = json.loads(pack_path.read_text(encoding="utf-8"))

    if gate_id in {"image_artifact_present", "actual_image_or_blocked"}:
        pack["routes"][0]["assets"][0]["kind"] = "visual-direction-board"
        pack["receipts"][0]["status"] = "manual_prompt_ready"
    elif gate_id == "image_receipt_real":
        pack["receipts"][0]["status"] = "images_disabled"
    elif gate_id == "font_claim_verified":
        for html_path in (root / "index.html", root / "prototype" / "index.html"):
            html_path.write_text(
                html_path.read_text(encoding="utf-8").replace("window.londonVerifyFontPreviews", ""),
                encoding="utf-8",
            )
    elif gate_id == "fallback_label_visible":
        for html_path in (root / "index.html", root / "prototype" / "index.html"):
            html = html_path.read_text(encoding="utf-8")
            html = html.replace('data-font-preview-status="actual_loaded"', 'data-font-preview-status="fallback_approximation"')
            html = html.replace("fallback approximation", "")
            html_path.write_text(html, encoding="utf-8")
    elif gate_id == "recommended_route_resolves":
        pack["recommended_route_ref"] = "route_missing_choice"
    elif gate_id == "first_viewport_visual":
        for html_path in (root / "index.html", root / "prototype" / "index.html"):
            html = html_path.read_text(encoding="utf-8").replace("data-visual-state=", "data-old-visual-state=")
            html_path.write_text(html, encoding="utf-8")
    elif gate_id == "actual_font_or_blocked":
        (root / "assets" / "fonts" / "launch-test.woff2").unlink()
    elif gate_id == "public_route_labels_human":
        for html_path in (root / "index.html", root / "prototype" / "index.html"):
            html_path.write_text(
                html_path.read_text(encoding="utf-8") + "<p>route_machine_ref</p>",
                encoding="utf-8",
            )
    elif gate_id == "route_visual_delta":
        pack["routes"][1]["title"] = pack["routes"][0]["title"]
        pack["routes"][1]["palette"] = list(pack["routes"][0]["palette"])
        pack["routes"][1]["assets"][0]["src"] = pack["routes"][0]["assets"][0]["src"]
    elif gate_id == "prompt_card_not_primary":
        for route in pack["routes"]:
            route["assets"][0]["kind"] = "manual-prompt-card"

    pack_path.write_text(json.dumps(pack), encoding="utf-8")
    report = evaluate_launch_gates(root)

    assert report["gates"][gate_id]["ok"] is False, gate_id


def test_launch_gate_rejects_disabled_images_and_fake_director(tmp_path):
    report = evaluate_launch_gates(_write_gate_pack(tmp_path, blocked=True))

    assert report["ok"] is False
    assert report["gates"]["image_receipt_real"]["ok"] is False
    failures = " ".join(report["gates"]["image_receipt_real"]["failures"])
    assert "images_disabled" in failures
    assert "Director receipt is deterministic" in failures
    assert "fake" in failures.lower()


def test_launch_gate_blocks_fallback_only_pilots_from_public_proof(tmp_path):
    report = evaluate_launch_gates(_write_gate_pack(tmp_path, generated_image=False, actual_font=False))

    assert report["ok"] is False
    assert report["gates"]["image_artifact_present"]["ok"] is False
    assert "fallback boards are internal only" in report["gates"]["image_artifact_present"]["detail"]
    assert "public proof blocked" in " ".join(report["gates"]["image_artifact_present"]["failures"])
    assert report["gates"]["fallback_label_visible"]["ok"] is True
    assert report["gates"]["actual_image_or_blocked"]["ok"] is False
    assert report["gates"]["actual_image_or_blocked"]["public_gallery_eligible_route_ids"] == []
    assert report["gates"]["actual_image_or_blocked"]["public_gallery_blocked_route_ids"] == [
        "launch-pilot-signal-kiosk",
        "launch-pilot-quiet-console",
    ]
    assert report["gates"]["actual_font_or_blocked"]["ok"] is False
    assert "blocked_for_real_image" in " ".join(report["gates"]["actual_image_or_blocked"]["failures"])
    assert "blocked_for_actual_font" in " ".join(report["gates"]["actual_font_or_blocked"]["failures"])


def test_launch_gate_accepts_reference_visual_as_visible_reference_label(tmp_path):
    root = _write_gate_pack(tmp_path)
    for html_path in (root / "index.html", root / "prototype" / "index.html"):
        html = html_path.read_text(encoding="utf-8")
        html += """
        <article data-font-preview-status="reference_only" data-font-preview-family="reference specimen">
          <p class="font-specimen">Reference specimen</p>
        </article>
        """
        html_path.write_text(html, encoding="utf-8")

    report = evaluate_launch_gates(root)

    assert report["gates"]["fallback_label_visible"]["ok"] is True


def test_launch_gate_fallback_label_visible_can_fail(tmp_path):
    root = _write_gate_pack(tmp_path, actual_font=False)
    for html_path in (root / "index.html", root / "prototype" / "index.html"):
        html = html_path.read_text(encoding="utf-8").replace("fallback approximation", "")
        html_path.write_text(html, encoding="utf-8")

    report = evaluate_launch_gates(root)

    assert report["gates"]["fallback_label_visible"]["ok"] is False
    assert "visible fallback approximation label" in " ".join(report["gates"]["fallback_label_visible"]["failures"])


def test_launch_gate_rejects_unresolved_or_visible_machine_route_refs(tmp_path):
    report = evaluate_launch_gates(
        _write_gate_pack(
            tmp_path,
            route_ref="route_missing_choice",
            chip_text="route_missing_choice",
        )
    )

    assert report["ok"] is False
    assert report["gates"]["recommended_route_resolves"]["ok"] is False
    assert report["gates"]["public_route_labels_human"]["ok"] is False
    failures = " ".join(report["gates"]["recommended_route_resolves"]["failures"])
    assert "route_missing_choice" in failures
    assert "launch-pilot-signal-kiosk / Signal Kiosk" in failures


def test_launch_gate_cli_json_exits_nonzero_on_failure(tmp_path, capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["launch-gate", str(_write_gate_pack(tmp_path, generated_image=False, actual_font=False)), "--json"])

    assert excinfo.value.code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False
    assert report["gates"]["actual_image_or_blocked"]["ok"] is False
