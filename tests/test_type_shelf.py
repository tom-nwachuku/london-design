import hashlib
import json
from importlib.resources import files

import pytest

from london.type_shelf import (
    TypeShelfError,
    enrich_font_reference_visuals,
    load_type_shelf,
    resolve_type_shelf_entry,
    type_shelf_entries,
    type_shelf_ring_counts,
)
from london.font_preview import FontshareAdapter, FontsourceAdapter, GoogleFontsAdapter, resolve_font_preview


def test_type_shelf_has_bundled_open_font_receipts():
    data = load_type_shelf()
    counts = type_shelf_ring_counts()

    assert data["schema_version"] == 1
    assert counts["bundled_open"] == 6
    assert counts["catalog_open"] >= 2
    assert counts["reference_premium"] >= 2

    for entry in type_shelf_entries(ring="bundled_open"):
        assert entry.family
        assert entry.source_url.startswith("https://")
        assert entry.license_name
        assert entry.license_url.startswith("https://")
        assert entry.license_checked_at == "2026-06-05"
        assert entry.asset_path.endswith(".woff2")
        assert entry.asset_sha256
        font_bytes = files("london.data").joinpath(entry.asset_path).read_bytes()
        assert hashlib.sha256(font_bytes).hexdigest() == entry.asset_sha256


def test_type_shelf_resolves_by_family_or_id():
    by_family = resolve_type_shelf_entry("Familjen Grotesk", bundled_only=True)
    by_id = resolve_type_shelf_entry("familjen-grotesk", bundled_only=True)

    assert by_family == by_id
    assert by_family.ring == "bundled_open"


def test_type_shelf_keeps_fontshare_taste_as_reference_visual_when_not_bundled():
    entry = resolve_type_shelf_entry("Clash Display")

    assert entry.ring == "reference_premium"
    assert entry.reference_only is True
    assert entry.reference_preview
    assert entry.reference_preview["kind"] == "official_preview_url"
    assert entry.reference_preview["url"].startswith("https://fontshare.com/fonts/")


def test_type_shelf_rejects_reference_font_as_bundled():
    with pytest.raises(TypeShelfError):
        resolve_type_shelf_entry("GT America", bundled_only=True)


def test_type_shelf_enriches_premium_options_as_reference_visual_not_loaded():
    pack = {
        "font_options": [
            {
                "route_id": "route-a",
                "route_title": "Route A",
                "options": [
                    {
                        "tier": "premium_inspiration",
                        "name": "GT America Cards + Tiempos Text",
                        "headline_font": "GT America",
                        "body_font": "Tiempos Text",
                        "label_font": "GT America Mono",
                        "fallback_stack": "'GT America', Arial, sans-serif",
                        "import_hint": "Reference GT America; license from Grilli Type.",
                    }
                ],
            }
        ]
    }

    enrich_font_reference_visuals(pack)
    preview = pack["font_options"][0]["options"][0]["font_preview"]

    assert preview["status"] == "reference_only"
    assert preview["delivery"] == "reference_only"
    assert preview["rendered_family"] == "GT America"
    assert preview["reference_visual"] is True
    assert preview["reference_preview"]["source_label"] == "Grilli Type public specimen"
    assert "font not loaded" in preview["license_note"]


def test_type_shelf_reference_visual_does_not_follow_mismatched_fallback_stack():
    pack = {
        "font_options": [
            {
                "route_id": "route-a",
                "route_title": "Route A",
                "options": [
                    {
                        "tier": "premium_inspiration",
                        "name": "PP Neue Machina + Dala Floda",
                        "headline_font": "PP Neue Machina",
                        "body_font": "Dala Floda",
                        "label_font": "PP Neue Machina Inktrap",
                        "fallback_stack": "'Cabinet Grotesk', Arial, sans-serif",
                        "import_hint": "Use Cabinet Grotesk only as a generic fallback while sourcing the named family.",
                    }
                ],
            }
        ]
    }

    enrich_font_reference_visuals(pack)
    option = pack["font_options"][0]["options"][0]

    assert "font_preview" not in option


def test_type_shelf_json_does_not_store_local_paths():
    blob = json.dumps(load_type_shelf())

    assert "/Users/" not in blob
    assert "/private/" not in blob
    assert "/tmp/" not in blob


def test_fontsource_resolver_marks_common_open_families_source_loadable():
    for family in ("Space Grotesk", "Geist Mono"):
        match = FontsourceAdapter.resolve(family)

        assert match is not None
        assert match.font_file_href.startswith("https://cdn.jsdelivr.net/fontsource/fonts/")
        assert match.font_file_href.endswith(".woff2")
        assert match.license_note


def test_google_fonts_resolver_records_no_key_css2_source_url():
    match = GoogleFontsAdapter.resolve("Space Grotesk")

    assert match is not None
    assert "fonts.googleapis.com/css2" in match.font_file_href
    assert "Google Fonts CSS2" in match.source_label


def test_fontshare_resolver_records_known_public_css_endpoint():
    for family in ("Satoshi", "Clash Display", "Switzer", "Cabinet Grotesk", "General Sans", "Bespoke Slab"):
        match = FontshareAdapter.resolve(family)

        assert match is not None
        assert match.font_file_href.startswith("https://api.fontshare.com/v2/css")
        assert match.source_url.startswith("https://fontshare.com/fonts/")


def test_open_public_font_option_resolves_to_source_loaded_state():
    option = {
        "tier": "open_public",
        "name": "Space Grotesk + Geist Mono",
        "headline_font": "Space Grotesk",
        "body_font": "Inter",
        "label_font": "Geist Mono",
        "fallback_stack": "'Space Grotesk', Arial, sans-serif",
    }

    preview = resolve_font_preview(option)

    assert preview.status == "source_loaded"
    assert preview.delivery == "remote_font_file"
    assert preview.display_state == "source_loaded"
    assert preview.role_css_stacks
    assert preview.role_css_stacks["headline"].startswith('"Space Grotesk"')
    assert all(href.startswith("https://cdn.jsdelivr.net/fontsource/fonts/") for href in preview.css_hrefs)
