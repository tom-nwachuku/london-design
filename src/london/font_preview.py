"""Font preview resolution for fidelity-aware London surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import re
from typing import Any, Mapping, Sequence
from urllib.parse import quote

from .text import display_text

FONT_PREVIEW_STATUSES = (
    "actual_loaded",
    "source_loaded",
    "fallback_approximation",
    "reference_capture",
    "reference_only",
)
FONT_PREVIEW_DELIVERIES = ("local_asset", "remote_font_file", "system_fallback", "reference_image", "reference_only")

_ALLOWED_FONT_EXTENSIONS = {
    ".otf": "opentype",
    ".ttf": "truetype",
    ".woff": "woff",
    ".woff2": "woff2",
}
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
_FONTSOURCE_WOFF2_RE = re.compile(r"^https://cdn\.jsdelivr\.net/fontsource/fonts/[A-Za-z0-9-]+@(?:latest|[0-9][A-Za-z0-9.-]*)/[A-Za-z0-9-]+\.woff2$")
_ALLOWED_REMOTE_FONT_HOSTS = ("https://cdn.jsdelivr.net/fontsource/fonts/",)


@dataclass(frozen=True)
class FontSourceMatch:
    family: str
    css_family: str
    source_label: str
    license_note: str
    source_url: str
    font_file_href: str
    fallback_stack: str = "system-ui, sans-serif"

    @property
    def css_stack(self) -> str:
        return f"{css_font_string(self.css_family)}, {self.fallback_stack}"


class FontsourceAdapter:
    """Small deterministic adapter for public Fontsource families London commonly names."""

    _FAMILIES = {
        "spacegrotesk": ("space-grotesk", "Space Grotesk", "sans-serif"),
        "geistmono": ("geist-mono", "Geist Mono", "monospace"),
        "inter": ("inter", "Inter", "sans-serif"),
        "ibmplexmono": ("ibm-plex-mono", "IBM Plex Mono", "monospace"),
        "nunito": ("nunito", "Nunito", "sans-serif"),
        "nunitosans": ("nunito-sans", "Nunito Sans", "sans-serif"),
        "publicsans": ("public-sans", "Public Sans", "sans-serif"),
        "sourceserif4": ("source-serif-4", "Source Serif 4", "serif"),
    }

    @classmethod
    def resolve(cls, family: Any, *, weight: int = 500) -> FontSourceMatch | None:
        key = _canonical_font_name(family)
        if key not in cls._FAMILIES:
            return None
        slug, css_family, fallback = cls._FAMILIES[key]
        href = f"https://cdn.jsdelivr.net/fontsource/fonts/{slug}@latest/latin-{weight}-normal.woff2"
        return FontSourceMatch(
            family=css_family,
            css_family=css_family,
            source_label="Fontsource public font",
            license_note="Open font served from Fontsource/jsDelivr; verify in browser before treating as loaded.",
            source_url=f"https://fontsource.org/fonts/{slug}",
            font_file_href=href,
            fallback_stack=fallback,
        )


class GoogleFontsAdapter:
    """No-key Google Fonts CSS2 URL resolver for known public families."""

    _FAMILIES = {
        "spacegrotesk": "Space Grotesk",
        "geistmono": "Geist Mono",
        "inter": "Inter",
        "ibmplexmono": "IBM Plex Mono",
        "nunito": "Nunito",
        "nunitosans": "Nunito Sans",
        "publicsans": "Public Sans",
        "sourceserif4": "Source Serif 4",
    }

    @classmethod
    def resolve(cls, family: Any) -> FontSourceMatch | None:
        key = _canonical_font_name(family)
        css_family = cls._FAMILIES.get(key)
        if not css_family:
            return None
        family_param = quote(css_family.replace(" ", "+"), safe="+")
        return FontSourceMatch(
            family=css_family,
            css_family=css_family,
            source_label="Google Fonts CSS2",
            license_note="Public Google Fonts CSS2 route; verify in browser before treating as loaded.",
            source_url=f"https://fonts.google.com/specimen/{family_param}",
            font_file_href=f"https://fonts.googleapis.com/css2?family={family_param}:wght@500;700&display=swap",
        )


class FontshareAdapter:
    """Known Fontshare CSS endpoint resolver for London-favored public families."""

    _FAMILIES = {
        "satoshi": ("satoshi", "Satoshi"),
        "clashdisplay": ("clash-display", "Clash Display"),
        "switzer": ("switzer", "Switzer"),
        "cabinetgrotesk": ("cabinet-grotesk", "Cabinet Grotesk"),
        "generalsans": ("general-sans", "General Sans"),
        "bespokeslab": ("bespoke-slab", "Bespoke Slab"),
    }

    @classmethod
    def resolve(cls, family: Any) -> FontSourceMatch | None:
        key = _canonical_font_name(family)
        if key not in cls._FAMILIES:
            return None
        slug, css_family = cls._FAMILIES[key]
        return FontSourceMatch(
            family=css_family,
            css_family=css_family,
            source_label="Fontshare public CSS",
            license_note="Fontshare public CSS endpoint; verify license/source posture before bundling binaries.",
            source_url=f"https://fontshare.com/fonts/{slug}",
            font_file_href=f"https://api.fontshare.com/v2/css?f[]={slug}@400,500,700&display=swap",
        )


@dataclass(frozen=True)
class FontPreviewResolution:
    status: str
    delivery: str
    rendered_family: str
    source_label: str
    license_note: str
    asset_href: str = ""
    css_stack: str = ""
    reference_preview: Mapping[str, Any] | None = None
    display_state: str = ""
    font_file_href: str = ""
    css_hrefs: tuple[str, ...] = ()
    role_css_stacks: Mapping[str, str] | None = None

    @property
    def status_label(self) -> str:
        if self.status == "actual_loaded":
            return "Loaded font"
        if self.status == "source_loaded":
            return "Source font loaded"
        if self.status in {"reference_capture", "reference_only"}:
            if self.reference_preview:
                return "Reference specimen"
            return "Reference needed"
        return "Approximation"

    @property
    def is_actual_loaded(self) -> bool:
        return self.status == "actual_loaded" and self.delivery == "local_asset" and bool(self.asset_href)

    @property
    def is_source_loaded(self) -> bool:
        return self.status == "source_loaded" and self.delivery == "remote_font_file" and bool(self.font_file_href)


def safe_font_asset_href(value: Any) -> str:
    """Return a safe relative local font asset href, or ``""`` if it is not local."""

    href = display_text(value)
    if not href:
        return ""
    if href.startswith(("/", "\\", "//")) or _SCHEME_RE.match(href):
        return ""
    if any(token in href for token in ("\\", "'", '"', "<", ">", "\n", "\r", "\t", "?", "#")):
        return ""

    path = PurePosixPath(href)
    if ".." in path.parts:
        return ""
    if path.suffix.lower() not in _ALLOWED_FONT_EXTENSIONS:
        return ""
    return href


def css_font_string(value: str) -> str:
    safe = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")
    return f'"{safe}"'


def safe_font_stack(value: Any, *, fallback: str = "system-ui, sans-serif") -> str:
    stack = display_text(value, fallback=fallback)
    lowered = stack.lower()
    if any(token in stack for token in ("{", "}", ";", "<", ">")):
        return fallback
    if "@import" in lowered or "url(" in lowered:
        return fallback
    return stack


def safe_remote_font_href(value: Any) -> str:
    href = display_text(value)
    if not href or any(token in href for token in ('"', "'", "<", ">", "\n", "\r", "\t")):
        return ""
    if href.startswith(_ALLOWED_REMOTE_FONT_HOSTS) and _FONTSOURCE_WOFF2_RE.match(href):
        return href
    return ""


def _canonical_font_name(value: Any) -> str:
    return "".join(char for char in display_text(value).lower() if char.isalnum())


def _source_match_for_family(value: Any) -> FontSourceMatch | None:
    # Prefer direct Fontsource font-file URLs for pack-stable @font-face rules. Google and
    # Fontshare adapters remain exposed/tested for resolver coverage and future source choice.
    return FontsourceAdapter.resolve(value) or FontshareAdapter.resolve(value)


def _source_matches_for_option(option: Mapping[str, Any]) -> dict[str, FontSourceMatch]:
    roles = {
        "headline": option.get("headline_font") or option.get("name"),
        "body": option.get("body_font") or option.get("name"),
        "label": option.get("label_font") or option.get("name"),
    }
    matches: dict[str, FontSourceMatch] = {}
    for role, family in roles.items():
        match = _source_match_for_family(family)
        if match and safe_remote_font_href(match.font_file_href):
            matches[role] = match
    return matches


def resolve_font_preview(option: Mapping[str, Any]) -> FontPreviewResolution:
    """Resolve one font option into an honest rendered-preview state.

    Missing metadata defaults conservatively by tier. The only way to resolve to
    ``actual_loaded`` is a local-asset delivery with a safe relative ``asset_href``;
    model-authored import hints never affect runtime CSS.
    """

    tier = display_text(option.get("tier"), fallback="safe_local")
    fallback_stack = safe_font_stack(option.get("fallback_stack"))
    preview = option.get("font_preview") if isinstance(option.get("font_preview"), Mapping) else {}

    raw_status = display_text(preview.get("status")) if isinstance(preview, Mapping) else ""
    raw_delivery = display_text(preview.get("delivery")) if isinstance(preview, Mapping) else ""
    asset_href = safe_font_asset_href(preview.get("asset_href") if isinstance(preview, Mapping) else "")
    rendered_family = display_text(
        preview.get("rendered_family") if isinstance(preview, Mapping) else "",
        fallback=display_text(option.get("headline_font") or option.get("name"), fallback=fallback_stack),
    )
    source_label = display_text(preview.get("source_label") if isinstance(preview, Mapping) else "")
    license_note = display_text(preview.get("license_note") if isinstance(preview, Mapping) else "")
    reference_preview = (
        dict(preview.get("reference_preview"))
        if isinstance(preview, Mapping) and isinstance(preview.get("reference_preview"), Mapping)
        else None
    )
    raw_display_state = display_text(preview.get("display_state") if isinstance(preview, Mapping) else "")
    raw_font_file_href = safe_remote_font_href(preview.get("font_file_href") if isinstance(preview, Mapping) else "")
    raw_css_hrefs = tuple(
        href
        for href in (
            safe_remote_font_href(item)
            for item in (
                preview.get("css_hrefs", [])
                if isinstance(preview, Mapping) and isinstance(preview.get("css_hrefs"), Sequence) and not isinstance(preview.get("css_hrefs"), (str, bytes, bytearray))
                else []
            )
        )
        if href
    )

    if raw_status == "actual_loaded" and raw_delivery == "local_asset" and asset_href:
        family = rendered_family or display_text(option.get("headline_font") or option.get("name"), fallback="London local font")
        source = source_label or asset_href
        note = license_note or "Local font asset supplied with this pack."
        return FontPreviewResolution(
            status="actual_loaded",
            delivery="local_asset",
            rendered_family=family,
            source_label=source,
            license_note=note,
            asset_href=asset_href,
            css_stack=f"{css_font_string(family)}, {fallback_stack}",
            display_state=raw_display_state or "bundled_loaded",
        )

    if raw_status == "source_loaded" and raw_delivery == "remote_font_file" and raw_font_file_href:
        family = rendered_family or display_text(option.get("headline_font") or option.get("name"), fallback="London source font")
        return FontPreviewResolution(
            status="source_loaded",
            delivery="remote_font_file",
            rendered_family=family,
            source_label=source_label or "Public source font",
            license_note=license_note or "Remote font source; verify in browser.",
            font_file_href=raw_font_file_href,
            css_hrefs=raw_css_hrefs or (raw_font_file_href,),
            css_stack=f"{css_font_string(family)}, {fallback_stack}",
            display_state=raw_display_state or "source_loaded",
        )

    source_matches = _source_matches_for_option(option)
    headline_match = source_matches.get("headline")
    if tier == "open_public" and headline_match:
        role_stacks = {
            role: match.css_stack
            for role, match in source_matches.items()
        }
        hrefs = tuple(dict.fromkeys(match.font_file_href for match in source_matches.values()))
        families = ", ".join(dict.fromkeys(match.css_family for match in source_matches.values()))
        return FontPreviewResolution(
            status="source_loaded",
            delivery="remote_font_file",
            rendered_family=headline_match.css_family,
            source_label=f"{headline_match.source_label}: {families}",
            license_note=headline_match.license_note,
            font_file_href=headline_match.font_file_href,
            css_hrefs=hrefs,
            css_stack=headline_match.css_stack,
            role_css_stacks=role_stacks,
            display_state="source_loaded",
        )

    if tier == "premium_inspiration" or raw_status in {"reference_only", "reference_capture"} or raw_delivery in {"reference_only", "reference_image"}:
        family = rendered_family or display_text(option.get("headline_font") or option.get("name"), fallback="Reference typeface")
        source = source_label or "Source/license required"
        note = license_note or "Reference only until a licensed local asset is supplied."
        status = "reference_capture" if _reference_preview_has_specimen_image(reference_preview) else "reference_only"
        delivery = "reference_image" if status == "reference_capture" else "reference_only"
        return FontPreviewResolution(
            status=status,
            delivery=delivery,
            rendered_family=family,
            source_label=source,
            license_note=note,
            css_stack=fallback_stack,
            reference_preview=reference_preview,
            display_state=raw_display_state or status,
        )

    family = rendered_family or fallback_stack
    if tier == "safe_local":
        source = source_label or "Portable system fallback"
        note = license_note or "Rendered with the safe local stack; no external font asset is loaded."
    else:
        source = source_label or "Public font direction not bundled"
        note = license_note or "Approximation only until a local font asset is supplied."
    return FontPreviewResolution(
        status="fallback_approximation",
        delivery="system_fallback",
        rendered_family=family,
        source_label=source,
        license_note=note,
        css_stack=fallback_stack,
        display_state="fallback_approximation",
    )


def _reference_preview_has_specimen_image(reference_preview: Mapping[str, Any] | None) -> bool:
    if not isinstance(reference_preview, Mapping):
        return False
    src = display_text(reference_preview.get("specimen_image_src") or reference_preview.get("image_src"))
    return bool(src and not src.startswith(("/", "\\", "file:")) and all(token not in src for token in ('"', "'", "<", ">", "\n", "\r")))


def _safe_font_asset_prefix(value: str) -> str:
    if value == "":
        return ""
    if value == "../":
        return value
    return ""


def font_face_css_for_groups(groups: Sequence[Mapping[str, Any]], *, asset_href_prefix: str = "") -> str:
    """Emit safe @font-face CSS for actual-loaded local assets and verified public font files."""

    rules: list[str] = []
    seen: set[tuple[str, str]] = set()
    prefix = _safe_font_asset_prefix(asset_href_prefix)
    for group in groups:
        options = group.get("options")
        if not isinstance(options, Sequence) or isinstance(options, (str, bytes, bytearray)):
            continue
        for option in options:
            if not isinstance(option, Mapping):
                continue
            preview = resolve_font_preview(option)
            if preview.is_actual_loaded:
                key = (preview.rendered_family, preview.asset_href)
                if key in seen:
                    continue
                seen.add(key)
                fmt = _ALLOWED_FONT_EXTENSIONS.get(PurePosixPath(preview.asset_href).suffix.lower())
                format_hint = f" format({css_font_string(fmt)})" if fmt else ""
                asset_href = f"{prefix}{preview.asset_href}"
                rules.append(
                    f"""
      @font-face {{
        font-family: {css_font_string(preview.rendered_family)};
        src: url({css_font_string(asset_href)}){format_hint};
        font-display: swap;
      }}"""
                )
                continue
            if preview.is_source_loaded:
                source_matches = _source_matches_for_option(option)
                if source_matches:
                    for match in source_matches.values():
                        href = safe_remote_font_href(match.font_file_href)
                        if not href:
                            continue
                        key = (match.css_family, href)
                        if key in seen:
                            continue
                        seen.add(key)
                        rules.append(_remote_font_face_rule(match.css_family, href))
                else:
                    key = (preview.rendered_family, preview.font_file_href)
                    if key not in seen and safe_remote_font_href(preview.font_file_href):
                        seen.add(key)
                        rules.append(_remote_font_face_rule(preview.rendered_family, preview.font_file_href))
    return "".join(rules)


def _remote_font_face_rule(family: str, href: str) -> str:
    return f"""
      @font-face {{
        font-family: {css_font_string(family)};
        src: url({css_font_string(href)}) format("woff2");
        font-display: swap;
      }}"""
