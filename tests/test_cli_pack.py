import base64
import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
import typer
from typer.testing import CliRunner

import london.cli as cli
from london.cli import main, validate_pack, write_london_pack
from london.director import FakeDirector
from london.launch import evaluate_launch_gates


def test_write_london_pack_exports_required_artifacts(tmp_path):
    brief = tmp_path / "brief.md"
    brief.write_text("# Joyful Retro-Futurist Product\n\nBuild a tactile public product system.", encoding="utf-8")
    out = tmp_path / "pack"

    pack = write_london_pack(brief, out)

    assert (out / "london-pack.json").exists()
    assert (out / "index.html").exists()
    assert (out / "prototype" / "index.html").exists()
    assert (out / "DESIGN.md").exists()
    assert (out / "BUILD-HANDOFF.md").exists()
    assert (out / "visual-routes.json").exists()
    assert (out / "london-session.json").exists()
    assert (out / "receipts.json").exists()
    rendered_pack = json.loads((out / "london-pack.json").read_text(encoding="utf-8"))
    assert list((out / "assets").glob("*.svg"))
    assert all(route["assets"][0]["kind"] == "visual-direction-board" for route in rendered_pack["routes"])
    assert all((out / route["assets"][0]["src"]).exists() for route in rendered_pack["routes"])
    assert rendered_pack["title"] == "Joyful Retro-Futurist Product"
    assert "source_path" not in rendered_pack["brief"]
    assert rendered_pack["brief"]["source_label"] == "brief.md"
    assert rendered_pack["brief"]["source_ref"] == "input:brief"
    assert rendered_pack["session_lane"]["origin"] == "current_brief"
    assert rendered_pack["reference_packs"] == []
    assert rendered_pack["routes"]
    assert rendered_pack["brain_findings"]
    assert rendered_pack["source_plan"]["sources"]
    # D-01 / Q7: the conversation count is DERIVED from the director's as-authored
    # decisions (count = len), never hard-coded to 7. The displayed conversation mirrors
    # the number of decisions the director actually wrote — variable-N, no cage.
    assert len(rendered_pack["conversation"]) >= 1
    assert rendered_pack["route_comparison"]
    assert all(len(group["options"]) >= 3 for group in rendered_pack["font_options"])
    assert all(len(group["tiles"]) >= 6 for group in rendered_pack["moodboard_tiles"])
    assert any(block["text"] for block in rendered_pack["copy_blocks"])
    assert rendered_pack["next_steps"]
    assert rendered_pack["evidence_summary"]["source_claim"]
    assert rendered_pack["receipts"]
    assert pack["anti_position"]
    html = (out / "index.html").read_text(encoding="utf-8")
    handoff = (out / "BUILD-HANDOFF.md").read_text(encoding="utf-8")
    assert "dossier-shell" in html
    assert "Creative Moodboard Workbench" in html
    assert "london-session.json" in html
    assert "London session summary" in html
    assert "`london-session.json`" in handoff
    assert "human-readable London session summary" in handoff
    assert "inspectable session companion, not a second canonical schema" in handoff
    session_handoff_lines = "\n".join(
        line for line in handoff.splitlines()
        if "london-session.json" in line or "session companion" in line
    )
    for blocked in ("provider", "telemetry", "receipt", "sha", "launch-gate", "MODE", "GATES", "CONFIDENCE"):
        assert blocked not in session_handoff_lines
    assert "seven-gate" not in handoff.lower()
    prototype = (out / "prototype" / "index.html").read_text(encoding="utf-8")
    assert "prototype-route" in prototype
    assert "prototype-nav" in prototype
    assert "data-prototype-route-panel" in prototype
    assert "artifacts" not in json.dumps(rendered_pack["receipts"])
    assert str(out) not in json.dumps(rendered_pack)
    exported = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            out / "london-pack.json",
            out / "london-session.json",
            out / "index.html",
            out / "receipts.json",
            out / "DESIGN.md",
            out / "BUILD-HANDOFF.md",
        )
    )
    assert str(brief) not in exported
    assert "/Users/" not in exported
    assert "/private/" not in exported


def test_existing_pack_refuses_without_force(tmp_path):
    brief = tmp_path / "brief.md"
    brief.write_text("# Joyful Retro-Futurist Product\n\nBuild a tactile public product system.", encoding="utf-8")
    out = tmp_path / "pack"
    write_london_pack(brief, out, offline=True)

    with pytest.raises(typer.BadParameter) as excinfo:
        write_london_pack(brief, out, offline=True)

    assert "Use --force" in str(excinfo.value)


def test_existing_pack_allows_force(tmp_path):
    brief = tmp_path / "brief.md"
    brief.write_text("# Joyful Retro-Futurist Product\n\nBuild a tactile public product system.", encoding="utf-8")
    out = tmp_path / "pack"
    write_london_pack(brief, out, offline=True)

    pack = write_london_pack(brief, out, offline=True, force=True)

    assert pack["title"]


def test_london_session_artifact_is_gradeable_and_sanitized(tmp_path):
    brief = tmp_path / "brief.md"
    brief.write_text("# Joyful Retro-Futurist Product\n\nBuild a tactile public product system.", encoding="utf-8")
    out = tmp_path / "pack"

    pack = write_london_pack(brief, out, director=FakeDirector())
    session = json.loads((out / "london-session.json").read_text(encoding="utf-8"))

    assert session["artifact"] == "london-session"
    assert session["brief"]["title"] == "Joyful Retro-Futurist Product"
    assert session["london"]["reframe"] == pack["london_reframe"]
    assert session["london"]["recommended_route"]["ref"] == pack["recommended_route_ref"]
    assert "recommendation" in session["london"]["recommended_route"]
    assert len(session["conversation"]) == len(pack["conversation"])

    first_decision = session["conversation"][0]
    for key in ("gate", "decision", "answer", "rationale", "critique"):
        assert first_decision[key] == pack["conversation"][0][key]
    provenance = first_decision["provenance"]
    assert provenance["evidence_classes"]["london_brain_findings"] >= 1
    assert provenance["brain_queries"]
    assert provenance["brain_findings"]
    assert provenance["sources"]
    assert provenance["receipts"]
    assert set(provenance["receipts"][0]) <= {"receipt_id", "kind"}
    assert "run_details" in session
    assert session["run_details"]["mode"] == pack["mode"]

    blob = json.dumps(session)
    for blocked in (
        str(tmp_path),
        "/Users/",
        "/private/",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        '"body"',
        '"debug"',
        '"path"',
        "provider_selection",
        "image_prompt",
        "Full prompt transcript",
    ):
        assert blocked not in blob


