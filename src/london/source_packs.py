from __future__ import annotations

from dataclasses import dataclass

from .sources import Source, get_source


@dataclass(frozen=True)
class SourceLens:
    """A local research angle that maps a brief to source types."""

    slug: str
    label: str
    question: str
    source_slugs: tuple[str, ...]
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class SourcePack:
    """A deterministic bundle of lenses and sources for a London research pass."""

    slug: str
    label: str
    description: str
    lens_slugs: tuple[str, ...]
    source_slugs: tuple[str, ...]
    local_prompts: tuple[str, ...]


@dataclass(frozen=True)
class SourcePlan:
    """Resolved source plan for a brief, with no network dependency."""

    brief: str
    packs: tuple[SourcePack, ...]
    lenses: tuple[SourceLens, ...]
    sources: tuple[Source, ...]


SOURCE_LENSES: tuple[SourceLens, ...] = (
    SourceLens(
        slug="typographic-evidence",
        label="Typographic Evidence",
        question="Which real uses prove the voice, hierarchy, and type pairing?",
        source_slugs=("fonts-in-use", "branding-style-guides", "bpando", "the-brand-identity"),
        keywords=("type", "typography", "font", "editorial", "logo", "voice", "hierarchy"),
    ),
    SourceLens(
        slug="photographic-art-direction",
        label="Photographic Art Direction",
        question="What image systems show the casting, props, light, and texture this brief needs?",
        source_slugs=("death-to-stock", "cosmos", "arena", "its-nice-that"),
        keywords=("photo", "photography", "image", "campaign", "editorial", "casting", "texture", "visual"),
    ),
    SourceLens(
        slug="brand-systems",
        label="Brand Systems",
        question="Which identity systems demonstrate the rules, rollout, and restraint?",
        source_slugs=("the-brand-identity", "bpando", "branding-style-guides", "fonts-in-use"),
        keywords=("brand", "identity", "system", "guidelines", "logo", "palette", "campaign"),
    ),
    SourceLens(
        slug="packaging-product",
        label="Packaging Product",
        question="How does the object, label, box, and unboxing moment carry the thesis?",
        source_slugs=("the-dieline", "bpando", "the-brand-identity", "branding-style-guides"),
        keywords=("packaging", "package", "label", "box", "unboxing", "retail", "shelf", "cpg"),
    ),
    SourceLens(
        slug="cultural-archive",
        label="Cultural Archive",
        question="What historic, niche, or internet-born references name the aesthetic without flattening it?",
        source_slugs=("cari", "duke-ad-access", "arena", "cosmos", "its-nice-that"),
        keywords=("archive", "historic", "history", "retro", "nostalgia", "culture", "movement", "aesthetic"),
    ),
    SourceLens(
        slug="web-composition",
        label="Web Composition",
        question="Which sites prove the pacing, frame logic, motion, and page structure?",
        source_slugs=("land-book", "godly", "cargo", "the-brand-identity"),
        keywords=("website", "web", "landing", "homepage", "site", "motion", "layout", "prototype"),
    ),
    SourceLens(
        slug="commerce-conversion",
        label="Commerce Conversion",
        question="Which stores make product story, merchandising, and purchase flow feel designed?",
        source_slugs=("commerce-cream", "mobbin", "land-book", "godly"),
        keywords=("commerce", "ecommerce", "shop", "shopify", "store", "product page", "checkout", "dtc"),
    ),
    SourceLens(
        slug="product-ui-flows",
        label="Product UI Flows",
        question="Which app screens or flows solve the interaction pattern without copying the surface?",
        source_slugs=("mobbin", "commerce-cream", "land-book"),
        keywords=("app", "mobile", "ui", "ux", "flow", "onboarding", "settings", "dashboard", "interface"),
    ),
)

_LENSES_BY_SLUG = {lens.slug: lens for lens in SOURCE_LENSES}

SOURCE_PACKS: tuple[SourcePack, ...] = (
    SourcePack(
        slug="brand-system-pack",
        label="Brand System Pack",
        description="Identity, typography, packaging, and guidelines evidence for a coherent public brand system.",
        lens_slugs=("brand-systems", "typographic-evidence", "packaging-product"),
        source_slugs=(
            "the-brand-identity",
            "bpando",
            "branding-style-guides",
            "fonts-in-use",
            "the-dieline",
        ),
        local_prompts=(
            "Find identity systems with visible rules, not just attractive logos.",
            "Capture type use in finished work before proposing type pairings.",
            "Separate product/packaging evidence from gallery decoration.",
        ),
    ),
    SourcePack(
        slug="image-culture-pack",
        label="Image Culture Pack",
        description="Photography, visual culture, and archive references for art direction and mood.",
        lens_slugs=("photographic-art-direction", "cultural-archive"),
        source_slugs=(
            "death-to-stock",
            "cosmos",
            "arena",
            "its-nice-that",
            "cari",
            "duke-ad-access",
        ),
        local_prompts=(
            "Use images as evidence of scene, texture, casting, and era.",
            "Name the aesthetic with cultural evidence before writing mood words.",
            "Prefer saved artifacts, articles, channels, and archival objects over feeds.",
        ),
    ),
    SourcePack(
        slug="web-commerce-pack",
        label="Web and Commerce Pack",
        description="Website, ecommerce, portfolio, and product UI references for build-ready digital direction.",
        lens_slugs=("web-composition", "commerce-conversion", "product-ui-flows"),
        source_slugs=(
            "land-book",
            "godly",
            "commerce-cream",
            "mobbin",
            "cargo",
        ),
        local_prompts=(
            "Look for page-level composition, responsive behavior, and interaction details.",
            "Treat store references as merchandising systems, not just nice screenshots.",
            "Use UI flows for behavior and state, then re-skin with the brief's own language.",
        ),
    ),
    SourcePack(
        slug="launch-dossier-pack",
        label="Launch Dossier Pack",
        description="Balanced London pass for a full dossier: identity, culture, image, web, commerce, and UI.",
        lens_slugs=(
            "brand-systems",
            "typographic-evidence",
            "photographic-art-direction",
            "cultural-archive",
            "web-composition",
            "commerce-conversion",
        ),
        source_slugs=(
            "fonts-in-use",
            "death-to-stock",
            "cosmos",
            "arena",
            "its-nice-that",
            "the-brand-identity",
            "the-dieline",
            "bpando",
            "cari",
            "duke-ad-access",
            "branding-style-guides",
            "land-book",
            "godly",
            "commerce-cream",
            "mobbin",
            "cargo",
        ),
        local_prompts=(
            "Build the dossier from actual work/detail artifacts across disciplines.",
            "Use each source for its discipline instead of laundering everything into generic inspiration.",
            "Keep citations artifact-shaped: article, case, channel, guide, screen, store, or site.",
        ),
    ),
)

