from __future__ import annotations

import json

from london.library import (
    REQUIRED_CATEGORIES,
    build_sqlite_from_extractions,
    load_extraction_records,
    normalize_extractions,
    read_brain_entries,
)


def test_normalize_extractions_preserves_required_categories():
    entries = normalize_extractions([_rich_extraction()])
    counts = {category: 0 for category in REQUIRED_CATEGORIES}
    for entry in entries:
        counts[entry.category] += 1

    assert counts["principles"] >= 2
    assert counts["resources"] == 1
    assert counts["visual_examples"] == 1
    assert counts["critique_approaches"] >= 1
    assert counts["product_concepts"] == 1
    assert counts["tools"] == 1
    assert counts["workflow_steps"] >= 2
    assert counts["lessons"] == 1
    assert counts["topics"] == 2
    assert all(entry.source_ref.startswith("source-") for entry in entries)
    assert all(".mp4" not in entry.source_ref for entry in entries)


def test_build_sqlite_from_extractions_reads_archive_json_without_raw_blob(tmp_path):
    input_dir = tmp_path / "extractions"
    input_dir.mkdir()
    (input_dir / "demo.json").write_text(json.dumps(_rich_extraction()), encoding="utf-8")
    db_path = tmp_path / "london_brain.sqlite"

    loaded = load_extraction_records(input_dir)
    inventory = build_sqlite_from_extractions(input_dir, db_path)
    entries = read_brain_entries(db_path)

    assert loaded[0]["_source_video"] == "london-demo.mp4"
    assert inventory.total_entries == len(entries)
    assert inventory.categories["tools"] == 1
    assert db_path.exists()
    assert all("_source_video" not in (entry.metadata or {}) for entry in entries)
    assert all(".mp4" not in entry.as_dict()["source_ref"] for entry in entries)


def _rich_extraction():
    return {
        "core_lesson": (
            "Stop making dreadfully boring tech. Build joyful retro-futurist products "
            "with transparent casings, visible internals, and a point of view."
        ),
        "tools_and_platforms": [
            {
                "name": "Fonts In Use",
                "url": "https://fontsinuse.com/",
                "use_case": "Study real typography in packaging, campaigns, and product systems.",
            }
        ],
        "resources_and_references": [
            {
                "name": "Karim Rashid",
                "why_referenced": "Proof that mass-produced objects can be colorful, liquid, and futuristic.",
            }
        ],
        "design_principles": [
            "Transparent acrylic, bright internals, and Y2K forms can make hardware feel impossible to ignore.",
            "Avoid generic stock photography and mood board noise when the brand needs a point of view.",
        ],
        "product_concept": {
            "exists": True,
            "name": "Kickback Pocket Speaker",
            "category": "Audio hardware",
            "design_direction": "Clear shell, orange driver, and postable packaging.",
            "launch_strategy": "Lead with design culture before technical specifications.",
            "target_market": "Taste-led buyers who want fun consumer electronics.",
        },
        "workflow_steps": ["Start with mature technology.", "Iterate through physical samples."],
        "visual_examples_on_screen": [
            "A clear orange speaker with exposed components beside a Swiss-grid instruction card."
        ],
        "strategic_frameworks": ["Steal principles from iconic brands, not their logos."],
        "actionable_directives": ["Use Fontshare pairs and Fonts In Use before choosing a typeface."],
        "topics": ["typography", "product-design"],
        "_source_video": "london-demo.mp4",
        "_source_description": "London explains how Kickback avoids boring modern electronics.",
    }
