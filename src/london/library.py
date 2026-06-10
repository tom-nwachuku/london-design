from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

SCHEMA_VERSION = 1
PACKAGE_DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_BRAIN_DB = PACKAGE_DATA_DIR / "london_brain.sqlite"
DEFAULT_CHROMA_DIR = PACKAGE_DATA_DIR / "chroma"
ENTRY_TABLE_COLUMNS = frozenset(
    {
        "id",
        "category",
        "title",
        "body",
        "source_ref",
        "source_description",
        "topics_json",
        "metadata_json",
        "search_text",
    }
)

REQUIRED_CATEGORIES: tuple[str, ...] = (
    "principles",
    "resources",
    "visual_examples",
    "critique_approaches",
    "product_concepts",
    "tools",
    "workflow_steps",
    "lessons",
    "topics",
)

GENERIC_FILLER_TERMS: tuple[str, ...] = (
    "modern clean",
    "clean modern",
    "sleek minimalist",
    "minimalist startup",
    "premium minimal",
)

CRITIQUE_MARKERS: tuple[str, ...] = (
    "avoid",
    "bad",
    "boring",
    "bland",
    "canva",
    "critique",
    "dafont",
    "do not",
    "don't",
    "generic",
    "mediocre",
    "mid",
    "noise",
    "not sufficient",
    "overcrowded",
    "pinterest",
    "reject",
    "shutterstock",
    "stop",
    "suck",
    "trendy",
)

TOKEN_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "typography": ("font", "fonts", "type", "typeface", "fontshare", "fontsinuse"),
    "typographic": ("font", "fonts", "type", "typeface", "fontshare", "fontsinuse"),
    "font": ("typography", "typeface", "fontshare", "fontsinuse"),
    "fonts": ("typography", "typeface", "fontshare", "fontsinuse"),
    "joyful": ("fun", "playful", "colorful", "vibrant", "bright"),
    "retro": ("retrofuturist", "retro-futurist", "retro-futurism", "y2k", "90s"),
    "futurist": ("retrofuturist", "retro-futurist", "futuristic", "transparent"),
    "retrofuturist": ("retro", "futuristic", "transparent", "acrylic", "y2k"),
    "product": ("packaging", "hardware", "object", "industrial", "utility"),
    "critique": ("avoid", "reject", "mid", "generic", "boring", "dafont"),
}

STOPWORDS: set[str] = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
    "your",
}


@dataclass(frozen=True)
class BrainEntry:
    id: str
    category: str
    title: str
    body: str
    source_ref: str
    source_description: str
    topics: tuple[str, ...] = ()
    metadata: Mapping[str, Any] | None = None

    @property
    def search_text(self) -> str:
        parts = [
            self.category,
            self.title,
            self.body,
            self.source_description,
            " ".join(self.topics),
            json.dumps(dict(self.metadata or {}), sort_keys=True),
        ]
        return "\n".join(part for part in parts if part)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "title": self.title,
            "body": self.body,
            "source_ref": self.source_ref,
            "source_description": self.source_description,
            "topics": list(self.topics),
            "metadata": dict(self.metadata or {}),
        }


@dataclass(frozen=True)
class QueryHit:
    entry: BrainEntry
    score: float
    matched_terms: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        payload = self.entry.as_dict()
        payload["score"] = round(self.score, 4)
        payload["matched_terms"] = list(self.matched_terms)
        return payload


@dataclass(frozen=True)
class Inventory:
    total_entries: int
    categories: Mapping[str, int]
    source_count: int
    top_topics: tuple[tuple[str, int], ...]
    schema_version: int = SCHEMA_VERSION
    brain_version: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "brain_version": self.brain_version,
            "total_entries": self.total_entries,
            "categories": dict(self.categories),
            "source_count": self.source_count,
            "top_topics": [{"topic": topic, "count": count} for topic, count in self.top_topics],
        }


