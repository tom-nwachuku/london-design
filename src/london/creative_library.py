from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from london.brain import LondonBrain


@dataclass(frozen=True)
class LibraryEntry:
    slug: str
    term: str
    kind: str
    london_explanation: str
    use_when: str
    avoid: str
    related: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["related"] = list(self.related)
        return payload


CURATED_LIBRARY: tuple[LibraryEntry, ...] = (
    LibraryEntry(
        slug="aesthetic-void",
        term="Aesthetic void",
        kind="principle",
        london_explanation="The unclaimed visual and behavioral space in a category before you start styling anything.",
        use_when="A market is full of lookalike products and the brief needs a real reason to exist.",
        avoid="Calling a vibe a void. The void must name what the category is failing to express.",
        related=("anti-positioning", "category tension", "taste"),
    ),
    LibraryEntry(
        slug="anti-positioning",
        term="Anti-positioning",
        kind="strategy",
        london_explanation="Define what the brand refuses to be so the audience can feel the edge of the point of view.",
        use_when="The brand would otherwise become broadly likeable and forgettable.",
        avoid="Being contrarian without a useful customer promise.",
        related=("aesthetic void", "mid branding", "brand enemy"),
    ),
    LibraryEntry(
        slug="fonts-in-use-first",
        term="Fonts In Use first",
        kind="typography",
        london_explanation="Study type in finished real-world systems before choosing a font from taste alone.",
        use_when="The brief needs typography that carries tone, era, and hierarchy.",
        avoid="DaFont, arbitrary font pairing, and moodboard typography with no applied proof.",
        related=("type proof", "Fontshare pairs", "editorial hierarchy"),
    ),
    LibraryEntry(
        slug="postable-product",
        term="Postable product",
        kind="image direction",
        london_explanation="A product or packaging moment designed to be worth photographing without becoming a gimmick.",
        use_when="The object, unboxing, or detail shot has to carry organic social energy.",
        avoid="Generic lifestyle haze where the product becomes a prop instead of the proof.",
        related=("art-directed stock", "unboxing", "object truth"),
    ),
    LibraryEntry(
        slug="withering-technology",
        term="Withered technology",
        kind="product design",
        london_explanation="Use mature, available technology in a novel way instead of pretending invention requires cutting edge parts.",
        use_when="A hardware/product brief needs feasibility and charm, not over-engineering.",
        avoid="Reinventing components that already work or hiding practical constraints from the creative direction.",
        related=("lateral thinking", "golden sample", "hardware joy"),
    ),
    LibraryEntry(
        slug="safe-card-grid",
        term="Safe-card grid",
        kind="anti-pattern",
        london_explanation="A repeated inspiration-card layout that makes every reference equally small and equally uncommitted.",
        use_when="Use only as a warning sign during dossier review.",
        avoid="Making the primary dossier UI a wall of cards instead of large inspectable work previews.",
        related=("Land-book grammar", "large preview", "desktop mobile frames"),
    ),
)

GENERIC_FILLER = ("modern clean", "sleek minimalist", "premium minimal", "startup clean")


def list_library_entries() -> tuple[LibraryEntry, ...]:
    return CURATED_LIBRARY


def search_library(query: str, *, brain: LondonBrain | None = None, limit: int = 8) -> list[dict[str, object]]:
    """Search curated terms and optionally attach London brain evidence."""
    terms = _terms(query)
    curated = [_entry_payload(entry, terms) for entry in CURATED_LIBRARY]
    curated = [entry for entry in curated if entry["score"] > 0]
    curated.sort(key=lambda item: (-float(item["score"]), str(item["term"])))

    if brain is not None:
        hits = brain.query(query, limit=max(2, limit // 2))
        for hit in hits:
            curated.append(
                {
                    "slug": hit.entry.id,
                    "term": hit.entry.title,
                    "kind": hit.entry.category,
                    "london_explanation": hit.entry.body,
                    "use_when": "Use as direct London brain evidence.",
                    "avoid": "Do not flatten this into generic design language.",
                    "related": list(hit.entry.topics),
                    "score": hit.score,
                    "source_ref": hit.entry.source_ref,
                }
            )

    return curated[:limit]


def assert_not_generic_library_output(rows: Iterable[dict[str, object]]) -> None:
    rendered = " ".join(str(row) for row in rows).lower()
    if any(term in rendered for term in GENERIC_FILLER):
        raise AssertionError("Creative library output collapsed into generic design filler.")


def _entry_payload(entry: LibraryEntry, terms: set[str]) -> dict[str, object]:
    haystack = " ".join(
        [
            entry.slug,
            entry.term,
            entry.kind,
            entry.london_explanation,
            entry.use_when,
            entry.avoid,
            " ".join(entry.related),
        ]
    ).lower()
    score = sum(1 for term in terms if term in haystack)
    payload = entry.to_dict()
    payload["score"] = score
    return payload


def _terms(query: str) -> set[str]:
    return {part.strip().lower() for part in query.replace("-", " ").split() if part.strip()}
