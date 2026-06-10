import base64
import json

from london.render import render_dossier
from london.session import run_london_session
from london.image_generation import (
    ImageGenerationRequest,
    _unavailable_result,
    _live_result,
)
from london.workbench import _is_live_artifact_receipt, _receipt_summary, enrich_workbench_pack
from london.workbench_audit import audit_html, default_public_copy, write_audit_packet


def _minimal_request(provider: str = "gemini") -> ImageGenerationRequest:
    """A minimal ImageGenerationRequest for testing receipt construction."""
    return ImageGenerationRequest(
        pack={"brief": {"title": "Test", "text": "Test brief."}, "routes": []},
        route={"title": "Route Alpha", "palette": []},
        route_index=0,
        requested_provider=provider,
        resolved_provider=provider,
    )


def test_live_result_receipt_classifies_as_live_artifact():
    """W2-P3: receipts built by _live_result() must be classified live by
    _is_live_artifact_receipt() — both on the raw receipt AND on the
    _receipt_summary() (which now preserves status and generation_mode).

    Pre-fix: _receipt() did not write generation_mode, so _receipt_summary()
    stripped it, and _is_live_artifact_receipt always returned False.
    """
    # Build a receipt via the real _live_result constructor (no network call).
    dummy_image_data = {"data": base64.b64encode(b"fake-png").decode(), "mime_type": "image/png"}
    result = _live_result(
        _minimal_request("gemini"),
        "A futuristic lunchbox prompt",
        provider="gemini",
        model="gemini-3-flash",
        image_data=dummy_image_data,
    )

    raw_receipt = result.receipt
    summary = _receipt_summary(raw_receipt)

    # Raw receipt must be live.
    assert _is_live_artifact_receipt(raw_receipt), (
        "raw receipt from _live_result() must classify as a live artifact"
    )
    # Summary (the form stored in the pack's receipts list) must also be live.
    assert _is_live_artifact_receipt(summary), (
        "_receipt_summary() must preserve status+generation_mode so the live-artifact check works"
    )

    # external-cmd is a real live lane — it must also classify as live.
    ext_result = _live_result(
        _minimal_request("external-cmd"),
        "An external command prompt",
        provider="external-cmd",
        model="local-model",
        image_data=dummy_image_data,
    )
    assert _is_live_artifact_receipt(ext_result.receipt), (
        "external-cmd receipts must classify as live artifacts"
    )
    assert _is_live_artifact_receipt(_receipt_summary(ext_result.receipt)), (
        "external-cmd receipt summary must classify as live artifact"
    )


def test_unavailable_result_receipt_is_not_live_artifact():
    """W2-P3: _unavailable_result() must produce a receipt that is NOT classified live,
    and both asset and receipt must have provider='none'."""
    result = _unavailable_result(
        _minimal_request("none"),
        "Image generation disabled prompt",
        status="images_disabled",
    )

    raw_receipt = result.receipt
    summary = _receipt_summary(raw_receipt)

    assert not _is_live_artifact_receipt(raw_receipt), (
        "unavailable receipt must NOT classify as live artifact"
    )
    assert not _is_live_artifact_receipt(summary), (
        "unavailable receipt summary must NOT classify as live artifact"
    )
    # Both asset and receipt must have provider="none" (W2-P3 part c).
    assert result.asset.get("provider") == "none", (
        "_unavailable_result must set asset provider to 'none'"
    )
    assert raw_receipt.get("provider") == "none", (
        "_unavailable_result must set receipt provider to 'none'"
    )


def test_live_receipt_classification_requires_generation_mode():
    """W2-P3: the test must FAIL if generation_mode is removed from the receipt.

    When generation_mode is absent, _is_live_artifact_receipt returns False
    even when status='generated_live' and provider is in the live set.
    """
    # A receipt WITHOUT generation_mode must not classify as live.
    no_mode_receipt = {"provider": "gemini", "status": "generated_live"}
    assert not _is_live_artifact_receipt(no_mode_receipt), (
        "a receipt missing generation_mode must not classify as live (guards against regression)"
    )


def test_audit_catches_visible_harness_terms_and_dashes():
    html = """
    <main>
      <section id="start">
        <h2>RUN DETAILS</h2>
        <p>scripted-local — Telemetry not captured, n/a.</p>
        <p>This pack separates London Brain Findings, Source Targets, and Live Artifacts.</p>
        <p>Source targets are planned unless a live evidence note proves fetched or generated work.</p>
      </section>
    </main>
    """

    audit = audit_html(html)
    tokens = {hit.token for hit in audit.public_hits}

    assert audit.failed
    assert "scripted-local" in tokens
    assert "Telemetry not captured" in tokens
    assert "—" in tokens
    assert "RUN DETAILS" in tokens
    assert r"\bn/a\b" in tokens
    assert r"\bLive Artifacts\b" in tokens
    assert r"\blive evidence note\b" in tokens
    assert r"\bgenerated work\b" in tokens


