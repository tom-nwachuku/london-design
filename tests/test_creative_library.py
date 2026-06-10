from london.brain import LondonBrain
from london.creative_library import (
    assert_not_generic_library_output,
    list_library_entries,
    search_library,
)
from london.library import normalize_extractions, write_brain_sqlite


def test_creative_library_has_london_terms_and_anti_patterns():
    entries = list_library_entries()
    terms = {entry.term for entry in entries}
    kinds = {entry.kind for entry in entries}

    assert "Aesthetic void" in terms
    assert "Fonts In Use first" in terms
    assert "Safe-card grid" in terms
    assert "anti-pattern" in kinds


def test_search_library_returns_specific_terms_not_generic_filler():
    rows = search_library("typography proof fonts")

    assert rows[0]["term"] == "Fonts In Use first"
    assert "DaFont" in rows[0]["avoid"]
    assert_not_generic_library_output(rows)


def test_search_library_can_attach_brain_evidence(tmp_path):
    db_path = tmp_path / "brain.sqlite"
    write_brain_sqlite(
        normalize_extractions(
            [
                {
                    "core_lesson": "Fonts In Use helps prove typography in real product systems.",
                    "tools_and_platforms": [
                        {
                            "name": "Fonts In Use",
                            "use_case": "Study applied typography before selecting a typeface.",
                        }
                    ],
                    "topics": ["typography"],
                    "_source_video": "type.mp4",
                }
            ]
        ),
        db_path,
    )

    rows = search_library("typography", brain=LondonBrain(db_path), limit=4)

    evidence_rows = [row for row in rows if row.get("source_ref")]
    assert evidence_rows
    assert all(str(row["source_ref"]).startswith("source-") for row in evidence_rows)
    assert all(".mp4" not in str(row["source_ref"]) for row in evidence_rows)
    assert_not_generic_library_output(rows)