_PACKS_BY_SLUG = {pack.slug: pack for pack in SOURCE_PACKS}

_DEFAULT_LENS_SLUGS = (
    "brand-systems",
    "typographic-evidence",
    "photographic-art-direction",
    "web-composition",
)

_DEFAULT_PACK_SLUGS = (
    "launch-dossier-pack",
    "brand-system-pack",
    "web-commerce-pack",
)


def list_source_lenses() -> tuple[SourceLens, ...]:
    return SOURCE_LENSES


def list_source_packs() -> tuple[SourcePack, ...]:
    return SOURCE_PACKS


def get_source_lens(slug: str) -> SourceLens:
    try:
        return _LENSES_BY_SLUG[slug]
    except KeyError as exc:
        raise KeyError(f"Unknown London source lens: {slug}") from exc


def get_source_pack(slug: str) -> SourcePack:
    try:
        return _PACKS_BY_SLUG[slug]
    except KeyError as exc:
        raise KeyError(f"Unknown London source pack: {slug}") from exc


def recommend_source_lenses(brief: str, *, limit: int = 4) -> tuple[SourceLens, ...]:
    """Return stable local lenses for a brief using keyword scoring only."""

    if limit <= 0:
        return ()

    scored = [
        (_score_text(brief, lens.keywords), index, lens)
        for index, lens in enumerate(SOURCE_LENSES)
    ]
    positive = [item for item in scored if item[0] > 0]
    if not positive:
        return tuple(get_source_lens(slug) for slug in _DEFAULT_LENS_SLUGS[:limit])

    positive.sort(key=lambda item: (-item[0], item[1]))
    selected = [lens for _, _, lens in positive[:limit]]

    if len(selected) < limit:
        selected_slugs = {lens.slug for lens in selected}
        for slug in _DEFAULT_LENS_SLUGS:
            if slug not in selected_slugs:
                selected.append(get_source_lens(slug))
            if len(selected) == limit:
                break
    return tuple(selected)


def recommend_source_packs(brief: str, *, limit: int = 3) -> tuple[SourcePack, ...]:
    """Return stable local packs for a brief without fetching or ranking online data."""

    if limit <= 0:
        return ()

    lens_scores = {
        lens.slug: _score_text(brief, lens.keywords)
        for lens in SOURCE_LENSES
    }
    if not any(lens_scores.values()):
        return tuple(get_source_pack(slug) for slug in _DEFAULT_PACK_SLUGS[:limit])

    scored: list[tuple[int, int, SourcePack]] = []
    for index, pack in enumerate(SOURCE_PACKS):
        lens_score = sum(lens_scores.get(slug, 0) * 10 for slug in pack.lens_slugs)
        prompt_score = _score_text(brief, pack.local_prompts)
        specificity_penalty = len(pack.source_slugs)
        scored.append((lens_score + prompt_score - specificity_penalty, index, pack))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return tuple(pack for _, _, pack in scored[:limit])


def build_source_plan(brief: str, *, pack_limit: int = 3, lens_limit: int = 5) -> SourcePlan:
    """Resolve packs, lenses, and deduped sources for a deterministic local run."""

    packs = recommend_source_packs(brief, limit=pack_limit)
    lenses = recommend_source_lenses(brief, limit=lens_limit)
    source_slugs = _dedupe_slugs(
        slug
        for pack in packs
        for slug in pack.source_slugs
    )
    if not source_slugs:
        source_slugs = _dedupe_slugs(
            slug
            for lens in lenses
            for slug in lens.source_slugs
        )
    return SourcePlan(
        brief=brief,
        packs=packs,
        lenses=lenses,
        sources=tuple(get_source(slug) for slug in source_slugs),
    )


def lens_source_names(lens: SourceLens) -> tuple[str, ...]:
    return tuple(get_source(slug).name for slug in lens.source_slugs)


def pack_source_names(pack: SourcePack) -> tuple[str, ...]:
    return tuple(get_source(slug).name for slug in pack.source_slugs)


def _score_text(text: str, keywords: tuple[str, ...]) -> int:
    normalized = text.lower()
    return sum(1 for keyword in keywords if keyword.lower() in normalized)


def _dedupe_slugs(slugs) -> tuple[str, ...]:
    seen: set[str] = set()
    deduped: list[str] = []
    for slug in slugs:
        if slug not in seen:
            seen.add(slug)
            deduped.append(slug)
    return tuple(deduped)
