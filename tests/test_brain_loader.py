"""BRAIN-01 — swappable, versioned brain loader (resolve / validate / version).

Keyless, deterministic unit tests of the mechanical plumbing: where the brain
resolves from (LONDON_BRAIN_PATH override vs bundled default), whether a brain is
valid (loud-fail on empty / unreadable), and reading the brain_version from meta.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from london import brain_loader
from london.library import (
    DEFAULT_BRAIN_DB,
    inventory_from_sqlite,
    normalize_extractions,
    write_brain_sqlite,
)


def _make_brain(
    tmp_path: Path,
    *,
    with_entries: bool = True,
    brain_version: str | None = "2026.06.03",
    name: str = "b.sqlite",
) -> Path:
    """Build a tmp sqlite mirroring library.write_brain_sqlite's schema.

    meta(key TEXT PRIMARY KEY, value TEXT NOT NULL) plus the full entries table
    layout (id, category, title, body, source_ref, source_description,
    topics_json, metadata_json, search_text).
    """
    db = tmp_path / name
    con = sqlite3.connect(db)
    try:
        con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        con.execute("INSERT INTO meta(key, value) VALUES('schema_version', '1')")
        if brain_version:
            con.execute(
                "INSERT INTO meta(key, value) VALUES('brain_version', ?)",
                (brain_version,),
            )
        con.execute(
            """
            CREATE TABLE entries(
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                source_ref TEXT NOT NULL,
                source_description TEXT NOT NULL,
                topics_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                search_text TEXT NOT NULL
            )
            """
        )
        if with_entries:
            con.execute(
                "INSERT INTO entries VALUES('e1','lessons','t','b','source-1','sd','[]','{}','st')"
            )
        con.commit()
    finally:
        con.close()
    return db


def test_resolve_uses_env_override(tmp_path, monkeypatch):
    db = _make_brain(tmp_path)
    monkeypatch.setenv("LONDON_BRAIN_PATH", str(db))
    assert brain_loader.resolve_brain_path() == db


def test_resolve_defaults_to_bundled(monkeypatch):
    monkeypatch.delenv("LONDON_BRAIN_PATH", raising=False)
    assert brain_loader.resolve_brain_path() == Path(DEFAULT_BRAIN_DB)


def test_validate_rejects_empty_brain(tmp_path):
    db = _make_brain(tmp_path, with_entries=False)
    report = brain_loader.validate_brain(db)
    assert report.ok is False
    assert "no entries" in report.reason.lower()


def test_validate_rejects_unreadable(tmp_path):
    junk = tmp_path / "junk.sqlite"
    junk.write_bytes(b"this is not a sqlite database at all")
    report = brain_loader.validate_brain(junk)
    assert report.ok is False
    assert "unreadable" in report.reason.lower()


def test_validate_rejects_malformed_entries_schema(tmp_path):
    db = tmp_path / "malformed.sqlite"
    con = sqlite3.connect(db)
    try:
        con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        con.execute("INSERT INTO meta(key, value) VALUES('schema_version', '1')")
        con.execute("CREATE TABLE entries(id TEXT PRIMARY KEY, category TEXT NOT NULL)")
        con.execute("INSERT INTO entries VALUES('e1','custom')")
        con.commit()
    finally:
        con.close()

    report = brain_loader.validate_brain(db)

    assert report.ok is False
    assert "missing columns" in report.reason


def test_validate_accepts_good_brain_and_reads_version(tmp_path):
    db = _make_brain(tmp_path, brain_version="2026.06.03")
    report = brain_loader.validate_brain(db)
    assert report.ok is True
    assert report.brain_version == "2026.06.03"
    assert report.total_entries == 1


def test_freshly_built_brain_carries_version(tmp_path):
    """A brain built via write_brain_sqlite(brain_version=...) reports it back.

    Exercises the real write path: brain_version flows into meta deterministically
    (caller-supplied, not a clock) and validate_brain reads it back.
    """
    db = tmp_path / "built.sqlite"
    entries = normalize_extractions(_built_records())
    write_brain_sqlite(entries, db, brain_version="2026.06.03-test")

    report = brain_loader.validate_brain(db)
    assert report.ok is True
    assert report.brain_version == "2026.06.03-test"

    inventory = inventory_from_sqlite(db)
    assert inventory.brain_version == "2026.06.03-test"
    assert inventory.as_dict()["brain_version"] == "2026.06.03-test"


def test_freshly_built_brain_omits_version_when_not_supplied(tmp_path):
    """Without a brain_version param, no meta row is written (back-compat)."""
    db = tmp_path / "built_noversion.sqlite"
    entries = normalize_extractions(_built_records())
    write_brain_sqlite(entries, db)

    report = brain_loader.validate_brain(db)
    assert report.ok is True
    assert report.brain_version is None


def _built_records() -> list[dict]:
    return [
        {
            "core_lesson": (
                "Build joyful retro-futurist products with transparent casings and "
                "a clear point of view instead of dull modern hardware."
            ),
            "design_principles": [
                "Transparent acrylic and bright internals make hardware impossible to ignore.",
            ],
            "topics": ["product-design"],
            "_source_video": "joyful-tech.mp4",
            "_source_description": "London on avoiding boring electronics.",
        }
    ]
