from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re
from typing import Iterable, Mapping
from urllib.parse import urlparse


@dataclass(frozen=True)
class Source:
    """Public source registry entry for local, deterministic research planning."""

    slug: str
    name: str
    homepage: str
    disciplines: tuple[str, ...]
    artifact_types: tuple[str, ...]
    use_for: str
    avoid: str
    domains: tuple[str, ...]


@dataclass(frozen=True)
class ExtractionCandidate:
    """A candidate URL discovered by an importer before any network fetch occurs."""

    url: str
    title: str = ""
    source_slug: str | None = None


@dataclass(frozen=True)
class ExtractorDecision:
    """Deterministic decision about whether a candidate is worth extracting."""

    url: str
    source_slug: str | None
    accepted: bool
    artifact_kind: str | None
    reason: str


@dataclass(frozen=True)
class SourceArtifact:
    """A deterministic extracted source artifact, not gallery/container chrome."""

    artifact_id: str
    source_slug: str
    url: str
    title: str
    artifact_kind: str
    summary: str
    assets: tuple[str, ...]
    tags: tuple[str, ...]
    receipt: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "source_slug": self.source_slug,
            "url": self.url,
            "title": self.title,
            "artifact_kind": self.artifact_kind,
            "summary": self.summary,
            "assets": list(self.assets),
            "tags": list(self.tags),
            "receipt": dict(self.receipt),
        }


@dataclass(frozen=True)
class _ArtifactRule:
    pattern: str
    artifact_kind: str


@dataclass(frozen=True)
class _ExtractorRules:
    accept: tuple[_ArtifactRule, ...]
    reject: tuple[str, ...]