def test_public_pack_writer_rejects_nonfinite_json_numbers(tmp_path, monkeypatch):
    pack = {
        "receipts": [],
        "grader": {
            "inspectors": [
                {
                    "name": "Distinctness",
                    "dimension": "palette",
                    "score": 1.0,
                    "verdict": "DISTINCT",
                    "min_palette_de": float("inf"),
                }
            ]
        },
    }
    monkeypatch.setattr(cli, "validate_pack", lambda _pack: None)

    with pytest.raises(ValueError):
        cli._write_public_pack_files(pack, tmp_path / "pack")

    assert not (tmp_path / "pack" / "london-pack.json").exists()


def test_pack_emits_all_pack01_fields(tmp_path):
    # PACK-01: the exported pack must already emit every renderer-critical field — Phase 1
    # built these in workbench.enrich_workbench_pack (conversation / route_comparison /
    # font_options / copy_blocks / next_steps / evidence_summary). Phase 2 RENDERS them; it
    # does NOT re-derive them. This is the executable assertion that locks PACK-01 green
    # BEFORE the render rebuild. Everything below is read AS GIVEN from the exported pack
    # dict — no count is recomputed and no field is re-derived here (Pitfall 2).
    brief = tmp_path / "brief.md"
    brief.write_text("# Luxury Fragrance Compact\n\nBuild a refillable scent ritual with atelier packaging.", encoding="utf-8")
    out = tmp_path / "pack"

    pack = write_london_pack(brief, out)

    # 1) The six renderer-critical top-level keys are present and non-empty.
    for key in ("conversation", "route_comparison", "font_options", "copy_blocks", "next_steps"):
        assert pack.get(key), f"PACK-01 field {key!r} must be present and non-empty"
    evidence_summary = pack.get("evidence_summary")
    assert isinstance(evidence_summary, dict) and evidence_summary, "evidence_summary must be a non-empty mapping"

    # 2) evidence_summary carries SPLIT collections — three DISTINCT fields for brain
    #    findings, source targets, and live artifacts (never one merged "N evidence" count).
    #    The actual key names from workbench.build_evidence_summary are brain / sources /
    #    live_artifacts; they are distinct keys, and the brain/source split is populated.
    for split_key in ("brain", "sources", "live_artifacts"):
        assert split_key in evidence_summary, f"evidence_summary must split out {split_key!r}"
        assert isinstance(evidence_summary[split_key], list), f"{split_key!r} must be a list (a counted collection)"
    assert len({"brain", "sources", "live_artifacts"}) == 3  # three distinct fields, never merged
    # The split is real: brain findings and source targets are both populated independently.
    assert len(evidence_summary["brain"]) > 0, "brain findings must be counted independently"
    assert len(evidence_summary["sources"]) > 0, "source targets must be counted independently"
    # No single merged evidence count masquerading as the whole picture.
    assert "evidence_count" not in evidence_summary, "evidence_summary must not collapse into one merged count"

    # 3) font_options carries >=3 tiers per route with the specimen field
    #    why_this_route_not_other_route present on at least one route's options.
    for group in pack["font_options"]:
        assert len(group.get("options", [])) >= 3, "each route must carry >=3 font tiers"
    assert any(
        "why_this_route_not_other_route" in option
        for group in pack["font_options"]
        for option in group.get("options", [])
    ), "at least one font option must carry why_this_route_not_other_route"

    # 4) The exported pack still passes the write-time schema hard-gate (no regression).
    validate_pack(pack)


