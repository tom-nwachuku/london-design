"""BRAIN-01 — `london brain install <path>` loud-validation update flow.

TOM-LOCKED privacy boundary: Tom does a new scrape PRIVATELY, produces a distilled
`.sqlite`, and installs it with one command — the engine never changes. install
validates BEFORE installing (loud-fail on a bad brain) and accepts a distilled
`.sqlite` ONLY; it NEVER re-runs extraction. The distilled brain is the only export.

Keyless, deterministic tests driving the REAL public entrypoint ``cli.main`` (the
command surface Tom uses: ``london brain install <path>``). The install destination
is monkeypatched so no test ever clobbers the bundled production brain. Brain
subcommands now route through the same Typer dispatcher as the public binary.
"""

from __future__ import annotations

import contextlib
import io
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from london import cli
from london.library import normalize_extractions, write_brain_sqlite


@dataclass
class _Result:
    exit_code: int
    output: str


def _invoke(argv: list[str]) -> _Result:
    """Run cli.main(argv), capturing console output + the SystemExit code.

    cli.console (rich) resolves its stream from the live sys.stdout on each write,
    so redirect_stdout/redirect_stderr captures it WITHOUT mutating console.file
    (mutating .file leaks across tests and breaks later capsys-based tests).
    """
    captured = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        try:
            cli.main(argv)
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    return _Result(exit_code=code, output=captured.getvalue())


