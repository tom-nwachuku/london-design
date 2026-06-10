import hashlib
import json
from pathlib import Path

from london.cli import main
from london.gallery import collect_gallery_items, render_gallery_detail, render_gallery_index, write_gallery
from london.prototype import render_static_prototype


def _write_gallery_pack(
    tmp_path: Path,
    name: str,
    *,
    generated: bool = True,
    asset_src: str | None = None,
    include_receipt: bool = True,
    receipt_status: str | None = None,
    provider: str | None = None,
    receipt_asset_src: str | None = None,
    receipt_asset_sha256: str | None = None,
    write_asset: bool = True,
) -> Path:
    root = tmp_path / name
    assets = root / "assets"
    fonts = assets / "fonts"
    assets.mkdir(parents=True)
    fonts.mkdir()
    image_name = "signal-proof.svg" if generated else "direction-board.svg"
    image_label = "Generated proof image" if generated else "Internal direction board"
    if asset_src is None:
        asset_src = f"assets/{image_name}"
    if write_asset:
        target = Path(asset_src)
        target = target if target.is_absolute() else root / target
        target.parent.mkdir(parents=True, exist_ok=True)
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="760" viewBox="0 0 1200 760">
  <rect width="1200" height="760" fill="#f7f6f2"/>
  <rect x="120" y="96" width="960" height="568" rx="28" fill="#ffffff" stroke="#1d1d1b"/>
  <text x="160" y="180" font-family="Arial" font-size="54">{image_label}</text>