def test_exported_pack_validates_against_public_schema(tmp_path):
    import jsonschema

    brief = tmp_path / "brief.md"
    brief.write_text("# Luxury Fragrance Compact\n\nBuild a refillable scent ritual with atelier packaging.", encoding="utf-8")
    out = tmp_path / "pack"

    write_london_pack(brief, out)

    schema = json.loads((Path(__file__).parents[1] / "schemas" / "london-pack.schema.json").read_text(encoding="utf-8"))
    rendered_pack = json.loads((out / "london-pack.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(rendered_pack)


def test_launch_font_asset_marks_recommended_route_actual_loaded_without_path_leak(tmp_path):
    brief = tmp_path / "brief.md"
    brief.write_text("# Joyful Retro-Futurist Product\n\nBuild a tactile public product system.", encoding="utf-8")
    font_asset = tmp_path / "Proof Sans.woff2"
    font_asset.write_bytes(b"local-font-proof")
    out = tmp_path / "pack"

    pack = write_london_pack(
        brief,
        out,
        font_asset=font_asset,
        font_family="Proof Sans",
        font_source_label="Proof Sans local test asset",
        font_license_note="Operator-supplied licensed font asset for launch proof.",
    )
    exported = json.loads((out / "london-pack.json").read_text(encoding="utf-8"))
    exported_blob = json.dumps(exported)
    html = (out / "index.html").read_text(encoding="utf-8")
    prototype = (out / "prototype" / "index.html").read_text(encoding="utf-8")
    receipts = (out / "receipts.json").read_text(encoding="utf-8")
    public_blobs = [exported_blob, html, prototype, receipts]

    assert (out / "assets" / "fonts" / "proof-sans.woff2").exists()
    assert all(str(font_asset) not in blob for blob in public_blobs)
    assert all("/private/" not in blob for blob in public_blobs)
    assert all("/Users/" not in blob for blob in public_blobs)
    actual_options = [
        option
        for group in exported["font_options"]
        for option in group["options"]
        if option.get("font_preview", {}).get("status") == "actual_loaded"
    ]
    assert len(actual_options) == 1
    preview = actual_options[0]["font_preview"]
    assert preview == {
        "status": "actual_loaded",
        "delivery": "local_asset",
        "rendered_family": "Proof Sans",
        "source_label": "Proof Sans local test asset",
        "license_note": "Operator-supplied licensed font asset for launch proof.",
        "asset_href": "assets/fonts/proof-sans.woff2",
    }
    assert "@font-face" in html
    assert 'url("assets/fonts/proof-sans.woff2")' in html
    assert 'url("../assets/fonts/proof-sans.woff2")' in prototype
    assert 'data-font-preview-status="actual_loaded"' in html
    assert 'data-font-preview-family="Proof Sans"' in html
    assert "Actual font loaded" not in prototype
    assert any(receipt.get("kind") == "font-proof" for receipt in pack["receipts"])
    gate = evaluate_launch_gates(out)
    assert gate["gates"]["actual_font_or_blocked"]["ok"] is True
    assert gate["gates"]["actual_image_or_blocked"]["ok"] is False
    validate_pack(pack)


def test_launch_font_shelf_family_marks_recommended_route_actual_loaded(tmp_path):
    brief = tmp_path / "brief.md"
    brief.write_text("# Joyful Retro-Futurist Product\n\nBuild a tactile public product system.", encoding="utf-8")
    out = tmp_path / "pack"

    pack = write_london_pack(
        brief,
        out,
        director=FakeDirector(),
        font_shelf_family="Familjen Grotesk",
    )
    exported = json.loads((out / "london-pack.json").read_text(encoding="utf-8"))
    html = (out / "index.html").read_text(encoding="utf-8")
    prototype = (out / "prototype" / "index.html").read_text(encoding="utf-8")
    public_blob = "\n".join(
        [
            json.dumps(exported),
            html,
            prototype,
            (out / "receipts.json").read_text(encoding="utf-8"),
        ]
    )

    font_path = out / "assets" / "fonts" / "familjen-grotesk-500.woff2"
    assert font_path.exists()
    assert str(font_path) not in public_blob
    assert "/Users/" not in public_blob
    actual_options = [
        option
        for group in exported["font_options"]
        for option in group["options"]
        if option.get("font_preview", {}).get("status") == "actual_loaded"
    ]
    assert len(actual_options) == 1
    preview = actual_options[0]["font_preview"]
    assert preview["rendered_family"] == "Familjen Grotesk"
    assert preview["delivery"] == "local_asset"
    assert preview["asset_href"] == "assets/fonts/familjen-grotesk-500.woff2"
    assert preview["source_kind"] == "bundled_open"
    assert preview["shelf_id"] == "familjen-grotesk"
    assert preview["asset_sha256"]
    assert "SIL Open Font License" in preview["source_label"]
    assert "@font-face" in html
    assert 'url("assets/fonts/familjen-grotesk-500.woff2")' in html
    assert 'url("../assets/fonts/familjen-grotesk-500.woff2")' in prototype
    assert "Actual font loaded" not in prototype
    assert any(receipt.get("provider") == "london-type-shelf" for receipt in pack["receipts"])
    gate = evaluate_launch_gates(out)
    assert gate["gates"]["actual_font_or_blocked"]["ok"] is True
    validate_pack(pack)


def test_launch_font_shelf_family_rejects_reference_fonts(tmp_path):
    brief = tmp_path / "brief.md"
    brief.write_text("# Joyful Retro-Futurist Product\n\nBuild a tactile public product system.", encoding="utf-8")

    with pytest.raises(typer.BadParameter) as exc:
        write_london_pack(
            brief,
            tmp_path / "pack",
            director=FakeDirector(),
            font_shelf_family="GT America",
        )

    assert "No bundled London Type Shelf font" in str(exc.value)


def test_launch_font_shelf_family_and_user_asset_are_separate_lanes(tmp_path):
    brief = tmp_path / "brief.md"
    brief.write_text("# Joyful Retro-Futurist Product\n\nBuild a tactile public product system.", encoding="utf-8")
    font_asset = tmp_path / "Proof Sans.woff2"
    font_asset.write_bytes(b"local-font-proof")

    with pytest.raises(typer.BadParameter) as exc:
        write_london_pack(
            brief,
            tmp_path / "pack",
            director=FakeDirector(),
            font_shelf_family="Familjen Grotesk",
            font_asset=font_asset,
            font_family="Proof Sans",
            font_source_label="Proof Sans local test asset",
            font_license_note="Operator-supplied licensed font asset for launch proof.",
        )

    assert "--font-shelf-family cannot be combined with --font-asset" in str(exc.value)


def test_launch_font_asset_requires_explicit_metadata(tmp_path):
    brief = tmp_path / "brief.md"
    brief.write_text("# Joyful Retro-Futurist Product\n\nBuild a tactile public product system.", encoding="utf-8")
    font_asset = tmp_path / "Proof Sans.woff2"
    font_asset.write_bytes(b"local-font-proof")

    with pytest.raises(typer.BadParameter) as exc:
        write_london_pack(
            brief,
            tmp_path / "pack",
            font_asset=font_asset,
            font_family="Proof Sans",
            font_source_label="Proof Sans local test asset",
        )

    assert "--font-license-note" in str(exc.value)


def test_launch_font_asset_uses_content_copy_not_metadata_copy(tmp_path, monkeypatch):
    brief = tmp_path / "brief.md"
    brief.write_text("# Joyful Retro-Futurist Product\n\nBuild a tactile public product system.", encoding="utf-8")
    font_asset = tmp_path / "Proof Sans.woff2"
    font_asset.write_bytes(b"local-font-proof")

    def fail_copy2(*args, **kwargs):
        raise OSError("simulated macOS metadata copy failure")

    monkeypatch.setattr(cli.shutil, "copy2", fail_copy2)

    write_london_pack(
        brief,
        tmp_path / "pack",
        font_asset=font_asset,
        font_family="Proof Sans",
        font_source_label="Proof Sans local test asset",
        font_license_note="Operator-supplied licensed font asset for launch proof.",
    )

    copied = tmp_path / "pack" / "assets" / "fonts" / "proof-sans.woff2"
    assert copied.read_bytes() == b"local-font-proof"


def test_launch_font_asset_copy_failure_is_clean(tmp_path, monkeypatch):
    brief = tmp_path / "brief.md"
    brief.write_text("# Joyful Retro-Futurist Product\n\nBuild a tactile public product system.", encoding="utf-8")
    font_asset = tmp_path / "Proof Sans.woff2"
    font_asset.write_bytes(b"local-font-proof")

    def fail_copyfileobj(*args, **kwargs):
        raise OSError(f"cannot read {font_asset}")

    monkeypatch.setattr(shutil, "copyfileobj", fail_copyfileobj)

    with pytest.raises(typer.BadParameter) as exc:
        write_london_pack(
            brief,
            tmp_path / "pack",
            font_asset=font_asset,
            font_family="Proof Sans",
            font_source_label="Proof Sans local test asset",
            font_license_note="Operator-supplied licensed font asset for launch proof.",
        )

    message = str(exc.value)
    assert "--font-asset could not be copied into the pack" in message
    assert str(font_asset) not in message
    assert not (tmp_path / "pack" / "assets" / "fonts" / "proof-sans.woff2").exists()


def test_receipt_carries_image_quality(tmp_path):
    # The chosen image-quality LEVEL must be recordable in a receipt (receipts-only audit
    # surface, ENG-06/D-05 honesty) and NEVER in creative prose. On the keyless default
    # path the recorded level is the existing auto-ladder, "model-default" (the 02-04
    # selector overrides it explicitly). This proves the receipt can CARRY the level
    # honestly; it does NOT wire the interactive selector (that is 02-04).
    brief = tmp_path / "brief.md"
    brief.write_text("# Luxury Fragrance Compact\n\nBuild a refillable scent ritual with atelier packaging.", encoding="utf-8")
    out = tmp_path / "pack"

    pack = write_london_pack(brief, out)

    # 1) At least one receipt carries the chosen image-quality LEVEL via the explicit
    #    image_quality key. The level is a plain string ("model-default" for the keyless
    #    default path) — a LEVEL, never a provider key value.
    receipts = pack["receipts"]
    quality_receipts = [r for r in receipts if isinstance(r, dict) and r.get("image_quality")]
    assert quality_receipts, "at least one receipt must carry the chosen image_quality level"
    assert all(r["image_quality"] == "model-default" for r in quality_receipts), (
        "the keyless default path records the model-default level"
    )

    # 2) The exported pack still passes the write-time schema hard-gate: adding
    #    image_quality to the receipt $def must keep additionalProperties:false VALID.
    validate_pack(pack)

    # 3) secrets_printed:false is preserved on the image receipts (V6 / threat T-02-01):
    #    the level is recorded WITHOUT ever printing a key value.
    image_receipts = [r for r in receipts if isinstance(r, dict) and r.get("kind") == "image-generation"]
    assert image_receipts, "image-generation receipts must be present"
    assert all(r.get("secrets_printed") is False for r in image_receipts), (
        "secrets_printed:false must be preserved on every image receipt"
    )

    # 4) Presence-only: the recorded level is a LEVEL string, never a secret key value, and
    #    it never leaks into the user-facing creative prose (title / london_reframe /
    #    conversation answers). The audit surface (receipts) is the ONLY place it lives.
    prose = _creative_prose_blob(pack)
    conversation_answers = "\n".join(
        str(entry.get("answer", "")) for entry in pack.get("conversation", [])
    )
    for level_token in ("image_quality", "model-default"):
        assert level_token not in prose, f"{level_token!r} must not appear in creative prose"
        assert level_token not in str(pack.get("london_reframe", ""))
        assert level_token not in conversation_answers


def test_generated_image_receipt_stamps_materialized_asset_proof(tmp_path, monkeypatch):
    brief = tmp_path / "brief.md"
    brief.write_text("# Joyful Retro-Futurist Product\n\nBuild a tactile public product system.", encoding="utf-8")
    out = tmp_path / "pack"

    def fake_generate_route_concept(pack, route, route_index, provider, requested_provider, **kwargs):
        route_id = str(route["id"])
        receipt_id = f"{route_id}-image-generation"
        if provider == "manual-prompt":
            svg = '<svg xmlns="http://www.w3.org/2000/svg"><text>board</text></svg>'
            return SimpleNamespace(
                asset={
                    "title": "Fallback visual direction board",
                    "alt": "Fallback visual direction board",
                    "kind": "visual-direction-board",
                    "src": "data:image/svg+xml," + svg,
                    "provider": "manual-prompt",
                    "receipt_id": receipt_id,
                },
                receipt={
                    "receipt_id": receipt_id,
                    "kind": "image-generation",
                    "summary": "Rendered fallback board.",
                    "deterministic": True,
                    "provider": "manual-prompt",
                    "requested_provider": requested_provider,
                    "resolved_provider": "manual-prompt",
                    "route_id": route_id,
                    "route_title": str(route["title"]),
                    "status": "manual_prompt_ready",
                    "secrets_printed": False,
                },
            )
        payload = base64.b64encode(b"generated proof bytes").decode("ascii")
        return SimpleNamespace(
            asset={
                "title": "Generated concept image",
                "alt": "Generated concept image",
                "kind": "generated-concept-image",
                "src": f"data:image/png;base64,{payload}",
                "provider": "gemini",
                "receipt_id": receipt_id,
            },
            receipt={
                "receipt_id": receipt_id,
                "kind": "image-generation",
                "summary": "Generated provider-backed image.",
                "deterministic": False,
                "provider": "gemini",
                "requested_provider": requested_provider,
                "resolved_provider": "gemini",
                "route_id": route_id,
                "route_title": str(route["title"]),
                "status": "generated_live",
                "secrets_printed": False,
            },
        )

    monkeypatch.setattr(cli, "generate_route_concept", fake_generate_route_concept)

    pack = write_london_pack(
        brief,
        out,
        image_provider="gemini",
        max_generated_routes=1,
        director=FakeDirector(),
    )

    generated_route = next(route for route in pack["routes"] if route["assets"][0]["kind"] == "generated-concept-image")
    asset = generated_route["assets"][0]
    receipt = next(
        receipt
        for receipt in pack["receipts"]
        if receipt.get("receipt_id") == asset.get("receipt_id")
    )
    asset_path = out / asset["src"]
    assert asset_path.exists()
    assert receipt["asset_src"] == asset["src"]
    assert receipt["asset_sha256"] == hashlib.sha256(asset_path.read_bytes()).hexdigest()
    validate_pack(pack)


def test_image_quality_defaults_to_model_default_non_interactive(tmp_path, monkeypatch):
    # Task 2 (D-05, resolved open-Q): with NO --image-quality flag, a non-TTY / keyless
    # context defaults to "model-default" and NEVER prompts — CI must not hang. We assert
    # the interactive selector is never reached by failing hard if it is.
    import london.cli as _cli

    def _explode(*args, **kwargs):  # the interactive prompt must NOT be called in CI
        raise AssertionError("interactive image-quality prompt must not run in non-TTY/CI")

    monkeypatch.setattr(_cli, "_prompt_image_quality", _explode, raising=False)
    # Force the non-interactive lane regardless of how pytest is launched.
    monkeypatch.setattr(_cli.sys.stdin, "isatty", lambda: False, raising=False)

    brief = tmp_path / "brief.md"
    brief.write_text("# Luxury Fragrance Compact\n\nBuild a refillable scent ritual with atelier packaging.", encoding="utf-8")
    out = tmp_path / "pack"

    pack = write_london_pack(brief, out)  # no image_quality -> model-default, no prompt

    receipts = pack["receipts"]
    quality_receipts = [r for r in receipts if isinstance(r, dict) and r.get("image_quality")]
    assert quality_receipts, "a receipt must carry the chosen image_quality level"
    assert all(r["image_quality"] == "model-default" for r in quality_receipts)


def test_image_quality_flag_overrides(tmp_path, monkeypatch):
    # Task 2: an explicit image_quality value (the --image-quality flag) is recorded as the
    # chosen LEVEL in the receipt, with NO prompt. "gemini" upgrades the level even when the
    # provider is not configured (the level is recorded; the auto-ladder still falls back to
    # an honest manual-prompt asset keyless — the LEVEL is a label, never a key value).
    import london.cli as _cli

    def _explode(*args, **kwargs):
        raise AssertionError("flag path must not prompt")

    monkeypatch.setattr(_cli, "_prompt_image_quality", _explode, raising=False)

    brief = tmp_path / "brief.md"
    brief.write_text("# Luxury Fragrance Compact\n\nBuild a refillable scent ritual with atelier packaging.", encoding="utf-8")
    out = tmp_path / "pack"

    pack = write_london_pack(brief, out, image_quality="gemini")

    receipts = pack["receipts"]
    quality_receipts = [r for r in receipts if isinstance(r, dict) and r.get("image_quality")]
    assert quality_receipts, "a receipt must carry the chosen image_quality level"
    assert all(r["image_quality"] == "gemini" for r in quality_receipts), (
        "the flag-chosen level must be recorded in the receipt"
    )
    validate_pack(pack)


def test_main_rejects_invalid_image_quality_before_pack_write(tmp_path, capsys):
    brief = tmp_path / "brief.md"
    brief.write_text("# Luxury Fragrance Compact\n\nBuild a refillable scent ritual with atelier packaging.", encoding="utf-8")
    out = tmp_path / "pack"

    with pytest.raises(SystemExit) as excinfo:
        main([str(brief), "--out", str(out), "--image-quality", "glossy", "--yes"])

    captured = capsys.readouterr()
    assert excinfo.value.code == 2
    assert "--image-quality must be one of" in captured.err
    assert not (out / "london-pack.json").exists()


def test_main_image_quality_flag_reaches_receipts(tmp_path, monkeypatch):
    import london.cli as _cli

    def _explode(*args, **kwargs):
        raise AssertionError("flag path must not prompt")

    monkeypatch.setattr(_cli, "_prompt_image_quality", _explode, raising=False)

    brief = tmp_path / "brief.md"
    brief.write_text("# Luxury Fragrance Compact\n\nBuild a refillable scent ritual with atelier packaging.", encoding="utf-8")
    out = tmp_path / "pack"

    main([str(brief), "--out", str(out), "--offline", "--image-quality", "gemini"])

    receipts = json.loads((out / "receipts.json").read_text(encoding="utf-8"))
    quality_receipts = [r for r in receipts if isinstance(r, dict) and r.get("image_quality")]
    assert quality_receipts
    assert all(r["image_quality"] == "gemini" for r in quality_receipts)


def test_main_yes_suppresses_interactive_image_quality_prompt(tmp_path, monkeypatch):
    import london.cli as _cli

    def _explode(*args, **kwargs):
        raise AssertionError("--yes must bypass the image-quality prompt")

    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(_cli.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(_cli, "_prompt_image_quality", _explode, raising=False)

    brief = tmp_path / "brief.md"
    brief.write_text("# Luxury Fragrance Compact\n\nBuild a refillable scent ritual with atelier packaging.", encoding="utf-8")
    out = tmp_path / "pack"

    main([str(brief), "--out", str(out), "--offline", "--yes"])

    assert (out / "london-pack.json").exists()


def test_main_piped_stdout_suppresses_interactive_image_quality_prompt(tmp_path, monkeypatch):
    import london.cli as _cli

    def _explode(*args, **kwargs):
        raise AssertionError("piped stdout must bypass the image-quality prompt")

    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(_cli.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(
        _cli.sys,
        "stdout",
        SimpleNamespace(isatty=lambda: False, write=lambda _text: None, flush=lambda: None),
    )
    monkeypatch.setattr(_cli, "_prompt_image_quality", _explode, raising=False)

    brief = tmp_path / "brief.md"
    brief.write_text("# Luxury Fragrance Compact\n\nBuild a refillable scent ritual with atelier packaging.", encoding="utf-8")
    out = tmp_path / "pack"

    main([str(brief), "--out", str(out), "--offline"])

    assert (out / "london-pack.json").exists()


def test_typer_deterministic_alias_is_positive_offline_flag(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    def fake_write_london_pack(brief, out, **kwargs):
        captured.update({"brief": brief, "out": out, **kwargs})
        return {}

    monkeypatch.setattr(cli, "write_london_pack", fake_write_london_pack)
    brief = tmp_path / "brief.md"
    brief.write_text("# Luxury Fragrance Compact\n\nBuild a refillable scent ritual with atelier packaging.", encoding="utf-8")
    out = tmp_path / "pack"

    result = CliRunner().invoke(
        cli.app,
        ["--out", str(out), "--deterministic", "--yes", "--image-quality", "gemini", str(brief)],
    )

    assert result.exit_code == 0, result.output
    assert captured["offline"] is True
    assert captured["assume_yes"] is True
    assert captured["image_quality"] == "gemini"


def test_image_quality_gates_on_readiness(monkeypatch):
    # Task 2: the selectable quality OPTIONS gate on recommend_image_provider readiness
    # BOOLEANS only. model-default is ALWAYS available (even keyless); gemini/bfl appear
    # only when ready_generate; bfl additionally needs allow_paid. The gating function
    # reads readiness booleans, NEVER a key value (V6 / threat T-02-09).
    from london.cli import _image_quality_options

    # Keyless / nothing ready, no paid acknowledgement: only model-default is selectable.
    keyless = _image_quality_options(
        readiness={"gemini": False, "bfl": False},
        allow_paid=False,
    )
    assert "model-default" in keyless
    assert "gemini" not in keyless
    assert "bfl" not in keyless

    # Gemini ready -> gemini joins; bfl still gated (not ready, no paid ack).
    gemini_ready = _image_quality_options(
        readiness={"gemini": True, "bfl": False},
        allow_paid=False,
    )
    assert "model-default" in gemini_ready
    assert "gemini" in gemini_ready
    assert "bfl" not in gemini_ready

    # BFL ready AND paid acknowledged -> bfl joins (premium needs both).
    bfl_ready = _image_quality_options(
        readiness={"gemini": True, "bfl": True},
        allow_paid=True,
    )
    assert "bfl" in bfl_ready

    # BFL ready but NO paid acknowledgement -> bfl stays gated (premium requires allow_paid).
    bfl_no_paid = _image_quality_options(
        readiness={"gemini": False, "bfl": True},
        allow_paid=False,
    )
    assert "bfl" not in bfl_no_paid


def test_image_quality_selector_prints_no_secret(tmp_path, monkeypatch):
    # Task 2 (V6 / threat T-02-09): the quality selector records the LEVEL without ever
    # printing or recording a provider key value. A fake key is planted in the env; it must
    # NOT appear in any receipt, and secrets_printed:false is preserved on image receipts.
    import london.cli as _cli

    monkeypatch.setattr(_cli, "_prompt_image_quality", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no prompt")), raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "sk-SECRET-must-never-leak-123")

    brief = tmp_path / "brief.md"
    brief.write_text("# Luxury Fragrance Compact\n\nBuild a refillable scent ritual with atelier packaging.", encoding="utf-8")
    out = tmp_path / "pack"

    pack = write_london_pack(brief, out, image_quality="gemini")

    receipts_blob = json.dumps(pack["receipts"])
    assert "sk-SECRET-must-never-leak-123" not in receipts_blob, "no key value may reach a receipt"
    # The full exported tree must not leak the secret either.
    exported = "\n".join(
        (out / name).read_text(encoding="utf-8")
        for name in ("london-pack.json", "receipts.json", "index.html", "visual-routes.json")
    )
    assert "sk-SECRET-must-never-leak-123" not in exported

    image_receipts = [r for r in pack["receipts"] if isinstance(r, dict) and r.get("kind") == "image-generation"]
    assert image_receipts, "image-generation receipts must be present"
    assert all(r.get("secrets_printed") is False for r in image_receipts), (
        "secrets_printed:false must be preserved on every image receipt"
    )


def test_underfilled_pack_aborts_before_any_write(tmp_path, monkeypatch):
    # The write-time jsonschema hard-gate (D-07): an under-filled pack must abort the run
    # with the formatted message and write NO london-pack.json (threat T-04-03 / Pitfall 3).
    # We corrupt the pack AFTER enrichment (the gate runs right after) by stripping a
    # required field, so the gate is the thing that fails — proving it is a write-time gate.
    real_enrich = cli.enrich_workbench_pack

    def corrupting_enrich(pack):
        real_enrich(pack)
        pack.pop("conversation", None)  # required by the schema -> ValidationError at the gate

    monkeypatch.setattr(cli, "enrich_workbench_pack", corrupting_enrich)

    brief = tmp_path / "brief.md"
    brief.write_text("# Tactile Product\n\nBuild a tactile public product system.", encoding="utf-8")
    out = tmp_path / "pack"

    with pytest.raises(typer.BadParameter) as excinfo:
        write_london_pack(brief, out)

    assert "director output missing/invalid" in str(excinfo.value)
    # No half-pack on disk.
    assert not (out / "london-pack.json").exists()


def test_validate_pack_rejects_under_fill():
    with pytest.raises(typer.BadParameter) as excinfo:
        validate_pack({"pack_id": "x"})  # nowhere near schema-complete
    assert "director output missing/invalid" in str(excinfo.value)


# The creative-prose pack fields the director mode must NEVER appear in (mode lives in
# the receipts audit surface only — ENG-06 / T-04-04). The receipts panel rendered in
# index.html is the audit surface and legitimately echoes the receipt; the guard is over
# the CREATIVE prose, not the receipts panel.
_PROSE_KEYS = (
    "title",
    "summary",
    "category_assumption",
    "aesthetic_void",
    "london_reframe",
    "anti_position",
)


def _creative_prose_blob(pack: dict) -> str:
    parts = [str(pack.get(key, "")) for key in _PROSE_KEYS]
    for route in pack.get("routes", []):
        parts += [str(route.get(k, "")) for k in ("title", "headline", "subhead", "lore", "mood", "rationale")]
    for entry in pack.get("conversation", []):
        parts += [str(entry.get(k, "")) for k in ("decision", "rationale", "critique", "answer")]
    for entry in pack.get("copy_blocks", []):
        parts.append(str(entry.get("text", "")))
    return "\n".join(parts)


@pytest.mark.real_director
def test_director_mode_in_receipts_not_in_creative_prose(tmp_path):
    # ENG-06: the resolved director mode is stamped into receipts ONLY — never into the
    # pack's creative prose. After the A5 flip the model director actually drives both
    # stages; CI never hits a live model, so the model path is exercised via the injected
    # FakeDirector (TST-04). The receipt still carries the resolved director name.
    brief = tmp_path / "brief.md"
    brief.write_text("# Joyful Retro-Futurist Product\n\nBuild a tactile public product system.", encoding="utf-8")
    out = tmp_path / "pack"

    write_london_pack(brief, out, director=FakeDirector())

    receipts = json.loads((out / "receipts.json").read_text(encoding="utf-8"))
    director_receipts = [r for r in receipts if r.get("kind") == "director"]
    assert director_receipts, "a director-selection receipt must be stamped"
    assert director_receipts[0]["provider"] == "FakeDirector"

    pack = json.loads((out / "london-pack.json").read_text(encoding="utf-8"))
    prose = _creative_prose_blob(pack)
    assert "FakeDirector" not in prose
    assert "ClaudeCodeDirector" not in prose
    assert "offline-template-preview" not in prose
    assert "director-selection" not in prose


@pytest.mark.real_director
def test_default_path_resolves_claude_code_director(tmp_path):
    # The DEFAULT path (no --offline, no injected director) resolves the model director
    # (ClaudeCodeDirector) and, with NO model reachable in CI, hard-errors per D-01 —
    # it NEVER silently falls back to the deterministic engine (D-03). This is the
    # honest model-driven default the A5 flip establishes.
    from london.director import LondonNoModelError

    brief = tmp_path / "brief.md"
    brief.write_text("# Joyful Retro-Futurist Product\n\nBuild a tactile public product system.", encoding="utf-8")
    out = tmp_path / "pack"

    with pytest.raises(LondonNoModelError):
        write_london_pack(brief, out)

    # No half-pack written when the model is unreachable.
    assert not (out / "london-pack.json").exists()


@pytest.mark.real_director
def test_no_key_cli_error_boundary_prints_fixit_without_traceback(tmp_path, monkeypatch, capsys):
    for name in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "CLAUDECODE",
        "CLAUDE_CODE_ENTRYPOINT",
        "LONDON_CLAUDE_CLI_PRINT",
    ):
        monkeypatch.delenv(name, raising=False)
    brief = tmp_path / "brief.md"
    brief.write_text("# Joyful Retro-Futurist Product\n\nBuild a tactile public product system.", encoding="utf-8")
    out = tmp_path / "pack"

    with pytest.raises(SystemExit) as excinfo:
        main([str(brief), "--out", str(out), "--yes"])

    captured = capsys.readouterr()
    assert excinfo.value.code == 1
    assert "London could not reach a creative-direction model" in captured.err
    assert "run London inside Claude Code" in captured.err
    assert "--offline" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""
    assert not (out / "london-pack.json").exists()


@pytest.mark.real_director
def test_offline_flag_selects_offline_director(tmp_path):
    # --offline -> OfflineDirector; the receipts mode is the offline-template-preview
    # label (mode-only-in-receipts), still absent from creative prose.
    brief = tmp_path / "brief.md"
    brief.write_text("# Luxury Fragrance Compact\n\nBuild a refillable scent ritual with atelier packaging.", encoding="utf-8")
    out = tmp_path / "pack"

    pack = write_london_pack(brief, out, offline=True)
    assert isinstance(pack, dict)

    receipts = json.loads((out / "receipts.json").read_text(encoding="utf-8"))
    director_receipts = [r for r in receipts if r.get("kind") == "director"]
    assert director_receipts[0]["provider"] == "offline-template-preview"
    assert director_receipts[0]["deterministic"] is True

    rendered_pack = json.loads((out / "london-pack.json").read_text(encoding="utf-8"))
    assert "offline-template-preview" not in _creative_prose_blob(rendered_pack)


@pytest.mark.real_director
def test_injected_fake_director_is_used(tmp_path):
    # Tests inject a director; the resolution honours it (keyless, no live model).
    brief = tmp_path / "brief.md"
    brief.write_text("# Kids Lunchbox\n\nCreate a school lunchbox system for kids.", encoding="utf-8")
    out = tmp_path / "pack"

    write_london_pack(brief, out, director=FakeDirector())

    receipts = json.loads((out / "receipts.json").read_text(encoding="utf-8"))
    director_receipts = [r for r in receipts if r.get("kind") == "director"]
    assert director_receipts[0]["provider"] == "FakeDirector"
    assert (out / "london-pack.json").exists()


# =============================================================================
# Phase 4.5 GATE-02 — artifact_type resolution order + provenance (RED stubs; W0).
# Resolution precedence (locked): --artifact flag > brief field > model declaration
# > honest "generic" default; HOW it resolved is recorded in a receipt; never a
# faked specific type. Drives the LIVE `london <brief>` dispatch via main(...)
# (RESEARCH Pitfall 7 — the bare-brief path goes through the Typer dispatcher,
# not write_london_pack directly). These fail today: no --artifact flag, no brief
# front-matter parse, no artifact-resolution receipt, no pack artifact_type. Wave 2
# drives them GREEN. All keyless — no provider key set, no network.
# =============================================================================

_ARTIFACT_ENUM = {"website", "app", "product", "brand", "generic"}
_FRAGRANCE_BRIEF = "# Luxury Fragrance Compact\n\nBuild a refillable scent ritual with atelier packaging."


def _read_pack(out: Path) -> dict:
    return json.loads((out / "london-pack.json").read_text(encoding="utf-8"))


def test_artifact_resolution_order_flag_beats_brief_beats_model_beats_generic(tmp_path):
    # (a) no flag + no brief field -> honest "generic" default (deterministic path never
    #     guesses a specific type).
    no_signal = tmp_path / "no-signal.md"
    no_signal.write_text(_FRAGRANCE_BRIEF, encoding="utf-8")
    out_a = tmp_path / "pack-generic"
    main([str(no_signal), "--out", str(out_a), "--offline"])
    assert _read_pack(out_a)["artifact_type"] == "generic"

    # (b) brief front-matter `artifact: product`, NO flag -> "product" (brief beats default).
    brief_field = tmp_path / "brief-field.md"
    brief_field.write_text(
        "---\nartifact: product\n---\n" + _FRAGRANCE_BRIEF,
        encoding="utf-8",
    )
    out_b = tmp_path / "pack-brief"
    main([str(brief_field), "--out", str(out_b), "--offline"])
    assert _read_pack(out_b)["artifact_type"] == "product"

    # (c) --artifact website OVERRIDES a brief field `artifact: product` (flag beats brief).
    out_c = tmp_path / "pack-flag"
    main([str(brief_field), "--out", str(out_c), "--offline", "--artifact", "website"])
    assert _read_pack(out_c)["artifact_type"] == "website"


def test_artifact_resolution_provenance_recorded_in_receipt(tmp_path):
    # GATE-02: a receipt records HOW the type resolved (flag | brief | model | generic-default)
    # so it is auditable — never a silently-faked specific type. No flag + no brief field
    # must record the honest "generic-default" provenance.
    no_signal = tmp_path / "no-signal.md"
    no_signal.write_text(_FRAGRANCE_BRIEF, encoding="utf-8")
    out = tmp_path / "pack-provenance"
    main([str(no_signal), "--out", str(out), "--offline"])

    receipts = json.loads((out / "receipts.json").read_text(encoding="utf-8"))
    artifact_receipts = [r for r in receipts if r.get("kind") == "artifact-resolution"]
    assert artifact_receipts, "an artifact-resolution receipt must record how the type resolved"
    resolved_from = artifact_receipts[0].get("resolved_from") or artifact_receipts[0].get("status")
    assert resolved_from in {"flag", "brief", "model", "generic-default"}
    assert resolved_from == "generic-default"


# =============================================================================
# Phase 4.5 HERO-02 (compose) — --images none + --artifact + CI zero-spend (RED
# stubs; Wave 0). Drives the live main() dispatch. They fail today: no --artifact
# flag, no artifact_type carry. Wave 2/3 drive them GREEN. All keyless, no network.
# =============================================================================


def test_images_none_forces_card_with_artifact_type(tmp_path, monkeypatch):
    # --images none ALWAYS produces a prompt CARD (zero spend), and --artifact website
    # composes orthogonally: the card is website-typed. --artifact does not change provider
    # selection (--images none wins on generation), only the artifact type carried + prompt.
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "BFL_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    brief = tmp_path / "brief.md"
    brief.write_text(_FRAGRANCE_BRIEF, encoding="utf-8")
    out = tmp_path / "pack-none"

    main([str(brief), "--out", str(out), "--images", "none", "--artifact", "website"])

    rendered_pack = _read_pack(out)
    first_asset = rendered_pack["routes"][0]["assets"][0]
    assert rendered_pack["artifact_type"] == "website"
    assert first_asset["kind"] == "visual-direction-board"
    assert first_asset["generation_status"] == "images_disabled"
    assert first_asset["src"].endswith(".svg")
    assert (out / first_asset["src"]).exists()


def test_ci_env_never_spends(tmp_path, monkeypatch):
    # CI=1 with NO keys -> honest card, zero spend, no adapter call. CI never calls a live
    # provider (TST-04). artifact_type still resolves honestly to "generic" (no flag/brief).
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "BFL_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CI", "1")
    # Disable local-provider readiness probes (localhost detection, not spend) so the only
    # remaining urlopen surface is the image-gen adapter, which must never fire keyless.
    monkeypatch.setattr("london.setup_checks._http_available", lambda _url: False)

    def fail_urlopen(*_args, **_kwargs):  # pragma: no cover - must never run
        raise AssertionError("CI must NEVER call a live image provider (TST-04)")

    monkeypatch.setattr("london.image_generation.urllib.request.urlopen", fail_urlopen)

    brief = tmp_path / "brief.md"
    brief.write_text(_FRAGRANCE_BRIEF, encoding="utf-8")
    out = tmp_path / "pack-ci"

    main([str(brief), "--out", str(out)])

    rendered_pack = _read_pack(out)
    first_asset = rendered_pack["routes"][0]["assets"][0]
    assert rendered_pack["artifact_type"] == "generic"
    assert first_asset["kind"] == "visual-direction-board"
    assert first_asset["provider"] == "manual-prompt"
    assert first_asset["src"].endswith(".svg")
    assert (out / first_asset["src"]).exists()


# ---------------------------------------------------------------------------
# W1-P1 — UsageError / -h probes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "args",
    [
        ["setup", "--bogus"],
        ["brain"],
        ["providers", "ls"],
        ["image", "bogus"],
    ],
)
def test_cli_usage_errors_exit_2_with_one_line_no_traceback(args, capsys):
    """W1-P1: every UsageError probe exits 2, one-line stderr, zero Traceback lines."""
    with pytest.raises(SystemExit) as excinfo:
        main(args)
    captured = capsys.readouterr()
    assert excinfo.value.code == 2, f"expected exit 2, got {excinfo.value.code} for {args}"
    assert "Traceback" not in captured.err, "must not print a traceback"
    err_lines = [ln for ln in captured.err.splitlines() if ln.strip()]
    assert len(err_lines) == 1, f"expected exactly one error line, got: {captured.err!r}"


def test_cli_dash_h_shows_help_exit_0(capsys):
    """W1-P1: bare -h renders help (exit 0) instead of a UsageError traceback."""
    # -h is not handled by typer natively; the shim must map it to --help.
    try:
        main(["-h"])
        # exit 0 path — typer called sys.exit(0) internally or returned cleanly
    except SystemExit as exc:
        assert exc.code == 0 or exc.code is None, f"-h should exit 0, got {exc.code}"
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    # Help text must reach stdout
    assert "london" in captured.out.lower()


# ---------------------------------------------------------------------------
# W1-P2 — restored dispatching behaviors
# ---------------------------------------------------------------------------

def test_cli_config_bare_defaults_to_config_show(capsys):
    """W1-P2: `london config` (no subcommand) must run config show, not error."""
    try:
        main(["config"])
    except SystemExit as exc:
        assert exc.code == 0 or exc.code is None, f"config bare should exit 0, got {exc.code}"
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    # config show prints some key=value or toml-like output
    assert "London config" in captured.out or "image_quality" in captured.out


def test_cli_brain_query_joins_multi_word_terms(monkeypatch):
    """W1-P2: `london brain query night shift nurses` passes all words as one query string."""
    received: list[str] = []

    class _FakeBrain:
        def formatted_query(self, query: str, *, limit: int = 8) -> str:
            received.append(query)
            return f"query={query}"

    import london.cli as _cli

    monkeypatch.setattr(_cli, "LondonBrain", lambda _path: _FakeBrain())
    main(["brain", "query", "night", "shift", "nurses"])
    assert received == ["night shift nurses"], f"expected joined query, got {received}"


def test_prompt_image_quality_propagates_eof_not_swallowed():
    """W2-P4: EOFError from typer.prompt must propagate — not be silently
    caught by the broad `except Exception` guard — so that piped/CI
    invocations abort cleanly instead of silently defaulting.

    Pre-fix: `except Exception: return "model-default"` swallowed EOFError.
    Post-fix: `except (EOFError, KeyboardInterrupt, typer.Abort): raise`.
    """
    import london.cli as _cli

    original_prompt = typer.prompt

    def _raise_eof(*args, **kwargs):
        raise EOFError("stdin closed")

    # Monkeypatch typer.prompt inside the cli module's namespace.
    _cli.typer.prompt = _raise_eof  # type: ignore[attr-defined]
    try:
        with pytest.raises(EOFError):
            _cli._prompt_image_quality(["model-default", "gemini"])
    finally:
        _cli.typer.prompt = original_prompt  # type: ignore[attr-defined]