SOURCE_REGISTRY: tuple[Source, ...] = (
    Source(
        slug="fonts-in-use",
        name="Fonts In Use",
        homepage="https://fontsinuse.com",
        disciplines=("typography", "brand identity", "editorial", "packaging"),
        artifact_types=("type use case", "specimen", "brand typography evidence"),
        use_for="Prove how type actually behaves in finished identity, editorial, packaging, and campaign systems.",
        avoid="Typeface directory pages, foundry browsing, and broad topic feeds without a specific use case.",
        domains=("fontsinuse.com",),
    ),
    Source(
        slug="death-to-stock",
        name="Death to Stock",
        homepage="https://deathtothestockphoto.com",
        disciplines=("photography", "art direction", "campaign imagery", "texture"),
        artifact_types=("image collection", "visual story", "photo set"),
        use_for="Art-directed photographic language, image texture, prop logic, casting, and campaign mood.",
        avoid="Membership, pricing, and collection index pages that only sell the library wrapper.",
        domains=("deathtothestockphoto.com", "deathtostock.com"),
    ),
    Source(
        slug="cosmos",
        name="Cosmos",
        homepage="https://www.cosmos.so",
        disciplines=("moodboard", "visual culture", "art direction", "reference gathering"),
        artifact_types=("curated post", "collection", "cluster"),
        use_for="Fast visual adjacency mapping across taste, culture, image fragments, and reference clusters.",
        avoid="Explore, search, and profile chrome without a stable saved item or collection.",
        domains=("cosmos.so",),
    ),
    Source(
        slug="arena",
        name="Are.na",
        homepage="https://www.are.na",
        disciplines=("research", "moodboard", "internet culture", "conceptual adjacency"),
        artifact_types=("channel", "block"),
        use_for="Curated reference channels and discrete blocks that reveal how people connect concepts.",
        avoid="Global search, explore pages, and channel indexes without a selected channel or block.",
        domains=("are.na", "arena.com"),
    ),
    Source(
        slug="its-nice-that",
        name="It's Nice That",
        homepage="https://www.itsnicethat.com",
        disciplines=("editorial design", "illustration", "graphic design", "creative culture"),
        artifact_types=("article", "profile", "project write-up"),
        use_for="Editorial context around creative work, makers, studios, and contemporary visual culture.",
        avoid="Discipline landing pages, search results, and article indexes.",
        domains=("itsnicethat.com",),
    ),
    Source(
        slug="the-brand-identity",
        name="The Brand Identity",
        homepage="https://the-brandidentity.com",
        disciplines=("brand identity", "graphic design", "art direction", "systems"),
        artifact_types=("identity project", "studio profile", "case study"),
        use_for="Contemporary identity systems with enough visual evidence to discuss type, grid, color, and rollout.",
        avoid="Category, tag, and industry pages that list projects without opening the work.",
        domains=("the-brandidentity.com",),
    ),
    Source(
        slug="the-dieline",
        name="The Dieline",
        homepage="https://thedieline.com",
        disciplines=("packaging", "consumer goods", "brand identity", "retail"),
        artifact_types=("packaging article", "case study", "product system"),
        use_for="Packaging systems, shelf presence, material choices, unboxing, and product storytelling.",
        avoid="Packaging category feeds, award indexes, and article list pages.",
        domains=("thedieline.com",),
    ),
    Source(
        slug="bpando",
        name="BP&O",
        homepage="https://bpando.org",
        disciplines=("brand identity", "packaging", "print", "graphic systems"),
        artifact_types=("identity review", "packaging review", "case analysis"),
        use_for="Opinionated identity and packaging critique with close attention to execution details.",
        avoid="Category pages and archive pages where the critique has not been opened.",
        domains=("bpando.org",),
    ),
    Source(
        slug="cari",
        name="CARI",
        homepage="https://cari.institute",
        disciplines=("aesthetic history", "internet culture", "visual taxonomy", "retro culture"),
        artifact_types=("aesthetic dossier", "taxonomy entry", "reference collection"),
        use_for="Naming and grounding visual movements, especially retro, niche, and internet-born aesthetics.",
        avoid="Aesthetic indexes and resource lists that do not open a specific movement or collection.",
        domains=("cari.institute",),
    ),
    Source(
        slug="duke-ad-access",
        name="Duke Ad Access",
        homepage="https://repository.duke.edu/dc/adaccess",
        disciplines=("advertising archive", "campaign history", "print", "consumer culture"),
        artifact_types=("archival ad", "campaign artifact", "print scan"),
        use_for="Historic advertising objects with enough artifact detail to study claims, layout, and product codes.",
        avoid="Collection landing pages and search results without a selected archival object.",
        domains=("repository.duke.edu",),
    ),
    Source(
        slug="branding-style-guides",
        name="Branding Style Guides",
        homepage="https://brandingstyleguides.com",
        disciplines=("brand guidelines", "identity systems", "governance", "design ops"),
        artifact_types=("brand guide", "identity manual", "guidelines artifact"),
        use_for="Operational brand systems: logo rules, type, palette, layout, tone, and usage constraints.",
        avoid="Guide directory pages and broad category pages without a selected manual.",
        domains=("brandingstyleguides.com",),
    ),
    Source(
        slug="land-book",
        name="Land-book",
        homepage="https://land-book.com",
        disciplines=("web design", "landing pages", "interaction", "marketing sites"),
        artifact_types=("website showcase", "page detail", "responsive reference"),
        use_for="Website composition, landing page pacing, visual hierarchy, and full-page presentation patterns.",
        avoid="Website indexes, category pages, and generic tag browsing.",
        domains=("land-book.com",),
    ),
    Source(
        slug="godly",
        name="Godly",
        homepage="https://godly.website",
        disciplines=("web design", "motion", "interaction", "digital art direction"),
        artifact_types=("website showcase", "interaction reference", "digital case detail"),
        use_for="High-taste digital references where motion, layout, and interactive finish matter.",
        avoid="Global website feeds and tag pages without a selected site.",
        domains=("godly.website",),
    ),
    Source(
        slug="commerce-cream",
        name="Commerce Cream",
        homepage="https://commercecream.com",
        disciplines=("commerce", "shopify", "product pages", "dtc"),
        artifact_types=("store showcase", "commerce case detail", "product page reference"),
        use_for="DTC store patterns, product storytelling, merchandising, and conversion-aware creative direction.",
        avoid="Category feeds and platform indexes without a selected store.",
        domains=("commercecream.com",),
    ),
    Source(
        slug="mobbin",
        name="Mobbin",
        homepage="https://mobbin.com",
        disciplines=("product design", "mobile UI", "flows", "interaction patterns"),
        artifact_types=("app screen", "product flow", "UI pattern"),
        use_for="Concrete app screens and flows for interaction, onboarding, checkout, settings, and product UX.",
        avoid="Browse, search, app directory, and pattern index pages without a selected app, screen, or flow.",
        domains=("mobbin.com",),
    ),
    Source(
        slug="cargo",
        name="Cargo",
        homepage="https://cargo.site",
        disciplines=("portfolio", "web design", "artist sites", "experimental publishing"),
        artifact_types=("portfolio site", "project page", "experimental web reference"),
        use_for="Artist and studio portfolio patterns, expressive publishing, and non-template web behavior.",
        avoid="Template, pricing, feature, and marketing pages for the platform itself.",
        domains=("cargo.site", "cargocollective.com"),
    ),
)


