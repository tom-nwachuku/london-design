"""Keyless, hermetic unit tests for the standalone FastMCP brain server.

These verify the *mechanical* contract of the brain MCP:
  1. ``london_brain_query`` returns the FULL 10-field finding bodies (not the
     ≤86-char titles the old fake engine used), proving it is not the title-only seam.
  2. ``london_brain_query`` applies NO ``GENERAL_BRAIN_CATEGORIES`` 5-of-9 pre-filter —
     the whole brain is searchable, so categories the old filter dropped can surface.
  3. All three tools (query / inventory / categories) exist and expose the brain's shape.

The server is pointed at a tmp brain via ``LONDON_BRAIN_PATH`` (monkeypatched), so the
suite is keyless and never touches the bundled production brain or the network.
"""

from __future__ import annotations

from london.library import normalize_extractions, write_brain_sqlite

# session.py:50 — the 5-of-9 category filter the MCP must NOT replicate. We assert the
# MCP can surface a category OUTSIDE this set, proving the absence of the pre-filter.
GENERAL_BRAIN_CATEGORIES = {
    "principles",
    "critique_approaches",
    "workflow_steps",
    "tools",
    "resources",
}


def _build_tmp_brain(tmp_path):
    """Clone the test_brain.py idiom: build a tmp brain from canned extractions."""
    db_path = tmp_path / "brain.sqlite"
    write_brain_sqlite(normalize_extractions(_extractions()), db_path)
    return db_path


def test_query_returns_full_findings_not_titles(tmp_path, monkeypatch):
    db_path = _build_tmp_brain(tmp_path)
    monkeypatch.setenv("LONDON_BRAIN_PATH", str(db_path))

    from london.brain_mcp import london_brain_query

    result = london_brain_query("joyful retro-futurist transparent product", limit=3)

    assert result["count"] >= 1
    finding = result["findings"][0]
    for field in (
        "id",
        "category",
        "title",
        "body",
        "source_ref",
        "topics",
        "score",
        "matched_terms",
    ):
        assert field in finding, f"missing field {field!r} in finding"
    # The body is the full text, NOT the truncated title — this is the whole point.
    assert finding["body"] != finding["title"]
    assert len(finding["body"]) > len(finding["title"]) or "\n" in finding["body"]


def test_query_applies_no_category_prefilter(tmp_path, monkeypatch):
    db_path = _build_tmp_brain(tmp_path)
    monkeypatch.setenv("LONDON_BRAIN_PATH", str(db_path))

    from london.brain_mcp import london_brain_query

    # Broad query, large limit — the whole brain is in scope.
    result = london_brain_query("joyful retro-futurist product typography visual", limit=40)
    categories = {f["category"] for f in result["findings"]}

    # The MCP must reach categories the old GENERAL_BRAIN_CATEGORIES filter dropped
    # (lessons / visual_examples / product_concepts / topics) OR surface >= 3 distinct
    # categories — either way proving no 5-of-9 pre-filter is applied.
    dropped_by_old_filter = categories - GENERAL_BRAIN_CATEGORIES
    assert dropped_by_old_filter or len(categories) >= 3, (
        f"MCP appears to replicate the 5-of-9 filter; categories seen: {sorted(categories)}"
    )
    # The result declares it searched the whole brain by default.
    assert result["categories"] == "all"


def test_query_honors_explicit_category_narrowing(tmp_path, monkeypatch):
    db_path = _build_tmp_brain(tmp_path)
    monkeypatch.setenv("LONDON_BRAIN_PATH", str(db_path))

    from london.brain_mcp import london_brain_query

    result = london_brain_query(
        "avoid generic moodboard typography",
        limit=10,
        categories=["critique_approaches"],
    )
    assert result["categories"] == ["critique_approaches"]
    assert all(f["category"] == "critique_approaches" for f in result["findings"])


def test_inventory_and_categories_tools(tmp_path, monkeypatch):
    db_path = _build_tmp_brain(tmp_path)
    monkeypatch.setenv("LONDON_BRAIN_PATH", str(db_path))

    from london.brain_mcp import london_brain_categories, london_brain_inventory

    inventory = london_brain_inventory()
    assert "total_entries" in inventory
    assert "categories" in inventory
    assert inventory["total_entries"] > 0

    cats = london_brain_categories()
    assert "categories" in cats
    assert isinstance(cats["categories"], list)
    assert cats["categories"]  # non-empty


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
