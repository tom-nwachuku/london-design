from __future__ import annotations

import json

from london.brain import LondonBrain, build_brain_from_extractions
from london.library import build_chroma_from_sqlite, format_query_hits, query_chroma_index, write_brain_sqlite, normalize_extractions
from london.library import BrainEntry, query_entries


def test_brain_inventory_and_query_return_london_specific_findings(tmp_path):
    db_path = tmp_path / "brain.sqlite"
    write_brain_sqlite(normalize_extractions(_extractions()), db_path)

    brain = LondonBrain(db_path)
    inventory = brain.inventory()
    hits = brain.query("typography for a joyful retro-futurist product", limit=6)
    rendered = format_query_hits(hits)
    rendered_lower = rendered.lower()

    assert inventory.categories["tools"] >= 2
    assert inventory.categories["visual_examples"] >= 2
    assert inventory.categories["critique_approaches"] >= 1
    assert "Fonts In Use" in rendered
    assert "transparent casings" in rendered or "clear shell" in rendered
    assert "modern clean" not in rendered_lower
    assert "sleek minimalist" not in rendered_lower
    assert all(hit.entry.source_ref.startswith("source-") for hit in hits)
    assert ".mp4" not in rendered


def test_brain_can_be_built_from_archive_extractions(tmp_path):
    input_dir = tmp_path / "extractions"
    input_dir.mkdir()
    for index, record in enumerate(_extractions(), start=1):
        (input_dir / f"{index}.json").write_text(json.dumps(record), encoding="utf-8")
    db_path = tmp_path / "brain.sqlite"

    inventory = build_brain_from_extractions(input_dir, db_path)
    brain = LondonBrain(db_path)
    hits = brain.query("avoid generic moodboard typography", categories=["critique_approaches"])

    assert inventory.total_entries > 12
    assert hits
    assert any("DaFont" in hit.entry.body or "generic" in hit.entry.body for hit in hits)
    assert brain.derived_index_status()["chroma"] == "build_required"


def test_chroma_derived_index_builds_and_queries_from_sqlite(tmp_path):
    db_path = tmp_path / "brain.sqlite"
    index_path = tmp_path / "chroma"
    write_brain_sqlite(normalize_extractions(_extractions()), db_path)

    status = build_chroma_from_sqlite(db_path, index_path)
    hits = query_chroma_index("typography for joyful retro futurist products", index_path=index_path, db_path=db_path, limit=4)

    assert status["count"] > 0
    assert status["source"] == "sqlite:brain.sqlite"
    assert index_path.exists()
    assert hits
    assert all(hit.entry.source_ref.startswith("source-") for hit in hits)
    assert all(".mp4" not in hit.entry.source_ref for hit in hits)


def test_chroma_query_skips_entries_not_present_in_sqlite(tmp_path):
    db_path = tmp_path / "brain.sqlite"
    foreign_db_path = tmp_path / "foreign.sqlite"
    index_path = tmp_path / "chroma"
    write_brain_sqlite(normalize_extractions(_extractions()), db_path)
    write_brain_sqlite([], foreign_db_path)
    build_chroma_from_sqlite(db_path, index_path)

    hits = query_chroma_index("typography for joyful retro futurist products", index_path=index_path, db_path=foreign_db_path)

    assert hits == []


def test_query_entries_searches_custom_categories_when_unspecified_and_clamps_negative_limit():
    entries = [
        BrainEntry(
            id="custom",
            category="private_custom",
            title="Joyful custom source",
            body="Typography and joyful product ritual.",
            source_ref="source-custom",
            source_description="custom",
        ),
        BrainEntry(
            id="lesson",
            category="lessons",
            title="Less relevant",
            body="joyful",
            source_ref="source-lesson",
            source_description="lesson",
        ),
    ]

    hits = query_entries(entries, "typography joyful", limit=-5)

    assert [hit.entry.id for hit in hits] == ["custom"]


def test_london_brain_queries_share_one_entry_read_per_instance(monkeypatch, tmp_path):
    db_path = tmp_path / "brain.sqlite"
    write_brain_sqlite(normalize_extractions(_extractions()), db_path)
    import london.brain as brain_module

    original = brain_module.read_brain_entries
    calls = []

    def counted_read(path):
        calls.append(path)
        return original(path)

    monkeypatch.setattr(brain_module, "read_brain_entries", counted_read)

    brain = LondonBrain(db_path)
    assert brain.query("typography", categories=["tools"])
    assert brain.query("generic brand noise", categories=["critique_approaches"])

    assert calls == [db_path]


def _extractions():
    return [
        {
            "core_lesson": (
                "Stop making dreadfully boring tech. Build joyful retro-futurist products "
                "with transparent casings, visible internals, and a point of view."
            ),
            "tools_and_platforms": [
                {
                    "name": "Fonts In Use",
                    "url": "https://fontsinuse.com/",
                    "use_case": "Study real typography in packaging, campaigns, and product systems.",
                },
                {
                    "name": "Fontshare",
                    "url": "https://www.fontshare.com/",
                    "use_case": "Use curated type families and pairing examples before choosing fonts.",
                },
            ],
            "resources_and_references": [
                {
                    "name": "Karim Rashid",
                    "why_referenced": (
                        "Refuses to let mass-produced objects be dull; uses liquid curves and neon colorways."
                    ),
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
            "workflow_steps": [
                "Start with mature technology.",
                "Iterate through physical samples before polishing the launch story.",
            ],
            "visual_examples_on_screen": [
                "A clear orange speaker with exposed components beside a Swiss-grid instruction card."
            ],
            "strategic_frameworks": ["Steal principles from iconic brands, not their logos."],
            "actionable_directives": ["Use Fontshare pairs and Fonts In Use before choosing a typeface."],
            "topics": ["typography", "product-design"],
            "_source_video": "joyful-tech.mp4",
            "_source_description": "London explains how Kickback avoids boring modern electronics.",
        },
        {
            "core_lesson": (
                "Do not let the brand collapse into mid branding. DaFont, Canva templates, "
                "Pinterest sameness, and Shutterstock imagery create mood board noise."
            ),
            "tools_and_platforms": [
                {
                    "name": "Are.na",
                    "url": "https://www.are.na/",
                    "use_case": "Curate references deliberately instead of accepting algorithmic feeds.",
                }
            ],
            "resources_and_references": [
                {
                    "name": "Death to Stock",
                    "why_referenced": "Art-directed image sets that avoid bland stock-photo defaults.",
                }
            ],
            "design_principles": [
                "A loved-and-hated brand is stronger than a merely liked one.",
                "Generic modern packaging is not a strategy.",
            ],
            "product_concept": {"exists": False},
            "workflow_steps": ["Name the aesthetic enemy before making the moodboard."],
            "visual_examples_on_screen": [
                "A comparison between a bland stock laptop image and an art-directed product still."
            ],
            "strategic_frameworks": ["Anti-positioning starts by defining what the brand refuses to be."],
            "actionable_directives": ["Stop downloading professional brand fonts from DaFont."],
            "topics": ["critique", "photography"],
            "_source_video": "anti-mid.mp4",
            "_source_description": "London critiques generic startup taste and lazy visual sourcing.",
        },
    ]
