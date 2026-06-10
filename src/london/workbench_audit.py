from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote


PUBLIC_ZONES = {"default_public", "public_folded_summary", "public_folded_body"}
AUDIT_ZONES = {"audit_body"}
USER_FACING_ATTRS = {"alt", "aria-label", "aria-description", "title", "data-copy", "placeholder", "value"}
LOCAL_MEDIA_ATTRS = {"src", "poster", "data-lightbox-src"}
LOCAL_MEDIA_TAGS = {"audio", "button", "img", "source", "video"}
BLOCK_TAGS = {"p", "dd", "figcaption", "blockquote", "li"}
SKIP_TAGS = {"script", "style"}

HARNESS_TOKENS = (
    "scripted-local",
    "claude_cli_print",
    "offline-template-preview",
    "generated_live",
    "receipt-recorded",
    "request_config",
    "asset_sha256",
    "sha256",
    "manual_prompt",
    "manual-prompt",
    "fallback",
    "fixture",
    "FakeDirector",
    "Telemetry not captured",
    "Private brief context",
    "Private London rationale",
    "Allowed visible words",
    "Create one text-free",
    "TELEMETRY_UNAVAILABLE",
    "CLAIM_OK",
    "CLAIM_UNVERIFIED",
    "DEAD_ENGINE",
    "THIN_GROUNDING",
    "ROUTES_TOO_NEAR",
    "BRAIN QUERIES // TRACE",
    "CLAIM INTEGRITY // AUDIT",
    "SOURCES MATRIX",
    "OUTPUT MANIFEST",
    "weighted from 5 objective checks",
    "Not scored",
    "No transcript for this engine mode",
    "No transcript for this mode",
    "No source trail for this mode",
)

PUBLIC_MACHINERY_PATTERNS = (
    r"\bn/a\b",
    r"\bprovider\b",
    r"\bdebug\b",
    r"\btelemetry\b",
    r"\btranscript\b",
    r"\bgrounding unavailable\b",
    r"\bMCP\b",
    r"\bengine mode\b",
    r"\blocal proof\b",
    r"\bobject proof\b",
    r"\bvisual proof\b",
    r"\bproof\s*:",
    r"\bproof status\b",
    r"\bprovider-backed artifact receipt\b",
    r"\bLive Artifacts\b",
    r"\blive evidence note\b",
    r"\bgenerated work\b",
    r"\blocal assets are proof\b",
    r"\bEvery required region is filled at honest cardinality\b",
    r"\bEvery required region filled at honest cardinality\b",
    r"\bFont Lab range\s*(?::|—|–|-)\s*local fonts allowed\b",
    r"\bsub-score\b",
    r"\bquality score\b",
    r"\b[A-Z]+(?:_[A-Z]+)+\b",
)

EXACT_PUBLIC_MACHINERY = ("RUN DETAILS", "Run Details")

DASH_TOKENS = ("—", "&mdash;", "&#8212;", "&#x2014;", "--")

AUDIT_CLASS_MARKERS = (
    "receipt",
    "source-ref",
    "prompt-detail",
    "drawer",
    "copy-block",
    "command-center-details",
    "decision-fold",
)
AUDIT_DATA_MARKERS = (
    "receipt",
    "source",
    "evidence",
    "provider",
    "prompt",
    "debug",
    "audit",
    "run",
)


@dataclass(frozen=True)
class TextSurface:
    zone: str
    source: str
    text: str
    tag: str
    section: str
    line: int
    column: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "zone": self.zone,
            "source": self.source,
            "text": self.text,
            "tag": self.tag,
            "section": self.section,
            "line": self.line,
            "column": self.column,
        }


@dataclass(frozen=True)
class ScanHit:
    token: str
    kind: str
    surface: TextSurface

    def as_dict(self) -> dict[str, Any]:
        data = self.surface.as_dict()
        data.update({"token": self.token, "kind": self.kind})
        return data


@dataclass(frozen=True)
class LongProseHit:
    words: int
    chars: int
    surface: TextSurface

    def as_dict(self) -> dict[str, Any]:
        data = self.surface.as_dict()
        data.update({"words": self.words, "chars": self.chars})
        return data