_REGISTRY_BY_SLUG = {source.slug: source for source in SOURCE_REGISTRY}

_GLOBAL_CHROME_TITLE_HINTS = (
    "search",
    "search results",
    "browse",
    "explore",
    "category",
    "categories",
    "tagged",
    "archive",
    "latest",
    "all websites",
    "all articles",
    "all projects",
)

_GLOBAL_CHROME_SEGMENTS = {
    "",
    "about",
    "advertise",
    "apps",
    "archive",
    "archives",
    "articles",
    "blog",
    "browse",
    "categories",
    "category",
    "channels",
    "collections",
    "contact",
    "discover",
    "explore",
    "features",
    "guides",
    "home",
    "industries",
    "industry",
    "latest",
    "login",
    "membership",
    "news",
    "patterns",
    "pricing",
    "projects",
    "search",
    "shop",
    "sign-in",
    "signin",
    "sites",
    "stores",
    "tag",
    "tags",
    "templates",
    "topics",
    "uses",
    "websites",
}

_ASSET_EXTENSIONS = (
    ".avif",
    ".css",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".mp4",
    ".pdf",
    ".png",
    ".svg",
    ".webp",
    ".xml",
)

_EXTRACTOR_RULES: dict[str, _ExtractorRules] = {
    "fonts-in-use": _ExtractorRules(
        accept=(
            _ArtifactRule(r"^/uses/\d+(?:/[a-z0-9][a-z0-9-]*)?/?$", "type use case"),
        ),
        reject=(
            r"^/$",
            r"^/uses/?$",
            r"^/(?:typefaces|topics|formats|industries|staff-picks|search)(?:/.*)?$",
        ),
    ),
    "death-to-stock": _ExtractorRules(
        accept=(
            _ArtifactRule(r"^/(?:collections|sets|stories|articles)/[a-z0-9][a-z0-9-]+/?$", "image collection"),
        ),
        reject=(
            r"^/$",
            r"^/(?:collections|sets|stories|articles|membership|pricing|shop|search)(?:/)?$",
        ),
    ),
    "cosmos": _ExtractorRules(
        accept=(
            _ArtifactRule(r"^/(?:e|p|c|clusters|collections)/[a-z0-9][a-z0-9-]+/?$", "curated visual artifact"),
        ),
        reject=(
            r"^/$",
            r"^/(?:explore|search|following|collections|clusters|about)(?:/)?$",
        ),
    ),
    "arena": _ExtractorRules(
        accept=(
            _ArtifactRule(r"^/blocks/\d+/?$", "curated block"),
            _ArtifactRule(r"^/[a-z0-9][a-z0-9-]+/[a-z0-9][a-z0-9-]+/?$", "curated channel"),
        ),
        reject=(
            r"^/$",
            r"^/(?:channels|blocks|search|explore|following|settings)(?:/)?$",
        ),
    ),
    "its-nice-that": _ExtractorRules(
        accept=(
            _ArtifactRule(r"^/articles/[a-z0-9][a-z0-9-]+/?$", "creative article"),
        ),
        reject=(
            r"^/$",
            r"^/(?:articles|graphic-design|art|photography|advertising|illustration|features|search|archive)(?:/)?$",
        ),
    ),
    "the-brand-identity": _ExtractorRules(
        accept=(
            _ArtifactRule(r"^/(?:project|projects|article|articles|interview|news)/[a-z0-9][a-z0-9-]+/?$", "identity case detail"),
        ),
        reject=(
            r"^/$",
            r"^/(?:project|projects|articles|interviews|news|industry|categories|search|tag)(?:/)?$",
        ),
    ),
    "the-dieline": _ExtractorRules(
        accept=(
            _ArtifactRule(r"^/blog/(?:\d{4}/\d{1,2}/\d{1,2}/)?[a-z0-9][a-z0-9-]+/?$", "packaging article"),
            _ArtifactRule(r"^/(?:articles|projects)/[a-z0-9][a-z0-9-]+/?$", "packaging case detail"),
        ),
        reject=(
            r"^/$",
            r"^/(?:blog|articles|projects|packaging-design|awards|search|category|tag)(?:/)?$",
        ),
    ),
    "bpando": _ExtractorRules(
        accept=(
            _ArtifactRule(r"^/\d{4}/\d{2}/\d{2}/[a-z0-9][a-z0-9-]+/?$", "identity critique"),
        ),
        reject=(
            r"^/$",
            r"^/(?:brand-identity|packaging|opinion|archive|category|tag|search)(?:/)?$",
        ),
    ),
    "cari": _ExtractorRules(
        accept=(
            _ArtifactRule(r"^/(?:aesthetics|collections|research)/[a-z0-9][a-z0-9-]+/?$", "aesthetic dossier"),
        ),
        reject=(
            r"^/$",
            r"^/(?:aesthetics|collections|research|archive|resources|search)(?:/)?$",
        ),
    ),
    "duke-ad-access": _ExtractorRules(
        accept=(
            _ArtifactRule(r"^/dc/adaccess/[a-z0-9_-]+/?$", "archival ad artifact"),
            _ArtifactRule(r"^/digitalcollections/adaccess_[a-z0-9_-]+/?$", "archival ad artifact"),
        ),
        reject=(
            r"^/$",
            r"^/dc/adaccess/?$",
            r"^/(?:catalog|digitalcollections)(?:/)?$",
            r"^/(?:search|browse)(?:/.*)?$",
        ),
    ),
    "branding-style-guides": _ExtractorRules(
        accept=(
            _ArtifactRule(r"^/(?:guide|guides|brand|brands)/[a-z0-9][a-z0-9-]+/?$", "brand guide"),
        ),
        reject=(
            r"^/$",
            r"^/(?:guide|guides|brand|brands|category|search|tag)(?:/)?$",
        ),
    ),
    "land-book": _ExtractorRules(
        accept=(
            _ArtifactRule(r"^/(?:website|websites)/[a-z0-9][a-z0-9-]+/?$", "website showcase"),
        ),
        reject=(
            r"^/$",
            r"^/(?:website|websites|categories|category|collections|search|tag)(?:/)?$",
        ),
    ),
    "godly": _ExtractorRules(
        accept=(
            _ArtifactRule(r"^/(?:website|websites|site)/[a-z0-9][a-z0-9-]+/?$", "website showcase"),
        ),
        reject=(
            r"^/$",
            r"^/(?:website|websites|sites|categories|category|collections|search|tag)(?:/)?$",
        ),
    ),
    "commerce-cream": _ExtractorRules(
        accept=(
            _ArtifactRule(r"^/(?:brand|brands|store|stores|website|websites)/[a-z0-9][a-z0-9-]+/?$", "commerce showcase"),
        ),
        reject=(
            r"^/$",
            r"^/(?:brand|brands|store|stores|website|websites|search|tag)(?:/)?$",
            r"^/(?:categories|category)(?:/.*)?$",
        ),
    ),
    "mobbin": _ExtractorRules(
        accept=(
            _ArtifactRule(r"^/(?:apps|screens|flows)/[a-z0-9][a-z0-9-]+(?:/[a-z0-9][a-z0-9-]+)*?/?$", "product UI artifact"),
        ),
        reject=(
            r"^/$",
            r"^/(?:apps|screens|flows|browse|patterns|search|categories|category)(?:/)?$",
        ),
    ),
    "cargo": _ExtractorRules(
        accept=(
            _ArtifactRule(r"^/(?:site|sites|project|projects)/[a-z0-9][a-z0-9-]+/?$", "portfolio reference"),
            _ArtifactRule(r"^/[a-z0-9][a-z0-9-]+/?$", "portfolio reference"),
        ),
        reject=(
            r"^/$",
            r"^/(?:templates|pricing|features|examples|in-use|sites|gallery|search|about)(?:/)?$",
        ),
    ),
}