def test_audit_catches_public_grader_report_card_terms():
    html = """
    <main>
      <section id="grader">
        <p>TELEMETRY_UNAVAILABLE</p>
        <p>CLAIM_OK</p>
        <p>BRAIN QUERIES // TRACE</p>
        <p>OUTPUT MANIFEST</p>
        <p>CLAIM INTEGRITY // AUDIT</p>
        <p>weighted from 5 objective checks</p>
        <p>Not scored</p>
        <p>sub-score not available</p>
        <p>no quality score available</p>
        <p>No transcript for this engine mode: grounding unavailable.</p>
        <p>No transcript for this mode: grounding unavailable.</p>
        <p>No source trail for this mode: grounding unavailable.</p>
        <p>Font choices show enough range; local assets are proof, not the whole taste pool.</p>
        <p>Font Lab range: local fonts allowed, but not allowed to dominate taste.</p>
        <p>Every required region is filled at honest cardinality.</p>
        <p>Every required region filled at honest cardinality, no padded slots.</p>
      </section>
    </main>
    """

    audit = audit_html(html)
    tokens = {hit.token for hit in audit.public_hits}

    assert audit.failed
    assert "TELEMETRY_UNAVAILABLE" in tokens
    assert "CLAIM_OK" in tokens
    assert "BRAIN QUERIES // TRACE" in tokens
    assert "OUTPUT MANIFEST" in tokens
    assert "CLAIM INTEGRITY // AUDIT" in tokens
    assert "weighted from 5 objective checks" in tokens
    assert "Not scored" in tokens
    assert r"\bsub-score\b" in tokens
    assert r"\bquality score\b" in tokens
    assert "No transcript for this engine mode" in tokens
    assert "No transcript for this mode" in tokens
    assert "No source trail for this mode" in tokens
    assert r"\blocal assets are proof\b" in tokens
    assert r"\bFont Lab range\s*(?::|—|–|-)\s*local fonts allowed\b" in tokens
    assert r"\bEvery required region is filled at honest cardinality\b" in tokens
    assert r"\bEvery required region filled at honest cardinality\b" in tokens


def test_audit_catches_interactive_and_accessibility_copy():
    html = """
    <main>
      <img alt="provider-generated concept image receipt asset_sha256">
      <button aria-label="Open debug receipts" title="debug source ref"
        data-copy="manual_prompt provider-backed artifact receipt">Copy</button>
    </main>
    """

    audit = audit_html(html)
    sources = {hit.surface.source for hit in audit.public_hits}

    assert audit.failed
    assert "attr:alt" in sources
    assert "attr:aria-label" in sources
    assert "attr:title" in sources
    assert "attr:data-copy" in sources


def test_audit_allows_raw_facts_inside_intentional_audit_body_only():
    html = """
    <main>
      <details class="drawer is-receipt-detail" data-persist="run-records">
        <summary>Source trail</summary>
        <p>provider receipt asset_sha256 generated_live scripted-local n/a</p>
      </details>
    </main>
    """

    audit = audit_html(html)
    public_copy = default_public_copy(html).lower()
    audit_body = " ".join(surface.text for surface in audit.surfaces if surface.zone == "audit_body")

    assert not audit.failed
    assert "source trail" in public_copy
    assert "provider" not in public_copy
    assert "asset_sha256" in audit_body
    assert "scripted-local" in audit_body


def test_audit_fails_untranslated_folded_summary_even_when_body_is_audit():
    html = """
    <main>
      <details class="drawer is-receipt-detail">
        <summary>Receipts / Debug</summary>
        <p>provider receipt asset_sha256</p>
      </details>
    </main>
    """

    audit = audit_html(html)
    summary_hits = [hit for hit in audit.public_hits if hit.surface.zone == "public_folded_summary"]

    assert audit.failed
    assert summary_hits


def test_decision_source_trail_body_is_intentional_audit_surface():
    html = """
    <main>
      <details class="decision-fold" data-persist="decision-1">
        <summary>Decision source trail</summary>
        <p>brain query about route receipts and provider records</p>
      </details>
    </main>
    """

    audit = audit_html(html)

    assert not audit.failed
    assert {surface.zone for surface in audit.surfaces} == {"public_folded_summary", "audit_body"}


def test_audit_catches_large_public_prose_blocks():
    long_text = " ".join(["This public paragraph keeps going without a visual treatment"] * 12)
    audit = audit_html(f"<main><p>{long_text}</p></main>")

    assert audit.failed
    assert audit.public_long_prose
    assert audit.public_long_prose[0].words > 85


def test_audit_catches_missing_public_local_media(tmp_path):
    html_path = tmp_path / "index.html"
    html_path.write_text('<main><img src="assets/missing.jpg" alt="Route product view"></main>', encoding="utf-8")

    audit = audit_html(html_path.read_text(encoding="utf-8"), html_path=html_path)

    assert audit.failed
    assert audit.public_media_hits
    assert audit.public_media_hits[0].src == "assets/missing.jpg"
    assert "missing local media" in audit.public_media_hits[0].reason


def test_audit_allows_existing_public_local_media(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "route.jpg").write_bytes(b"not a real image but present for path validation")
    html_path = tmp_path / "index.html"
    html_path.write_text('<main><img src="assets/route.jpg" alt="Route product view"></main>', encoding="utf-8")

    audit = audit_html(html_path.read_text(encoding="utf-8"), html_path=html_path)

    assert audit.public_media_hits == []
    assert not audit.failed


def test_audit_packet_writer_outputs_required_files(tmp_path):
    html = "<main><p>Clean public copy.</p></main>"
    audit = audit_html(html)

    write_audit_packet(audit, tmp_path, html_path=tmp_path / "index.html")

    expected = {
        "rendered-text-inventory.json",
        "rendered-text-inventory.md",
        "humanize-scan.json",
        "long-prose-audit.md",
        "media-audit.md",
        "rubric-failure-log.md",
    }
    assert expected.issubset({path.name for path in tmp_path.iterdir()})
    scan = json.loads((tmp_path / "humanize-scan.json").read_text(encoding="utf-8"))
    assert scan["failed"] is False


def test_rendered_workbench_passes_reusable_public_text_gate():
    pack = run_london_session(
        "# Kids Lunchbox\n\nCreate a lunchbox system with parent setup, kid choice, and a daily reveal ritual."
    )
    enrich_workbench_pack(pack)

    audit = audit_html(render_dossier(pack))

    assert audit.public_hits == []
    assert audit.public_long_prose == []