</svg>"""
        target.write_text(svg, encoding="utf-8")
    (fonts / "familjen-grotesk.woff2").write_bytes(b"font-placeholder")
    route_id = f"{name}-signal-kiosk"
    receipt_id = f"{route_id}-image-generation"
    asset_kind = "generated-concept-image" if generated else "visual-direction-board"
    receipt_status = receipt_status or ("generated_live" if generated else "images_disabled")
    provider = provider or ("gemini" if generated else "manual-prompt")
    pack = {
        "title": f"{name.title()} Pilot",
        "artifact_type": "Product prototype",
        "recommended_route_ref": "route_signal_kiosk",
        "routes": [
            {
                "id": route_id,
                "title": "Signal Kiosk",
                "headline": "A finished visual route, not a transcript dump.",
                "subhead": "Product copy leads the public gallery before status labels appear.",
                "rationale": "London anchors the route in a working object first, then lets the interface language follow the material logic.",
                "sections": [
                    {
                        "title": "Visual system",
                        "body": "The image should feel like a photographed working prototype with one clear action and quiet supporting marks.",
                    }
                ],
                "visual_read": "A calm product scene carries the idea; tiny status labels stay out of the public read.",
                "type": "Compact grotesk headlines make the kiosk feel operational, with tabular labels reserved for wayfinding.",
                "palette": [
                    {"role": "spark", "name": "Signal Orange", "hex": "#ff4f1f"},
                    {"role": "ink", "name": "Quiet Ink", "hex": "#1d1d1b"},
                ],
                "tags": ["product", "interface", "launch proof"],
                "assets": [
                    {
                        "kind": asset_kind,
                        "src": asset_src,
                        "provider": provider,
                        "receipt_id": receipt_id,
                    }
                ],
            }
        ],
        "font_options": [
            {
                "route_id": route_id,
                "options": [
                    {
                        "tier": "safe_local",
                        "name": "Familjen Grotesk",
                        "headline_font": "Familjen Grotesk",
                        "fallback_stack": "system-ui, sans-serif",
                        "sample_headline": "A finished visual route, not a transcript dump.",
                        "sample_body": "Product copy leads the public gallery before status labels appear.",
                        "best_use": "Public route cards and detail pages where the interface needs to feel exact without becoming cold.",
                        "why_london_chose_it": "Its blunt, friendly forms keep the kiosk legible while the orange accent carries urgency.",
                        "why_this_route_not_other_route": "Signal Kiosk needs operational clarity; softer routes would make the system feel decorative.",
                        "font_preview": {
                            "status": "actual_loaded",
                            "delivery": "local_asset",
                            "rendered_family": "Familjen Grotesk",
                            "source_label": "London Type Shelf",
                            "license_note": "Bundled open font for launch proof.",
                            "asset_href": "assets/fonts/familjen-grotesk.woff2",
                        },
                    }
                ],
            }
        ],
        "route_comparison": [
            {
                "route_id": route_id,
                "first_build_move": "Prototype the kiosk as a single photographed product moment before expanding the interface.",
                "best_for": "Best when London needs a public proof card that reads at a glance.",
                "steal": "Steal the hard edge between utility and warmth.",
                "do_not_copy": "Do not copy receipt panels into the image.",
                "risk": "If the card becomes too informational it starts reading like QA.",
            }
        ],
        "receipts": [],
    }
    if include_receipt:
        receipt_asset_src = receipt_asset_src or asset_src
        if receipt_asset_sha256 is None:
            receipt_target = Path(receipt_asset_src)
            receipt_target = receipt_target if receipt_target.is_absolute() else root / receipt_target
            receipt_asset_sha256 = (
                hashlib.sha256(receipt_target.read_bytes()).hexdigest()
                if receipt_target.exists() and receipt_target.is_file()
                else ""
            )
        pack["receipts"].append(
            {
                "kind": "image-generation",
                "receipt_id": receipt_id,
                "provider": provider,
                "model": "gemini-public-proof-model",
                "route_id": route_id,
                "status": receipt_status,
                "asset_src": receipt_asset_src,
                "asset_sha256": receipt_asset_sha256,
            }
        )
    (root / "london-pack.json").write_text(json.dumps(pack), encoding="utf-8")
    return root


def _public_grid(html: str) -> str:
    return html.split('<section class="gallery-grid"', 1)[1].split("</section>", 1)[0]


def _first_card(html: str) -> str:
    return html.split('<article class="gallery-card"', 1)[1].split("</article>", 1)[0]


def _diagnostics_drawer(html: str) -> str:
    return html.split('<details class="gallery-diagnostics"', 1)[1].split("</details>", 1)[0]


def test_gallery_index_uses_neutral_shell_and_image_first_cards(tmp_path):
    item = collect_gallery_items([_write_gallery_pack(tmp_path, "generated")])[0]

    html = render_gallery_index([item])
    card = _first_card(html)

    assert "--gallery-bg: #f7f6f2" in html
    assert "background: var(--gallery-bg)" in html
    assert "<header class=\"gallery-topbar\">" in html
    assert "placeholder=\"Search routes\"" not in html
    assert 'aria-label="Public gallery work"' in html
    assert "A finished visual route, not a transcript dump." in html
    assert "Product copy leads the public gallery before status labels appear." in html
    assert "Generated London work, framed quietly." not in html
    assert "The prototype remains the artifact" not in html
    assert "Generated proof" not in html
    assert "Public proof eligible" not in html
    assert "grid-template-columns: repeat(auto-fill, minmax(min(100%, 360px), 420px))" in html
    assert ".gallery-card-preview { margin: 0; aspect-ratio: 4 / 3;" in html
    assert ".gallery-card-preview img { width: 100%; height: 100%; object-fit: cover;" in html
    assert "html, body { max-width: 100%; overflow-x: hidden; }" in html
    assert ".gallery-search input, .gallery-sort select" not in html
    assert "overflow-wrap: anywhere" in html
    assert ".gallery-grid { grid-template-columns: 1fr; }" in html
    assert ".gallery-card { width: 100%; max-width: 100%; }" in html
    assert ".gallery-card-preview img { object-fit: contain; }" in html
    assert "font-size: clamp(1.75rem, 8.8vw, 2.1rem)" in html
    assert ".gallery-hero h1 { max-width: 11ch; }" in html
    assert ".gallery-hero p:not(.gallery-kicker) { max-width: 32ch; }" in html
    assert card.index('class="gallery-card-preview"') < card.index('class="gallery-card-caption"')
    assert '<img src="assets/signal-proof.svg"' in card
    assert "background: #ff4f1f" not in html


def test_generated_pack_enters_public_grid_and_fallback_pack_is_blocked(tmp_path):
    generated = _write_gallery_pack(tmp_path, "generated", generated=True)
    fallback = _write_gallery_pack(tmp_path, "fallback", generated=False)
    items = collect_gallery_items([generated, fallback])

    html = render_gallery_index(items)
    grid = _public_grid(html)

    assert "Signal Kiosk" in grid
    assert "A finished visual route, not a transcript dump." in grid
    assert "Fallback Pilot" not in grid
    assert grid.count('class="gallery-card"') == 1
    assert 'data-public-gallery="internal-diagnostics"' in html
    diagnostics = _diagnostics_drawer(html)
    assert "<summary>Internal gallery review notes</summary>" in diagnostics
    assert "Fallback Pilot" in diagnostics
    assert "fallback boards stay internal/offline" in diagnostics


def test_gallery_card_caption_excludes_receipt_provider_hash_and_model_text(tmp_path):
    item = collect_gallery_items([_write_gallery_pack(tmp_path, "generated")])[0]

    html = render_gallery_index([item])
    card = _first_card(html)

    assert "Signal Kiosk" in card
    assert "A finished visual route, not a transcript dump." in card
    assert "Product copy leads the public gallery before status labels appear." in card
    assert "Public proof eligible" not in card
    assert "Generated proof" not in card
    assert "generated_live" not in card
    assert "receipt" not in card.lower()
    assert "gemini" not in card.lower()
    assert "gemini-public-proof-model" not in card
    assert "receipt-sha256" not in card
    assert "abc123hash" not in card


def test_claude_image_provider_uses_shared_public_label_in_gallery_and_prototype(tmp_path):
    pack_dir = _write_gallery_pack(tmp_path, "claude", provider="claude-image")
    item = collect_gallery_items([pack_dir])[0]
    detail = render_gallery_detail(item)
    pack = json.loads((pack_dir / "london-pack.json").read_text(encoding="utf-8"))
    prototype = render_static_prototype(pack)

    assert item.provider == "Claude image"
    assert "Claude image" in detail
    assert "data-provider-label=\"Claude image\"" in prototype
    assert "claude-image" not in detail
    assert "data-provider-label=\"claude-image\"" not in prototype


def test_gallery_public_candidate_rejects_stale_0804_hero_names(tmp_path):
    fresh_packs = [
        _write_gallery_pack(tmp_path, "kids-rain-boot-line"),
        _write_gallery_pack(tmp_path, "horoscope-app"),
        _write_gallery_pack(tmp_path, "daily-motivation-notebook"),
    ]
    items = collect_gallery_items(fresh_packs)

    html = render_gallery_index(items)
    grid = _public_grid(html)

    for stale_name in (
        "Pressed Index",
        "Vellum Refill",
        "Accession",
        "The Calm Instrument",
        "Phases",
        "Bench Slip",
        "The Composing Table",
    ):
        assert stale_name not in grid


def test_gallery_surfaces_richer_london_route_copy_before_audit_details(tmp_path):
    item = collect_gallery_items([_write_gallery_pack(tmp_path, "generated")])[0]

    index = render_gallery_index([item])
    detail = render_gallery_detail(item)
    first_layer = detail.split('<details class="gallery-proof-detail">', 1)[0]

    assert "London anchors the route in a working object first" in index
    assert "A calm product scene carries the idea" in index
    assert "London anchors the route in a working object first" in first_layer
    assert "A calm product scene carries the idea" in first_layer
    assert "Compact grotesk headlines make the kiosk feel operational" in first_layer
    assert "Its blunt, friendly forms keep the kiosk legible" in first_layer
    assert "Public route cards and detail pages" in first_layer
    for proof_term in (
        "Generated proof",
        "Public proof eligible",
        "Actual font loaded",
        "generated_live",
        "provider",
        "receipt",
        "sha256",
        "launch-gate",
    ):
        assert proof_term.lower() not in first_layer.lower()


def test_gallery_does_not_invent_missing_route_rationale(tmp_path):
    pack = _write_gallery_pack(tmp_path, "missing-copy")
    payload = json.loads((pack / "london-pack.json").read_text(encoding="utf-8"))
    route = payload["routes"][0]
    for key in ("rationale", "thesis", "sections", "visual_read"):
        route.pop(key, None)
    payload.pop("route_comparison", None)
    payload["routes"][0]["assets"][0].pop("caption", None)
    payload["routes"][0]["assets"][0].pop("alt", None)
    (pack / "london-pack.json").write_text(json.dumps(payload), encoding="utf-8")
    item = collect_gallery_items([pack])[0]

    html = render_gallery_index([item]) + render_gallery_detail(item)

    assert item.route_rationale == ""
    assert item.visual_read == ""
    assert "why this route" not in html.lower()
    assert "route read" not in html.lower()
    assert "visual idea" not in html.lower()
    assert "London says" not in html


def test_gallery_detail_has_landbook_like_preview_toolbar_and_right_rail(tmp_path):
    item = collect_gallery_items([_write_gallery_pack(tmp_path, "generated")])[0]

    html = render_gallery_detail(item)

    assert '<nav class="gallery-toolbar"' in html
    assert "Preview" in html and "Pages" in html and "Routes" in html
    assert 'class="gallery-large-preview"' in html
    assert '<aside class="gallery-rail"' in html
    assert "Palette" in html and "Type direction" in html and "Source record" in html and "Tags" in html
    assert "--swatch:#ff4f1f" in html
    assert "Familjen Grotesk" in html
    assert "Compact grotesk headlines make the kiosk feel operational" in html
    assert "Its blunt, friendly forms keep the kiosk legible" in html
    assert "Public route cards and detail pages" in html
    assert "Open audit note" in html
    assert "Provider" not in html
    assert "generated_live" not in html
    first_read = html.split('<details class="gallery-proof-detail">', 1)[0]
    assert "Actual font loaded" not in first_read
    assert "generated_live" not in first_read
    assert "Gemini" not in first_read
    assert "Generated proof" not in first_read
    assert "A finished visual route, not a transcript dump." in html
    assert "Product copy leads the public gallery before status labels appear." in html
    assert "route_signal_kiosk" not in html


def test_gallery_cli_writes_only_eligible_detail_pages_and_copies_assets(tmp_path):
    generated = _write_gallery_pack(tmp_path, "generated", generated=True)
    fallback = _write_gallery_pack(tmp_path, "fallback", generated=False)
    out = tmp_path / "gallery"

    main(["gallery", "build", str(generated), str(fallback), "--out", str(out)])

    index = (out / "index.html").read_text(encoding="utf-8")
    details = sorted((out / "details").glob("*.html"))
    copied_assets = sorted((out / "assets").glob("*.svg"))
    assert len(details) == 1
    assert len(copied_assets) == 1
    assert copied_assets[0].name == "generated-pilot-signal-kiosk.svg"
    assert "assets/generated-pilot-signal-kiosk.svg" in index
    assert "Signal Kiosk" in _public_grid(index)
    assert "A finished visual route, not a transcript dump." in _public_grid(index)
    assert "Fallback Pilot" not in _public_grid(index)


def test_gallery_blocks_generated_label_with_disabled_receipt(tmp_path):
    item = collect_gallery_items(
        [_write_gallery_pack(tmp_path, "disabled", generated=True, receipt_status="images_disabled")]
    )[0]
    html = render_gallery_index([item])

    assert item.eligible is False
    assert "Disabled Pilot" not in _public_grid(html)
    assert "receipt status images_disabled" in _diagnostics_drawer(html)


def test_gallery_blocks_generated_label_without_receipt(tmp_path):
    item = collect_gallery_items([_write_gallery_pack(tmp_path, "missing", generated=True, include_receipt=False)])[0]
    html = render_gallery_index([item])

    assert item.eligible is False
    assert "Missing Pilot" not in _public_grid(html)
    assert "missing generated_live image receipt" in _diagnostics_drawer(html)


def test_gallery_blocks_manual_prompt_receipt_provider(tmp_path):
    item = collect_gallery_items(
        [_write_gallery_pack(tmp_path, "manual", generated=True, provider="manual-prompt")]
    )[0]
    html = render_gallery_index([item])

    assert item.eligible is False
    assert "Manual Pilot" not in _public_grid(html)
    assert "provider manual-prompt is not public proof" in _diagnostics_drawer(html)


def test_gallery_blocks_absolute_asset_path_outside_pack_and_does_not_copy(tmp_path):
    outside = tmp_path / "outside.svg"
    pack = _write_gallery_pack(tmp_path, "absolute", generated=True, asset_src=str(outside))
    out = tmp_path / "gallery"

    index_path = write_gallery([pack], out)

    html = index_path.read_text(encoding="utf-8")
    assert "Absolute Pilot" not in _public_grid(html)
    assert "unsafe asset path" in html
    assert not list((out / "assets").glob("*.svg"))


def test_gallery_blocks_parent_directory_asset_path(tmp_path):
    pack = _write_gallery_pack(tmp_path, "parent", generated=True, asset_src="../outside.svg")
    out = tmp_path / "gallery"

    index_path = write_gallery([pack], out)

    html = index_path.read_text(encoding="utf-8")
    assert "Parent Pilot" not in _public_grid(html)
    assert "unsafe asset path: ../outside.svg" in html
    assert not list((out / "assets").glob("*.svg"))


def test_gallery_valid_generated_live_receipt_and_assets_path_enters_grid(tmp_path):
    pack = _write_gallery_pack(tmp_path, "valid", generated=True, asset_src="assets/foo.svg")
    out = tmp_path / "gallery"

    index_path = write_gallery([pack], out)

    html = index_path.read_text(encoding="utf-8")
    assert "Signal Kiosk" in _public_grid(html)
    assert "A finished visual route, not a transcript dump." in _public_grid(html)
    copied_assets = sorted((out / "assets").glob("*.svg"))
    assert [path.name for path in copied_assets] == ["valid-pilot-signal-kiosk.svg"]


def test_gallery_blocks_stale_route_receipt_for_swapped_display_asset(tmp_path):
    pack = _write_gallery_pack(tmp_path, "stale", generated=True)
    fallback = pack / "assets" / "direction-board.svg"
    fallback.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="760">
  <text x="40" y="80">Fallback board swapped into generated route</text>
</svg>""",
        encoding="utf-8",
    )
    payload = json.loads((pack / "london-pack.json").read_text(encoding="utf-8"))
    payload["routes"][0]["assets"][0]["src"] = "assets/direction-board.svg"
    (pack / "london-pack.json").write_text(json.dumps(payload), encoding="utf-8")

    item = collect_gallery_items([pack])[0]
    html = render_gallery_index([item])

    assert item.eligible is False
    assert "Stale Pilot" not in _public_grid(html)
    assert "receipt asset_src does not match displayed asset" in html