def list_sources() -> tuple[Source, ...]:
    """Return the registry in stable London priority order."""

    return SOURCE_REGISTRY


def get_source(slug: str) -> Source:
    try:
        return _REGISTRY_BY_SLUG[slug]
    except KeyError as exc:
        raise KeyError(f"Unknown London source: {slug}") from exc


def source_slug_from_url(url: str) -> str | None:
    host = _host(url)
    if not host:
        return None
    for source in SOURCE_REGISTRY:
        if any(host == domain or host.endswith(f".{domain}") for domain in source.domains):
            return source.slug
    return None


def classify_source_url(url: str, *, title: str = "", source_slug: str | None = None) -> ExtractorDecision:
    """Classify a URL before fetching it.

    The classifier intentionally accepts detail artifacts and rejects galleries,
    feed pages, search results, and other container chrome. It does not fetch the
    network; decisions come from the public registry and source-specific URL
    shapes.
    """

    resolved_slug = source_slug or source_slug_from_url(url)
    if resolved_slug is None:
        return ExtractorDecision(url, None, False, None, "unknown source domain")
    if resolved_slug not in _REGISTRY_BY_SLUG:
        return ExtractorDecision(url, resolved_slug, False, None, "unknown source slug")

    parsed = urlparse(url)
    path = _normalized_path(parsed.path)
    if _looks_like_asset(path):
        return ExtractorDecision(url, resolved_slug, False, None, "asset URL, not a source artifact")

    rules = _EXTRACTOR_RULES[resolved_slug]
    if _matches_any(path, rules.reject):
        return ExtractorDecision(url, resolved_slug, False, None, "gallery or container chrome")

    if _has_global_chrome_shape(path, title):
        return ExtractorDecision(url, resolved_slug, False, None, "gallery or container chrome")

    for rule in rules.accept:
        if re.match(rule.pattern, path, flags=re.IGNORECASE):
            return ExtractorDecision(url, resolved_slug, True, rule.artifact_kind, "showcased work detail")

    return ExtractorDecision(url, resolved_slug, False, None, "not a recognized showcased artifact URL")