def _good_brain(tmp_path: Path, *, brain_version: str = "2026.06.03") -> Path:
    db = tmp_path / "incoming.sqlite"
    records = [
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
    write_brain_sqlite(normalize_extractions(records), db, brain_version=brain_version)
    return db


def _patch_destination(monkeypatch, tmp_path: Path) -> Path:
    """Redirect the install target to a tmp file (never the bundled brain)."""
    dest = tmp_path / "installed" / "london_brain.sqlite"
    monkeypatch.setattr(cli, "_brain_install_target", lambda: dest)
    return dest


def test_brain_install_rejects_invalid(tmp_path, monkeypatch):
    dest = _patch_destination(monkeypatch, tmp_path)
    bad = tmp_path / "empty.sqlite"
    bad.write_bytes(b"not a db")

    result = _invoke(["brain", "install", str(bad)])

    assert result.exit_code != 0
    lowered = result.output.lower()
    assert "refusing" in lowered or "invalid" in lowered or "unreadable" in lowered
    # A refused brain is never copied into place.
    assert not dest.exists()


def test_brain_install_rejects_empty_brain(tmp_path, monkeypatch):
    dest = _patch_destination(monkeypatch, tmp_path)
    empty = tmp_path / "empty_schema.sqlite"
    write_brain_sqlite([], empty, brain_version="2026.06.03")

    result = _invoke(["brain", "install", str(empty)])

    assert result.exit_code != 0
    assert "no entries" in result.output.lower() or "refusing" in result.output.lower()
    assert not dest.exists()


def test_brain_install_accepts_valid(tmp_path, monkeypatch):
    dest = _patch_destination(monkeypatch, tmp_path)
    src = _good_brain(tmp_path, brain_version="2026.06.03")

    result = _invoke(["brain", "install", str(src)])

    assert result.exit_code == 0
    assert "2026.06.03" in result.output
    # The distilled brain was copied into the installed slot, intact.
    assert dest.exists()
    with contextlib.closing(sqlite3.connect(dest)) as con:
        version = con.execute(
            "SELECT value FROM meta WHERE key='brain_version'"
        ).fetchone()[0]
        count = con.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    assert version == "2026.06.03"
    assert count >= 1


def test_brain_install_preserves_wal_rows_with_sqlite_backup(tmp_path, monkeypatch):
    dest = _patch_destination(monkeypatch, tmp_path)
    src = _good_brain(tmp_path, brain_version="2026.06.03")
    con = sqlite3.connect(src)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute(
            """
            INSERT INTO entries VALUES(
              'wal-row','lessons','WAL row','Committed in WAL','source-wal','sd','[]','{}','wal text'
            )
            """
        )
        con.commit()
        assert src.with_name(src.name + "-wal").exists()

        result = _invoke(["brain", "install", str(src)])
    finally:
        con.close()

    assert result.exit_code == 0
    with contextlib.closing(sqlite3.connect(dest)) as installed:
        row = installed.execute("SELECT title FROM entries WHERE id='wal-row'").fetchone()
    assert row == ("WAL row",)


def test_brain_install_resolves_through_resolve_brain_path_for_inventory_and_session(tmp_path, monkeypatch):
    """W2-P1 — brain split-brain: after installing a user brain, both `london brain
    inventory` AND the offline session RAG must read FROM that user brain, not the bundle.

    The fix routes every brain consumer through ``brain_loader.resolve_brain_path()``
    (env override → user install → bundle).  Pre-fix, ``brain inventory`` and
    ``session.py`` still hardcoded ``DEFAULT_BRAIN_DB`` so the installed brain was
    silently ignored by half the product.
    """
    from london import brain_loader
    from london import session as session_mod

    # Build a marker brain with a uniquely recognisable title.
    marker_title = "W2-P1-SPLIT-BRAIN-MARKER-UNIQUE-ENTRY"
    marker_records = [
        {
            "core_lesson": marker_title,
            "design_principles": ["The user-installed brain is the active brain."],
            "topics": ["product-design"],
            "_source_video": "w2p1-marker.mp4",
            "_source_description": "Marker entry for the W2-P1 split-brain regression test.",
        }
    ]
    installed_db = tmp_path / "user_brain" / "london_brain.sqlite"
    installed_db.parent.mkdir(parents=True, exist_ok=True)
    from london.library import normalize_extractions, write_brain_sqlite
    write_brain_sqlite(normalize_extractions(marker_records), installed_db, brain_version="w2p1-test")

    # Redirect user_brain_path() to our tmp brain — this is what brain install writes to.
    monkeypatch.setattr(brain_loader, "user_brain_path", lambda: installed_db)

    # 1. brain inventory CLI should report the installed brain (by its unique brain_version).
    inventory_result = _invoke(["brain", "inventory"])
    assert inventory_result.exit_code == 0, f"brain inventory failed: {inventory_result.output}"
    assert "w2p1-test" in inventory_result.output, (
        "brain inventory must read from the installed user brain, not the bundle "
        "(expected brain_version 'w2p1-test' in inventory output)"
    )

    # 2. Offline session RAG must also read from the installed brain.
    # The offline session uses brain_loader.resolve_brain_path() via session.py.
    # We query the brain directly through resolve_brain_path to check the seam.
    from london.brain import LondonBrain
    active_brain = LondonBrain(brain_loader.resolve_brain_path())
    entries = active_brain.entries()
    titles = [e.title for e in entries]
    assert any(marker_title in t for t in titles), (
        "resolve_brain_path() must resolve to the installed user brain, not the bundle"
    )

    # 3. The RAG query in a session also honours the installed brain.
    hits = active_brain.query(marker_title, limit=3)
    hit_titles = [h.entry.title for h in hits]
    assert any(marker_title in t for t in hit_titles), (
        "brain RAG query must return the marker entry from the installed brain"
    )


def test_brain_install_never_extracts(tmp_path, monkeypatch):
    """A directory of raw extractions is NOT a valid install input.

    install accepts a distilled `.sqlite` only; pointing it at a raw-extraction
    directory must be refused (non-zero exit) and never trigger extraction.
    """
    _patch_destination(monkeypatch, tmp_path)
    raw_dir = tmp_path / "raw_extractions"
    raw_dir.mkdir()
    (raw_dir / "1.json").write_text('{"core_lesson": "private scrape data"}', encoding="utf-8")

    # Hard guard: if install ever reaches extraction code, fail loudly.
    def _boom(*args, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError("install must never re-run extraction")

    monkeypatch.setattr(cli, "build_sqlite_from_extractions", _boom, raising=False)
    monkeypatch.setattr(cli, "normalize_extractions", _boom, raising=False)

    result = _invoke(["brain", "install", str(raw_dir)])

    assert result.exit_code != 0
    lowered = result.output.lower()
    assert "refusing" in lowered or "invalid" in lowered or "unreadable" in lowered
