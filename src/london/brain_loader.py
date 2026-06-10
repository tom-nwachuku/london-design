"""Resolve and validate the swappable London brain artifact. [TOM-LOCKED]

The brain is a swappable, versioned `.sqlite`. Tom runs a new scrape PRIVATELY,
produces a new distilled brain, and installs it — the engine never changes. This
module is the single seam that answers two questions:

  * resolve_brain_path() — which brain is loaded (LONDON_BRAIN_PATH override, else
    the bundled DEFAULT_BRAIN_DB).
  * validate_brain()      — is it a real, non-empty, readable brain, and what is
    its brain_version (read from the meta table)?

validate_brain() fails LOUDLY (ok=False + a human reason) for a missing /
unreadable / empty brain so the engine never silently runs on a dead artifact.
"""

from __future__ import annotations

import os
import platform
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from london.library import DEFAULT_BRAIN_DB, ENTRY_TABLE_COLUMNS, SCHEMA_VERSION, readonly_sqlite_uri

#: Environment override naming the active brain artifact. NOT a secret.
BRAIN_PATH_ENV = "LONDON_BRAIN_PATH"
USER_BRAIN_ENV = "LONDON_USER_BRAIN_PATH"


@dataclass(frozen=True)
class BrainReport:
    """Outcome of validating a candidate brain artifact."""

    ok: bool
    reason: str = ""
    brain_version: str | None = None
    total_entries: int = 0


def resolve_brain_path() -> Path:
    """Return the active brain path: explicit env, user install, else bundle."""
    override = os.environ.get(BRAIN_PATH_ENV)
    if override:
        return Path(override)
    user_brain = user_brain_path()
    if user_brain.exists():
        return user_brain
    return Path(DEFAULT_BRAIN_DB)


def user_brain_path() -> Path:
    override = os.environ.get(USER_BRAIN_ENV)
    if override:
        return Path(override)
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return root / "london-design" / "london_brain.sqlite"
    if xdg_home := os.environ.get("XDG_DATA_HOME"):
        return Path(xdg_home) / "london-design" / "london_brain.sqlite"
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "london-design" / "london_brain.sqlite"
    return Path.home() / ".local" / "share" / "london-design" / "london_brain.sqlite"


def validate_brain(db_path: Path | str) -> BrainReport:
    """Validate a candidate brain, failing loudly on missing / unreadable / empty.

    Returns ok=True only for a readable sqlite with a `meta` table and at least
    one row in `entries`; brain_version is read from meta (None if absent).
    """
    db = Path(db_path)
    if not db.exists():
        return BrainReport(ok=False, reason=f"brain not found at {db}")
    try:
        with closing(sqlite3.connect(readonly_sqlite_uri(db), uri=True)) as con:
            meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
            schema_version = meta.get("schema_version")
            if schema_version != str(SCHEMA_VERSION):
                return BrainReport(
                    ok=False,
                    reason=f"brain schema_version must be {SCHEMA_VERSION}; got {schema_version or '<missing>'}",
                )
            columns = {row[1] for row in con.execute("PRAGMA table_info(entries)").fetchall()}
            missing_columns = sorted(ENTRY_TABLE_COLUMNS - columns)
            if missing_columns:
                return BrainReport(
                    ok=False,
                    reason="brain entries schema is missing columns: " + ", ".join(missing_columns),
                )
            count = con.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            con.execute(
                """
                SELECT id, category, title, body, source_ref, source_description, topics_json, metadata_json
                FROM entries
                LIMIT 1
                """
            ).fetchone()
    except sqlite3.Error as exc:
        return BrainReport(ok=False, reason=f"unreadable brain: {exc}")
    if count == 0:
        return BrainReport(ok=False, reason="brain has no entries")
    return BrainReport(
        ok=True,
        brain_version=meta.get("brain_version"),
        total_entries=count,
    )
