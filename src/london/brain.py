from __future__ import annotations

from pathlib import Path
from typing import Sequence

from london.library import (
    DEFAULT_BRAIN_DB,
    DEFAULT_CHROMA_DIR,
    BrainEntry,
    Inventory,
    QueryHit,
    build_chroma_from_sqlite,
    build_sqlite_from_extractions,
    derived_index_status,
    format_inventory,
    format_query_hits,
    inventory_from_sqlite,
    query_chroma_index,
    query_entries,
    read_brain_entries,
)


class LondonBrain:
    """SQLite-backed access to the sanitized public London brain."""

    def __init__(self, db_path: Path | str = DEFAULT_BRAIN_DB) -> None:
        self.db_path = Path(db_path)
        self._entries_cache: list[BrainEntry] | None = None

    @classmethod
    def from_extractions(cls, input_path: Path | str, db_path: Path | str) -> "LondonBrain":
        build_sqlite_from_extractions(input_path, db_path)
        return cls(db_path)

    def entries(self, *, categories: Sequence[str] | None = None) -> list[BrainEntry]:
        if self._entries_cache is None:
            self._entries_cache = read_brain_entries(self.db_path)
        if categories is None:
            return list(self._entries_cache)
        allowed = set(categories)
        return [entry for entry in self._entries_cache if entry.category in allowed]

    def inventory(self) -> Inventory:
        return inventory_from_sqlite(self.db_path)

    def query(
        self,
        text: str,
        *,
        limit: int = 8,
        categories: Sequence[str] | None = None,
    ) -> list[QueryHit]:
        entries = self.entries(categories=categories)
        return query_entries(entries, text, limit=limit, categories=categories)

    def formatted_inventory(self) -> str:
        return format_inventory(self.inventory())

    def formatted_query(
        self,
        text: str,
        *,
        limit: int = 8,
        categories: Sequence[str] | None = None,
    ) -> str:
        return format_query_hits(self.query(text, limit=limit, categories=categories))

    def derived_index_status(self) -> dict[str, object]:
        return derived_index_status(self.db_path)

    def build_chroma(self, index_path: Path | str = DEFAULT_CHROMA_DIR) -> dict[str, object]:
        return build_chroma_from_sqlite(self.db_path, index_path)

    def query_chroma(
        self,
        text: str,
        *,
        index_path: Path | str = DEFAULT_CHROMA_DIR,
        limit: int = 8,
    ) -> list[QueryHit]:
        return query_chroma_index(text, index_path=index_path, db_path=self.db_path, limit=limit)


def open_brain(db_path: Path | str = DEFAULT_BRAIN_DB) -> LondonBrain:
    return LondonBrain(db_path)


def build_brain_from_extractions(input_path: Path | str, db_path: Path | str) -> Inventory:
    return build_sqlite_from_extractions(input_path, db_path)