def is_showcased_artifact(url: str, *, title: str = "", source_slug: str | None = None) -> bool:
    return classify_source_url(url, title=title, source_slug=source_slug).accepted


def is_gallery_chrome(url: str, *, title: str = "", source_slug: str | None = None) -> bool:
    decision = classify_source_url(url, title=title, source_slug=source_slug)
    return not decision.accepted and "chrome" in decision.reason


def select_extractable_candidates(
    candidates: Iterable[ExtractionCandidate | str],
) -> tuple[ExtractionCandidate, ...]:
    """Filter candidate URLs to extraction-worthy artifacts, preserving order."""

    selected: list[ExtractionCandidate] = []
    seen_urls: set[str] = set()
    for item in candidates:
        candidate = item if isinstance(item, ExtractionCandidate) else ExtractionCandidate(url=item)
        if candidate.url in seen_urls:
            continue
        decision = classify_source_url(
            candidate.url,
            title=candidate.title,
            source_slug=candidate.source_slug,
        )
        if decision.accepted:
            selected.append(candidate)
            seen_urls.add(candidate.url)
    return tuple(selected)


def extract_showcased_artifact(
    candidate: ExtractionCandidate | str,
    html: str,
) -> SourceArtifact | None:
    """Extract an artifact from fixture HTML after URL-level chrome rejection."""

    item = candidate if isinstance(candidate, ExtractionCandidate) else ExtractionCandidate(url=candidate)
    decision = classify_source_url(item.url, title=item.title, source_slug=item.source_slug)
    if not decision.accepted or decision.source_slug is None or decision.artifact_kind is None:
        return None

    title = _extract_title(html) or item.title.strip() or _title_from_url(item.url)
    summary = _extract_summary(html)
    if _looks_like_chrome_title(title):
        return None
    if not summary:
        summary = f"{title} is a selected {decision.artifact_kind} from {get_source(decision.source_slug).name}."

    assets = tuple(_dedupe(_extract_assets(html)))
    tags = tuple(_dedupe((decision.artifact_kind, get_source(decision.source_slug).name, "actual-work-artifact")))
    artifact_id = f"{decision.source_slug}-{sha256(item.url.encode('utf-8')).hexdigest()[:12]}"
    return SourceArtifact(
        artifact_id=artifact_id,
        source_slug=decision.source_slug,
        url=item.url,
        title=title,
        artifact_kind=decision.artifact_kind,
        summary=summary,
        assets=assets,
        tags=tags,
        receipt={
            "kind": "fixture-html-extraction",
            "decision": decision.reason,
            "source": decision.source_slug,
        },
    )