@dataclass(frozen=True)
class MediaHit:
    zone: str
    source: str
    src: str
    tag: str
    section: str
    line: int
    column: int
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "zone": self.zone,
            "source": self.source,
            "src": self.src,
            "tag": self.tag,
            "section": self.section,
            "line": self.line,
            "column": self.column,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class WorkbenchAudit:
    surfaces: list[TextSurface]
    hits: list[ScanHit]
    long_prose: list[LongProseHit]
    media_hits: list[MediaHit]

    @property
    def public_hits(self) -> list[ScanHit]:
        return [hit for hit in self.hits if hit.surface.zone in PUBLIC_ZONES]

    @property
    def public_long_prose(self) -> list[LongProseHit]:
        return [hit for hit in self.long_prose if hit.surface.zone in PUBLIC_ZONES]

    @property
    def public_media_hits(self) -> list[MediaHit]:
        return [hit for hit in self.media_hits if hit.zone in PUBLIC_ZONES]

    @property
    def failed(self) -> bool:
        return bool(self.public_hits or self.public_long_prose or self.public_media_hits)

    def as_dict(self) -> dict[str, Any]:
        return {
            "surface_count": len(self.surfaces),
            "public_hit_count": len(self.public_hits),
            "public_long_prose_count": len(self.public_long_prose),
            "failed": self.failed,
            "surfaces": [surface.as_dict() for surface in self.surfaces],
            "hits": [hit.as_dict() for hit in self.hits],
            "long_prose": [hit.as_dict() for hit in self.long_prose],
            "media_hits": [hit.as_dict() for hit in self.media_hits],
        }


@dataclass
class _TagContext:
    tag: str
    element_id: str
    class_name: str


@dataclass
class _DetailsContext:
    audit: bool


@dataclass
class _BlockContext:
    tag: str
    zone: str
    section: str
    line: int
    column: int
    parts: list[str]


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip()


def audit_html(
    markup: str,
    *,
    html_path: Path | None = None,
    max_public_words: int = 85,
    max_public_chars: int = 640,
) -> WorkbenchAudit:
    parser = _WorkbenchAuditParser(max_public_words=max_public_words, max_public_chars=max_public_chars)
    parser.feed(markup)
    parser.close()
    surfaces = parser.surfaces
    return WorkbenchAudit(
        surfaces=surfaces,
        hits=_scan_surfaces(surfaces),
        long_prose=parser.long_prose,
        media_hits=_scan_media(parser.media_surfaces, html_path=html_path),
    )


def default_public_copy(markup: str) -> str:
    audit = audit_html(markup)
    return normalize_space(" ".join(surface.text for surface in audit.surfaces if surface.zone in PUBLIC_ZONES))