def load_extraction_records(path: Path | str) -> list[dict[str, Any]]:
    input_path = Path(path)
    if input_path.is_dir():
        files = sorted(input_path.glob("*.json"))
    else:
        files = [input_path]

    records: list[dict[str, Any]] = []
    for file_path in files:
        if not file_path.exists():
            raise FileNotFoundError(file_path)
        data = json.loads(file_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{file_path} must contain a JSON object")
        data.setdefault("_file", file_path.name)
        records.append(data)
    return records


def normalize_extractions(records: Iterable[Mapping[str, Any]]) -> list[BrainEntry]:
    entries: list[BrainEntry] = []
    seen: set[str] = set()

    def add(
        category: str,
        title: str,
        body: str,
        record: Mapping[str, Any],
        *,
        topics: Sequence[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        title_clean = _clean_text(title)
        body_clean = _clean_text(body)
        if category not in REQUIRED_CATEGORIES or not title_clean or not body_clean:
            return
        source_ref = _source_ref(record)
        source_description = _clean_text(_string(record.get("_source_description")))
        topic_values = tuple(_dedupe(_clean_text(topic) for topic in (topics or _topics(record))))
        entry_id = _entry_id(category, title_clean, body_clean, source_ref)
        if entry_id in seen:
            return
        seen.add(entry_id)
        entries.append(
            BrainEntry(
                id=entry_id,
                category=category,
                title=title_clean,
                body=body_clean,
                source_ref=source_ref,
                source_description=source_description,
                topics=topic_values,
                metadata=dict(metadata or {}),
            )
        )

    for record in records:
        lesson = _clean_text(_string(record.get("core_lesson")))
        if lesson:
            add(
                "lessons",
                _title_from_text(lesson, fallback="Core lesson"),
                lesson,
                record,
                metadata={
                    "subtype": "core_lesson",
                    "directive_count": len(_strings(record.get("actionable_directives"))),
                    "workflow_count": len(_strings(record.get("workflow_steps"))),
                    "visual_count": len(_strings(record.get("visual_examples_on_screen"))),
                },
            )
            if _is_critique(lesson):
                add(
                    "critique_approaches",
                    _title_from_text(lesson, fallback="Critical stance"),
                    lesson,
                    record,
                    metadata={"derived_from": "core_lesson"},
                )

        for item in _strings(record.get("design_principles")):
            add(
                "principles",
                _title_from_text(item, fallback="Design principle"),
                item,
                record,
                metadata={"subtype": "design_principle"},
            )
            if _is_critique(item):
                add(
                    "critique_approaches",
                    _title_from_text(item, fallback="Design critique"),
                    item,
                    record,
                    metadata={"derived_from": "design_principle"},
                )

        for item in _strings(record.get("strategic_frameworks")):
            add(
                "principles",
                _title_from_text(item, fallback="Strategic framework"),
                item,
                record,
                metadata={"subtype": "strategic_framework"},
            )
            if _is_critique(item):
                add(
                    "critique_approaches",
                    _title_from_text(item, fallback="Strategic critique"),
                    item,
                    record,
                    metadata={"derived_from": "strategic_framework"},
                )

        for index, item in enumerate(_strings(record.get("actionable_directives")), start=1):
            add(
                "workflow_steps",
                f"Directive {index}: {_title_from_text(item, fallback='Actionable directive')}",
                item,
                record,
                metadata={"subtype": "actionable_directive", "sequence": index},
            )
            if _is_critique(item):
                add(
                    "critique_approaches",
                    _title_from_text(item, fallback="Actionable critique"),
                    item,
                    record,
                    metadata={"derived_from": "actionable_directive"},
                )

        for index, item in enumerate(_strings(record.get("workflow_steps")), start=1):
            add(
                "workflow_steps",
                f"Step {index}: {_title_from_text(item, fallback='Workflow step')}",
                item,
                record,
                metadata={"subtype": "workflow_step", "sequence": index},
            )
            if _is_critique(item):
                add(
                    "critique_approaches",
                    _title_from_text(item, fallback="Workflow critique"),
                    item,
                    record,
                    metadata={"derived_from": "workflow_step"},
                )

        for index, item in enumerate(_strings(record.get("visual_examples_on_screen")), start=1):
            add(
                "visual_examples",
                f"Visual example {index}: {_title_from_text(item, fallback='On-screen reference')}",
                item,
                record,
                metadata={"sequence": index},
            )

        for item in _dicts(record.get("resources_and_references")):
            name = _clean_text(_string(item.get("name")))
            reason = _clean_text(_string(item.get("why_referenced")))
            if name and reason:
                add(
                    "resources",
                    name,
                    f"{name}: {reason}",
                    record,
                    metadata={"resource_name": name},
                )

        for item in _dicts(record.get("tools_and_platforms")):
            name = _clean_text(_string(item.get("name")))
            use_case = _clean_text(_string(item.get("use_case")))
            url = _clean_text(_string(item.get("url")))
            body = "\n".join(part for part in (f"{name}: {use_case}" if use_case else name, url) if part)
            if name and body:
                add(
                    "tools",
                    name,
                    body,
                    record,
                    metadata={"tool_name": name, "url": url},
                )

        product = record.get("product_concept")
        if isinstance(product, Mapping) and product.get("exists"):
            name = _clean_text(_string(product.get("name"))) or "Unnamed product concept"
            body_parts = [
                f"Product concept: {name}",
                _labeled("Category", product.get("category")),
                _labeled("Design direction", product.get("design_direction")),
                _labeled("Launch strategy", product.get("launch_strategy")),
                _labeled("Target market", product.get("target_market")),
            ]
            if lesson:
                body_parts.append(f"Core lesson: {lesson}")
            add(
                "product_concepts",
                name,
                "\n".join(part for part in body_parts if part),
                record,
                metadata={
                    "product_name": name,
                    "category": _clean_text(_string(product.get("category"))),
                },
            )

        for topic in _topics(record):
            add(
                "topics",
                topic,
                _topic_body(topic, lesson, record),
                record,
                topics=(topic,),
                metadata={"topic": topic},
            )

    return entries


def write_brain_sqlite(
    entries: Sequence[BrainEntry],
    db_path: Path | str,
    *,
    replace: bool = True,
    brain_version: str | None = None,
) -> Path:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if replace and path.exists():
        path.unlink()

    with closing(sqlite3.connect(path)) as conn:
        with conn:
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS entries (
                    id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    source_description TEXT NOT NULL,
                    topics_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    search_text TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_entries_category ON entries(category);
                CREATE INDEX IF NOT EXISTS idx_entries_source ON entries(source_ref);
                """
            )
            conn.execute("DELETE FROM entries")
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
            # brain_version is provenance for the swappable brain (BRAIN-01). It is a
            # caller-supplied value, NEVER a clock call — this preserves the
            # deterministic-rebuild property of the brain artifact.
            if brain_version is not None:
                conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                    ("brain_version", str(brain_version)),
                )
            conn.executemany(
                """
                INSERT INTO entries(
                    id,
                    category,
                    title,
                    body,
                    source_ref,
                    source_description,
                    topics_json,
                    metadata_json,
                    search_text
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        entry.id,
                        entry.category,
                        entry.title,
                        entry.body,
                        entry.source_ref,
                        entry.source_description,
                        json.dumps(list(entry.topics), sort_keys=True),
                        json.dumps(dict(entry.metadata or {}), sort_keys=True),
                        entry.search_text,
                    )
                    for entry in entries
                ),
            )
    return path


def build_sqlite_from_extractions(input_path: Path | str, db_path: Path | str) -> Inventory:
    records = load_extraction_records(input_path)
    entries = normalize_extractions(records)
    write_brain_sqlite(entries, db_path)
    return inventory_from_sqlite(db_path)


def read_brain_entries(
    db_path: Path | str = DEFAULT_BRAIN_DB,
    *,
    categories: Sequence[str] | None = None,
) -> list[BrainEntry]:
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"London brain SQLite not found: {path}")

    params: list[str] = []
    where = ""
    if categories:
        placeholders = ", ".join("?" for _ in categories)
        where = f"WHERE category IN ({placeholders})"
        params.extend(categories)

    with closing(_connect_readonly(path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT id, category, title, body, source_ref, source_description, topics_json, metadata_json
            FROM entries
            {where}
            ORDER BY category, title, source_ref
            """,
            params,
        ).fetchall()

    return [_row_to_entry(row) for row in rows]


def _read_brain_version(db_path: Path | str = DEFAULT_BRAIN_DB) -> str | None:
    """Read the provenance brain_version from meta (None if absent)."""
    path = Path(db_path)
    if not path.exists():
        return None
    try:
        with closing(_connect_readonly(path)) as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = ?", ("brain_version",)
            ).fetchone()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def inventory_from_sqlite(db_path: Path | str = DEFAULT_BRAIN_DB) -> Inventory:
    entries = read_brain_entries(db_path)
    category_counts = {category: 0 for category in REQUIRED_CATEGORIES}
    sources: set[str] = set()
    topic_counts: dict[str, int] = {}

    for entry in entries:
        category_counts[entry.category] = category_counts.get(entry.category, 0) + 1
        if entry.source_ref:
            sources.add(entry.source_ref)
        for topic in entry.topics:
            topic_counts[topic] = topic_counts.get(topic, 0) + 1

    top_topics = tuple(sorted(topic_counts.items(), key=lambda item: (-item[1], item[0]))[:20])
    return Inventory(
        total_entries=len(entries),
        categories=category_counts,
        source_count=len(sources),
        top_topics=top_topics,
        brain_version=_read_brain_version(db_path),
    )


def query_entries(
    entries: Sequence[BrainEntry],
    query: str,
    *,
    limit: int = 8,
    categories: Sequence[str] | None = None,
) -> list[QueryHit]:
    clamped_limit = max(1, int(limit))
    allowed = set(categories) if categories is not None else None
    query_terms = _expanded_terms(_tokenize(query))
    phrase = _clean_text(query).lower()
    hits: list[QueryHit] = []

    for entry in entries:
        if allowed is not None and entry.category not in allowed:
            continue
        score, matches = _score_entry(entry, query_terms, phrase)
        if score > 0:
            hits.append(QueryHit(entry=entry, score=score, matched_terms=tuple(sorted(matches))))

    hits.sort(key=lambda hit: (-hit.score, hit.entry.category, hit.entry.title))
    return hits[:clamped_limit]


def format_inventory(inventory: Inventory) -> str:
    lines = [
        "London brain inventory",
        f"schema_version: {inventory.schema_version}",
        f"brain_version: {inventory.brain_version or 'unset'}",
        f"total_entries: {inventory.total_entries}",
        f"sources: {inventory.source_count}",
        "categories:",
    ]
    for category in REQUIRED_CATEGORIES:
        lines.append(f"  {category}: {inventory.categories.get(category, 0)}")
    if inventory.top_topics:
        topic_text = ", ".join(f"{topic} ({count})" for topic, count in inventory.top_topics[:10])
        lines.append(f"top_topics: {topic_text}")
    return "\n".join(lines)


def format_query_hits(hits: Sequence[QueryHit]) -> str:
    if not hits:
        return "No London brain entries matched that query."

    lines: list[str] = []
    for index, hit in enumerate(hits, start=1):
        entry = hit.entry
        lines.append(f"{index}. [{entry.category}] {entry.title}")
        lines.append(f"   score: {hit.score:.2f}; matches: {', '.join(hit.matched_terms)}")
        lines.append(f"   {entry.body}")
        if entry.source_ref:
            lines.append(f"   source: {entry.source_ref}")
    return "\n".join(lines)


def derived_index_status(db_path: Path | str = DEFAULT_BRAIN_DB) -> dict[str, Any]:
    path = Path(db_path)
    chroma_path = DEFAULT_CHROMA_DIR if path == DEFAULT_BRAIN_DB else path.with_suffix(".chroma")
    return {
        "source": _public_db_source(path),
        "source_exists": path.exists(),
        "derived_indexes": [str(chroma_path)] if chroma_path.exists() else [],
        "chroma": "ready" if chroma_path.exists() else "build_required",
        "message": "SQLite is the public source of truth; Chroma is a derived index rebuildable from SQLite.",
    }


def build_chroma_from_sqlite(
    db_path: Path | str = DEFAULT_BRAIN_DB,
    index_path: Path | str = DEFAULT_CHROMA_DIR,
    *,
    collection_name: str = "london_brain",
) -> dict[str, Any]:
    """Build a Chroma index from the sanitized SQLite brain using local embeddings."""

    import chromadb

    entries = read_brain_entries(db_path)
    path = Path(index_path)
    path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(path))
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass
    collection = client.get_or_create_collection(collection_name, metadata={"source": "sqlite-derived"})

    if entries:
        collection.add(
            ids=[entry.id for entry in entries],
            documents=[entry.search_text for entry in entries],
            embeddings=[_local_embedding(entry.search_text) for entry in entries],
            metadatas=[_chroma_metadata(entry) for entry in entries],
        )

    return {
        "source": _public_db_source(db_path),
        "index_path": str(path),
        "collection": collection_name,
        "count": collection.count(),
    }


def query_chroma_index(
    query: str,
    index_path: Path | str = DEFAULT_CHROMA_DIR,
    *,
    db_path: Path | str = DEFAULT_BRAIN_DB,
    collection_name: str = "london_brain",
    limit: int = 8,
) -> list[QueryHit]:
    """Query a derived Chroma index and hydrate public entries from SQLite."""

    import chromadb

    client = chromadb.PersistentClient(path=str(index_path))
    collection = client.get_collection(collection_name)
    results = collection.query(
        query_embeddings=[_local_embedding(query)],
        n_results=limit,
        include=["documents", "metadatas", "distances"],
    )
    entries_by_id = {entry.id: entry for entry in read_brain_entries(db_path)}
    query_terms = _expanded_terms(_tokenize(query))
    hits: list[QueryHit] = []
    for metadata, distance in zip(
        results.get("metadatas", [[]])[0],
        results.get("distances", [[]])[0],
        strict=False,
    ):
        entry = entries_by_id.get(str(metadata["id"]))
        if entry is None:
            continue
        entry_terms = set(_tokenize(entry.search_text.lower()))
        matched = query_terms & entry_terms
        hits.append(
            QueryHit(
                entry=entry,
                score=max(0.0, 10.0 - float(distance)),
                matched_terms=tuple(sorted(matched)),
            )
        )
    return hits


def _row_to_entry(row: sqlite3.Row) -> BrainEntry:
    return BrainEntry(
        id=row["id"],
        category=row["category"],
        title=row["title"],
        body=row["body"],
        source_ref=row["source_ref"],
        source_description=row["source_description"],
        topics=tuple(json.loads(row["topics_json"])),
        metadata=json.loads(row["metadata_json"]),
    )


def readonly_sqlite_uri(db_path: Path | str) -> str:
    path = Path(db_path)
    return f"file:{quote(str(path), safe='/')}?mode=ro"


def _connect_readonly(db_path: Path | str) -> sqlite3.Connection:
    return sqlite3.connect(readonly_sqlite_uri(db_path), uri=True)


def _score_entry(entry: BrainEntry, query_terms: set[str], phrase: str) -> tuple[float, set[str]]:
    search_text = entry.search_text.lower()
    title_text = entry.title.lower()
    topic_text = " ".join(entry.topics).lower()
    entry_terms = set(_tokenize(search_text))
    matches = query_terms & entry_terms
    score = float(len(matches))

    for term in matches:
        if term in title_text:
            score += 2.0
        if term in topic_text:
            score += 1.25
    if phrase and phrase in search_text:
        score += 3.0
    if entry.category in {"lessons", "principles", "tools", "product_concepts"}:
        score += 0.35
    if entry.category == "critique_approaches" and {"critique", "avoid", "reject", "mid", "generic"} & query_terms:
        score += 1.5
    if entry.category == "visual_examples" and {"visual", "image", "imagery", "reference"} & query_terms:
        score += 1.5

    return score, matches


def _expanded_terms(tokens: Iterable[str]) -> set[str]:
    expanded: set[str] = set()
    for token in tokens:
        expanded.add(token)
        if token.endswith("s") and len(token) > 3:
            expanded.add(token[:-1])
        expanded.update(TOKEN_EXPANSIONS.get(token, ()))
    return expanded


def _tokenize(text: str) -> list[str]:
    normalized = text.lower().replace("retro-futurist", "retrofuturist").replace("retro-futurism", "retrofuturism")
    return [token for token in re.findall(r"[a-z0-9]+", normalized) if token not in STOPWORDS]


def _chroma_metadata(entry: BrainEntry) -> dict[str, str]:
    return {
        "id": entry.id,
        "category": entry.category,
        "title": entry.title,
        "body": entry.body[:7000],
        "source_ref": entry.source_ref,
        "source_description": entry.source_description[:1000],
        "topics_json": json.dumps(list(entry.topics), sort_keys=True),
        "metadata_json": json.dumps(dict(entry.metadata or {}), sort_keys=True),
    }


def _public_db_source(db_path: Path | str) -> str:
    path = Path(db_path)
    try:
        if path.resolve() == DEFAULT_BRAIN_DB.resolve():
            return "bundled:london_brain.sqlite"
    except FileNotFoundError:
        if path == DEFAULT_BRAIN_DB:
            return "bundled:london_brain.sqlite"
    return f"sqlite:{path.name}"


def _local_embedding(text: str, dimensions: int = 48) -> list[float]:
    vector = [0.0] * dimensions
    for token in _expanded_terms(_tokenize(text)):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:2], "big") % dimensions
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        weight = 1.0 + (digest[3] % 7) / 10.0
        vector[index] += sign * weight
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def _entry_id(category: str, title: str, body: str, source_ref: str) -> str:
    digest = hashlib.sha256(f"{category}\0{title}\0{body}\0{source_ref}".encode("utf-8")).hexdigest()
    return digest[:24]


def _source_ref(record: Mapping[str, Any]) -> str:
    value = _string(record.get("_source_video")) or _string(record.get("_file"))
    if not value:
        return ""
    raw_name = Path(value).name
    digest = hashlib.sha256(raw_name.encode("utf-8")).hexdigest()[:12]
    return f"source-{digest}"


def _topic_body(topic: str, lesson: str, record: Mapping[str, Any]) -> str:
    parts = [f"Topic: {topic}"]
    if lesson:
        parts.append(f"Connected lesson: {lesson}")
    description = _clean_text(_string(record.get("_source_description")))
    if description:
        parts.append(f"Source description: {description}")
    return "\n".join(parts)


def _is_critique(text: str) -> bool:
    lower = text.lower()
    return any(marker in lower for marker in CRITIQUE_MARKERS)


def _topics(record: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(_dedupe(_normalize_topic(topic) for topic in _strings(record.get("topics"))))


def _normalize_topic(topic: str) -> str:
    return re.sub(r"[\s_]+", "-", _clean_text(topic).lower()).strip("-")


def _dicts(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clean_text(item) for item in value if isinstance(item, str) and _clean_text(item)]


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _clean_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _title_from_text(text: str, *, fallback: str, limit: int = 86) -> str:
    clean = _clean_text(text)
    if not clean:
        return fallback
    first = re.split(r"(?<=[.!?])\s+", clean, maxsplit=1)[0]
    if len(first) <= limit:
        return first
    return first[: limit - 1].rstrip() + "..."


def _labeled(label: str, value: Any) -> str:
    clean = _clean_text(_string(value))
    return f"{label}: {clean}" if clean else ""


def _dedupe(values: Iterable[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output