def extract_source_artifacts(
    candidates: Iterable[ExtractionCandidate | str],
    html_by_url: Mapping[str, str],
) -> tuple[SourceArtifact, ...]:
    """Extract deterministic artifacts for accepted candidates with supplied HTML."""

    artifacts: list[SourceArtifact] = []
    seen: set[str] = set()
    for item in candidates:
        candidate = item if isinstance(item, ExtractionCandidate) else ExtractionCandidate(url=item)
        if candidate.url in seen:
            continue
        html = html_by_url.get(candidate.url, "")
        if not html:
            continue
        artifact = extract_showcased_artifact(candidate, html)
        if artifact is not None:
            artifacts.append(artifact)
            seen.add(candidate.url)
    return tuple(artifacts)


def _host(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc or parsed.path.split("/", 1)[0]
    host = host.lower()
    if "@" in host:
        host = host.rsplit("@", 1)[-1]
    if ":" in host:
        host = host.split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def _normalized_path(path: str) -> str:
    normalized = "/" + path.strip("/")
    return normalized.lower() if normalized != "/" else "/"


def _looks_like_asset(path: str) -> bool:
    return path.endswith(_ASSET_EXTENSIONS)


def _matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    return any(re.match(pattern, path, flags=re.IGNORECASE) for pattern in patterns)


def _has_global_chrome_shape(path: str, title: str) -> bool:
    segments = tuple(segment for segment in path.strip("/").split("/") if segment)
    if not segments:
        return True
    if len(segments) == 1 and segments[0] in _GLOBAL_CHROME_SEGMENTS:
        return True
    if len(segments) >= 2 and segments[-1] in _GLOBAL_CHROME_SEGMENTS:
        return True

    normalized_title = title.strip().lower()
    if normalized_title and any(hint == normalized_title or normalized_title.startswith(f"{hint}:") for hint in _GLOBAL_CHROME_TITLE_HINTS):
        return True
    return False


def _extract_title(html: str) -> str:
    patterns = (
        r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)["\']',
        r'<meta\s+content=["\']([^"\']+)["\']\s+property=["\']og:title["\']',
        r"<h1[^>]*>(.*?)</h1>",
        r"<title[^>]*>(.*?)</title>",
    )
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return _strip_html(match.group(1))
    return ""


def _extract_summary(html: str) -> str:
    for pattern in (
        r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']',
        r'<meta\s+content=["\']([^"\']+)["\']\s+name=["\']description["\']',
    ):
        match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return _strip_html(match.group(1))[:420]

    paragraphs = [_strip_html(match) for match in re.findall(r"<p[^>]*>(.*?)</p>", html, flags=re.IGNORECASE | re.DOTALL)]
    meaningful = [paragraph for paragraph in paragraphs if len(paragraph.split()) >= 7]
    return " ".join(meaningful[:2])[:420]


def _extract_assets(html: str) -> list[str]:
    assets: list[str] = []
    for pattern in (
        r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
        r'<meta\s+content=["\']([^"\']+)["\']\s+property=["\']og:image["\']',
        r'<img[^>]+src=["\']([^"\']+)["\']',
    ):
        assets.extend(re.findall(pattern, html, flags=re.IGNORECASE | re.DOTALL))
    blocked = (".css", ".js", ".json", ".xml", ".ico")
    return [asset.strip() for asset in assets if asset.strip() and not urlparse(asset).path.lower().endswith(blocked)]


def _strip_html(value: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", value)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _looks_like_chrome_title(title: str) -> bool:
    normalized = title.strip().lower()
    return any(normalized == hint or normalized.startswith(f"{hint}:") for hint in _GLOBAL_CHROME_TITLE_HINTS)


def _title_from_url(url: str) -> str:
    path = _normalized_path(urlparse(url).path)
    parts = [part for part in path.strip("/").split("/") if part]
    return (parts[-1].replace("-", " ").replace("_", " ").title() if parts else "Untitled source artifact")


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return tuple(output)