def write_audit_packet(audit: WorkbenchAudit, out_dir: Path, *, html_path: Path | None = None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    inventory = [surface.as_dict() for surface in audit.surfaces]
    (out_dir / "rendered-text-inventory.json").write_text(
        json.dumps(inventory, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (out_dir / "rendered-text-inventory.md").write_text(_inventory_markdown(audit.surfaces), encoding="utf-8")
    (out_dir / "humanize-scan.json").write_text(
        json.dumps(
            {
                "html_path": str(html_path) if html_path else None,
                "failed": audit.failed,
                "public_hit_count": len(audit.public_hits),
                "public_long_prose_count": len(audit.public_long_prose),
                "public_media_hit_count": len(audit.public_media_hits),
                "hits": [hit.as_dict() for hit in audit.hits],
                "media_hits": [hit.as_dict() for hit in audit.media_hits],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (out_dir / "long-prose-audit.md").write_text(_long_prose_markdown(audit.public_long_prose), encoding="utf-8")
    (out_dir / "media-audit.md").write_text(_media_markdown(audit.public_media_hits), encoding="utf-8")
    (out_dir / "rubric-failure-log.md").write_text(_failure_markdown(audit), encoding="utf-8")


def _scan_surfaces(surfaces: Iterable[TextSurface]) -> list[ScanHit]:
    hits: list[ScanHit] = []
    for surface in surfaces:
        text = surface.text
        if surface.zone not in PUBLIC_ZONES:
            continue
        for token in DASH_TOKENS:
            if token in text:
                hits.append(ScanHit(token=token, kind="dash", surface=surface))
        lowered = text.lower()
        for token in HARNESS_TOKENS:
            if token.lower() in lowered:
                hits.append(ScanHit(token=token, kind="harness-token", surface=surface))
        for token in EXACT_PUBLIC_MACHINERY:
            if token in text:
                hits.append(ScanHit(token=token, kind="public-machinery", surface=surface))
        for pattern in PUBLIC_MACHINERY_PATTERNS:
            if re.search(pattern, text, flags=re.I):
                hits.append(ScanHit(token=pattern, kind="public-machinery", surface=surface))
    return hits


def _scan_media(media_refs: Iterable[MediaHit], *, html_path: Path | None) -> list[MediaHit]:
    if html_path is None:
        return []
    html_dir = html_path.parent
    hits: list[MediaHit] = []
    for ref in media_refs:
        src = ref.src.strip()
        if not src or _is_remote_or_embedded_media(src):
            continue
        src_path = unquote(src.split("#", 1)[0].split("?", 1)[0])
        candidate = Path(src_path) if src_path.startswith("/") else html_dir / src_path
        if candidate.exists():
            continue
        hits.append(
            MediaHit(
                zone=ref.zone,
                source=ref.source,
                src=ref.src,
                tag=ref.tag,
                section=ref.section,
                line=ref.line,
                column=ref.column,
                reason=f"missing local media: {candidate}",
            )
        )
    return hits


def _is_remote_or_embedded_media(src: str) -> bool:
    lowered = src.lower()
    return lowered.startswith(("http://", "https://", "data:", "blob:", "#", "mailto:", "javascript:"))


class _WorkbenchAuditParser(HTMLParser):
    def __init__(self, *, max_public_words: int, max_public_chars: int) -> None:
        super().__init__(convert_charrefs=False)
        self.max_public_words = max_public_words
        self.max_public_chars = max_public_chars
        self.skip_depth = 0
        self.summary_depth = 0
        self.tags: list[_TagContext] = []
        self.details: list[_DetailsContext] = []
        self.blocks: list[_BlockContext] = []
        self.surfaces: list[TextSurface] = []
        self.long_prose: list[LongProseHit] = []
        self.media_surfaces: list[MediaHit] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name: value or "" for name, value in attrs}
        class_name = attrs_dict.get("class", "")
        element_id = attrs_dict.get("id", "")
        self.tags.append(_TagContext(tag=tag, element_id=element_id, class_name=class_name))
        if tag in SKIP_TAGS:
            self.skip_depth += 1
        if tag == "details":
            self.details.append(_DetailsContext(audit=_is_audit_details(attrs_dict)))
        if tag == "summary":
            self.summary_depth += 1
        if tag in BLOCK_TAGS:
            line, column = self.getpos()
            self.blocks.append(
                _BlockContext(
                    tag=tag,
                    zone=self._zone(),
                    section=self._section(),
                    line=line,
                    column=column,
                    parts=[],
                )
            )
        if self.skip_depth == 0:
            for name, value in attrs:
                if value and name in USER_FACING_ATTRS:
                    self._add_surface(value, source=f"attr:{name}", tag=tag)
                if value and tag in LOCAL_MEDIA_TAGS and name in LOCAL_MEDIA_ATTRS:
                    self._add_media(value, source=f"attr:{name}", tag=tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in BLOCK_TAGS:
            self._close_block(tag)
        if tag == "summary" and self.summary_depth:
            self.summary_depth -= 1
        if tag == "details" and self.details:
            self.details.pop()
        if tag in SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
        for index in range(len(self.tags) - 1, -1, -1):
            if self.tags[index].tag == tag:
                del self.tags[index:]
                break

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = normalize_space(data)
        if not text:
            return
        self._add_surface(text, source="text", tag=self.tags[-1].tag if self.tags else "")
        if self.blocks:
            self.blocks[-1].parts.append(text)

    def _add_surface(self, value: str, *, source: str, tag: str) -> None:
        text = normalize_space(value)
        if not text:
            return
        line, column = self.getpos()
        self.surfaces.append(
            TextSurface(
                zone=self._zone(),
                source=source,
                text=text,
                tag=tag,
                section=self._section(),
                line=line,
                column=column,
            )
        )

    def _add_media(self, value: str, *, source: str, tag: str) -> None:
        src = normalize_space(value)
        if not src:
            return
        line, column = self.getpos()
        self.media_surfaces.append(
            MediaHit(
                zone=self._zone(),
                source=source,
                src=src,
                tag=tag,
                section=self._section(),
                line=line,
                column=column,
                reason="unchecked",
            )
        )

    def _zone(self) -> str:
        if self.skip_depth:
            return "internal_script_style"
        if self.summary_depth:
            return "public_folded_summary"
        if not self.details:
            return "default_public"
        if self.details[-1].audit:
            return "audit_body"
        return "public_folded_body"

    def _section(self) -> str:
        for context in reversed(self.tags):
            if context.element_id:
                return context.element_id
        return "document"

    def _close_block(self, tag: str) -> None:
        for index in range(len(self.blocks) - 1, -1, -1):
            block = self.blocks[index]
            if block.tag != tag:
                continue
            del self.blocks[index:]
            text = normalize_space(" ".join(block.parts))
            if not text:
                return
            words = len(re.findall(r"\b\S+\b", text))
            chars = len(text)
            if block.zone in PUBLIC_ZONES and (words > self.max_public_words or chars > self.max_public_chars):
                self.long_prose.append(
                    LongProseHit(
                        words=words,
                        chars=chars,
                        surface=TextSurface(
                            zone=block.zone,
                            source="block-text",
                            text=text,
                            tag=block.tag,
                            section=block.section,
                            line=block.line,
                            column=block.column,
                        ),
                    )
                )
            return


def _is_audit_details(attrs: dict[str, str]) -> bool:
    class_name = attrs.get("class", "").lower()
    if any(marker in class_name for marker in AUDIT_CLASS_MARKERS):
        return True
    data_values = " ".join(value for name, value in attrs.items() if name.startswith("data-")).lower()
    return any(marker in data_values for marker in AUDIT_DATA_MARKERS)


def _inventory_markdown(surfaces: list[TextSurface]) -> str:
    lines = [
        "# Rendered Text Inventory",
        "",
        "| Zone | Source | Section | Text |",
        "| --- | --- | --- | --- |",
    ]
    for surface in surfaces:
        lines.append(
            f"| {surface.zone} | {surface.source} | {surface.section} | {_md_cell(_clip(surface.text, 180))} |"
        )
    return "\n".join(lines) + "\n"


def _long_prose_markdown(hits: list[LongProseHit]) -> str:
    lines = [
        "# Long Prose Audit",
        "",
        "| Zone | Section | Words | Chars | Text |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    if not hits:
        lines.append("| - | - | 0 | 0 | No public long-prose hits. |")
    for hit in hits:
        surface = hit.surface
        lines.append(
            f"| {surface.zone} | {surface.section} | {hit.words} | {hit.chars} | {_md_cell(_clip(surface.text, 220))} |"
        )
    return "\n".join(lines) + "\n"


def _failure_markdown(audit: WorkbenchAudit) -> str:
    lines = [
        "# Rubric Failure Log",
        "",
        f"- Public humanize hits: {len(audit.public_hits)}",
        f"- Public long-prose hits: {len(audit.public_long_prose)}",
        f"- Public media hits: {len(audit.public_media_hits)}",
        f"- Gate status: {'Patch public surface' if audit.failed else 'No public surface gate failures'}",
        "",
    ]
    if audit.public_hits:
        lines.extend(["## Humanize Hits", "", "| Kind | Token | Zone | Section | Text |", "| --- | --- | --- | --- | --- |"])
        for hit in audit.public_hits:
            surface = hit.surface
            lines.append(
                f"| {hit.kind} | {_md_cell(hit.token)} | {surface.zone} | {surface.section} | {_md_cell(_clip(surface.text, 180))} |"
            )
        lines.append("")
    if audit.public_long_prose:
        lines.extend(["## Long Prose Hits", ""])
        lines.append("See `long-prose-audit.md` for block-level detail.")
    if audit.public_media_hits:
        lines.extend(["", "## Media Hits", "", "| Zone | Section | Source | Src | Reason |", "| --- | --- | --- | --- | --- |"])
        for hit in audit.public_media_hits:
            lines.append(
                f"| {hit.zone} | {hit.section} | {hit.source} | {_md_cell(_clip(hit.src, 180))} | {_md_cell(_clip(hit.reason, 220))} |"
            )
    if not audit.failed:
        lines.append("No public-surface failures found by the reusable Workbench audit.")
    return "\n".join(lines) + "\n"


def _media_markdown(hits: list[MediaHit]) -> str:
    lines = [
        "# Media Audit",
        "",
        "| Zone | Section | Source | Src | Reason |",
        "| --- | --- | --- | --- | --- |",
    ]
    if not hits:
        lines.append("| - | - | - | - | No missing public media references. |")
    for hit in hits:
        lines.append(
            f"| {hit.zone} | {hit.section} | {hit.source} | {_md_cell(_clip(hit.src, 180))} | {_md_cell(_clip(hit.reason, 220))} |"
        )
    return "\n".join(lines) + "\n"


def _clip(value: str, max_chars: int) -> str:
    text = normalize_space(value)
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 3].rstrip()}..."


def _md_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
