"""Bundled Type Shelf resolver for launch-grade font proof."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
from importlib.resources import files
import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .assets import pack_routes
from .errors import LondonError
from .route_refs import resolve_route_ref
from .text import display_text


class TypeShelfError(LondonError):
    """Raised when a bundled type shelf request cannot be resolved safely."""


@dataclass(frozen=True)
class TypeShelfEntry:
    id: str
    family: str
    ring: str
    source_name: str
    source_url: str
    license_name: str
    license_url: str
    license_checked_at: str
    version_or_import_ref: str
    asset_path: str
    asset_sha256: str
    formats: tuple[str, ...]
    weights_or_axes: tuple[str, ...]
    style_tags: tuple[str, ...]
    best_for: str
    avoid_when: str
    pairings: tuple[str, ...]
    reference_only: bool
    reference_preview: Mapping[str, Any] | None
    notes: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "TypeShelfEntry":
        return cls(
            id=display_text(data.get("id")),
            family=display_text(data.get("family")),
            ring=display_text(data.get("ring")),
            source_name=display_text(data.get("source_name")),
            source_url=display_text(data.get("source_url")),
            license_name=display_text(data.get("license_name")),
            license_url=display_text(data.get("license_url")),
            license_checked_at=display_text(data.get("license_checked_at")),
            version_or_import_ref=display_text(data.get("version_or_import_ref")),
            asset_path=display_text(data.get("asset_path")),
            asset_sha256=display_text(data.get("asset_sha256")),
            formats=tuple(_as_strings(data.get("formats"))),
            weights_or_axes=tuple(_as_strings(data.get("weights_or_axes"))),
            style_tags=tuple(_as_strings(data.get("style_tags"))),
            best_for=display_text(data.get("best_for")),
            avoid_when=display_text(data.get("avoid_when")),
            pairings=tuple(_as_strings(data.get("pairings"))),
            reference_only=bool(data.get("reference_only")),
            reference_preview=(
                dict(data.get("reference_preview"))
                if isinstance(data.get("reference_preview"), Mapping)
                else None
            ),
            notes=display_text(data.get("notes")),
        )


def load_type_shelf() -> dict[str, Any]:
    """Load the packaged type shelf metadata."""

    payload = files("london.data").joinpath("type_shelf.json").read_text(encoding="utf-8")
    data = json.loads(payload)
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise TypeShelfError("Type shelf metadata is missing entries.")
    return data


def type_shelf_entries(*, ring: str | None = None) -> list[TypeShelfEntry]:
    entries = [TypeShelfEntry.from_mapping(entry) for entry in load_type_shelf()["entries"]]
    if ring is not None:
        entries = [entry for entry in entries if entry.ring == ring]
    return entries


def type_shelf_ring_counts() -> dict[str, int]:
    return dict(Counter(entry.ring for entry in type_shelf_entries()))


def resolve_type_shelf_entry(identifier: str, *, bundled_only: bool = False) -> TypeShelfEntry:
    """Resolve a shelf entry by id or family."""

    needle = _canonical(identifier)
    if not needle:
        raise TypeShelfError("--font-shelf-family requires a family name or shelf id.")
    matches = [
        entry
        for entry in type_shelf_entries()
        if needle in {_canonical(entry.id), _canonical(entry.family)}
    ]
    if bundled_only:
        matches = [entry for entry in matches if entry.ring == "bundled_open"]
    if not matches:
        if bundled_only:
            raise TypeShelfError(f"No bundled London Type Shelf font matches {identifier!r}.")
        raise TypeShelfError(f"No London Type Shelf entry matches {identifier!r}.")
    return matches[0]


def apply_bundled_font_to_pack(
    pack: dict[str, Any],
    out_dir: Path,
    *,
    family: str,
) -> dict[str, Any]:
    """Copy one approved bundled font into a pack and mark the recommended route actual_loaded."""

    entry = resolve_type_shelf_entry(family, bundled_only=True)
    _validate_bundled_entry(entry)
    font_bytes = _read_bundled_font(entry)
    digest = hashlib.sha256(font_bytes).hexdigest()
    if digest != entry.asset_sha256:
        raise TypeShelfError("Bundled type shelf asset hash mismatch; refusing to mark actual_loaded.")

    routes = pack_routes(pack)
    matched = resolve_route_ref(pack.get("recommended_route_ref"), routes)
    if matched is None:
        raise TypeShelfError("--font-shelf-family could not resolve recommended_route_ref for launch proof.")
    route_id = display_text(matched.get("id"))
    route_title = display_text(matched.get("title"), fallback="recommended route")
    target_group = _font_group_for_route(pack, route_id)
    target_option = _target_font_option(target_group)

    font_dir = out_dir / "assets" / "fonts"
    font_dir.mkdir(parents=True, exist_ok=True)
    target_name = PurePosixPath(entry.asset_path).name
    target = font_dir / target_name
    target.write_bytes(font_bytes)
    asset_href = f"assets/fonts/{target_name}"

    _apply_entry_to_option(target_option, entry, asset_href)
    return {
        "receipt_id": f"type-shelf-font-proof-{route_id}",
        "kind": "font-proof",
        "summary": (
            f"Actual-loaded bundled font preview for {route_title} uses {entry.family} "
            f"from {entry.source_name}; license: {entry.license_name}; SHA-256: {entry.asset_sha256}."
        ),
        "deterministic": True,
        "provider": "london-type-shelf",
        "route_id": route_id,
        "route_title": route_title,
        "status": "actual_loaded",
        "secrets_printed": False,
    }


def enrich_font_reference_visuals(pack: dict[str, Any]) -> None:
    """Attach visible reference metadata for known non-bundled commercial faces."""

    references = [
        entry
        for entry in type_shelf_entries()
        if entry.reference_preview and entry.ring in {"reference_premium", "catalog_open"}
    ]
    if not references:
        return

    groups = pack.get("font_options") if isinstance(pack.get("font_options"), list) else []
    for group in groups:
        if not isinstance(group, dict):
            continue
        options = group.get("options") if isinstance(group.get("options"), list) else []
        for option in options:
            if not isinstance(option, dict):
                continue
            if _preview_status(option) == "actual_loaded":
                continue
            entry = _reference_entry_for_option(option, references)
            if entry is None or not entry.reference_preview:
                continue
            option["font_preview"] = {
                "status": "reference_only",
                "delivery": "reference_only",
                "rendered_family": entry.family,
                "source_label": f"{entry.source_name} specimen",
                "license_note": (
                    "reference_visual: visual reference, font not loaded. "
                    "London links to the public specimen/license path and does not redistribute the font binary."
                ),
                "reference_visual": True,
                "reference_preview": dict(entry.reference_preview),
            }


def _validate_bundled_entry(entry: TypeShelfEntry) -> None:
    if entry.ring != "bundled_open" or entry.reference_only:
        raise TypeShelfError(f"{entry.family} is not a bundled-open Type Shelf font.")
    required = (
        entry.id,
        entry.family,
        entry.source_name,
        entry.source_url,
        entry.license_name,
        entry.license_url,
        entry.license_checked_at,
        entry.asset_path,
        entry.asset_sha256,
    )
    if not all(required):
        raise TypeShelfError(f"{entry.family} is missing Type Shelf source/license/hash metadata.")
    if PurePosixPath(entry.asset_path).suffix.lower() != ".woff2":
        raise TypeShelfError(f"{entry.family} is not a bundled WOFF2 asset.")


def _read_bundled_font(entry: TypeShelfEntry) -> bytes:
    path = PurePosixPath(entry.asset_path)
    if path.is_absolute() or ".." in path.parts:
        raise TypeShelfError(f"{entry.family} has an unsafe bundled asset path.")
    try:
        return files("london.data").joinpath(*path.parts).read_bytes()
    except FileNotFoundError as exc:
        raise TypeShelfError(f"{entry.family} bundled font asset is missing from the package.") from exc


def _font_group_for_route(pack: Mapping[str, Any], route_id: str) -> dict[str, Any]:
    groups = pack.get("font_options") if isinstance(pack.get("font_options"), list) else []
    for group in groups:
        if isinstance(group, dict) and display_text(group.get("route_id")) == route_id:
            return group
    raise TypeShelfError("--font-shelf-family could not find Font Lab group for the recommended route.")


def _target_font_option(group: dict[str, Any]) -> dict[str, Any]:
    options = group.get("options") if isinstance(group.get("options"), list) else []
    preferred = (
        option
        for option in options
        if isinstance(option, dict) and display_text(option.get("tier")) == "open_public"
    )
    target = next(preferred, None)
    if target is None:
        target = next((option for option in options if isinstance(option, dict)), None)
    if target is None:
        raise TypeShelfError("--font-shelf-family could not find a Font Lab option to mark actual_loaded.")
    return target


def _apply_entry_to_option(option: dict[str, Any], entry: TypeShelfEntry, asset_href: str) -> None:
    option["tier"] = "open_public"
    option["name"] = entry.family
    option["headline_font"] = entry.family
    option["body_font"] = entry.family
    option["label_font"] = entry.family
    option["fallback_stack"] = f'"{entry.family}", system-ui, sans-serif'
    option["best_use"] = option.get("best_use") or entry.best_for
    option["why_london_chose_it"] = (
        display_text(option.get("why_london_chose_it"))
        or f"{entry.family} gives this route a sourceable, bundled type voice without pretending a premium reference is loaded."
    )
    option["what_makes_it_wrong"] = display_text(option.get("what_makes_it_wrong")) or entry.avoid_when
    option["font_preview"] = {
        "status": "actual_loaded",
        "delivery": "local_asset",
        "rendered_family": entry.family,
        "source_label": f"{entry.source_name} ({entry.license_name})",
        "license_note": (
            f"Bundled London Type Shelf asset; license checked {entry.license_checked_at}; "
            f"source: {entry.source_url}; SHA-256: {entry.asset_sha256}."
        ),
        "asset_href": asset_href,
        "source_kind": "bundled_open",
        "shelf_id": entry.id,
        "asset_sha256": entry.asset_sha256,
    }


def _reference_entry_for_option(
    option: Mapping[str, Any],
    references: list[TypeShelfEntry],
) -> TypeShelfEntry | None:
    # Match public specimen cards only against the family the option names as its
    # type recommendation. Fallback stacks/import hints can mention temporary or
    # generic substitutes, and must not relabel another family's specimen as proof.
    primary_fields = (
        option.get("name"),
        option.get("headline_font"),
        option.get("body_font"),
        option.get("label_font"),
    )
    haystack = {_canonical(field) for field in primary_fields if display_text(field)}
    compact = " ".join(sorted(haystack))
    for entry in references:
        needle = _canonical(entry.family)
        if needle and (needle in haystack or needle in compact):
            return entry
    return None


def _preview_status(option: Mapping[str, Any]) -> str:
    preview = option.get("font_preview")
    if isinstance(preview, Mapping):
        return display_text(preview.get("status"))
    return ""


def _canonical(value: str) -> str:
    return "".join(char for char in display_text(value).lower() if char.isalnum())


def _as_strings(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [display_text(item) for item in value if display_text(item)]
    text = display_text(value)
    return [text] if text else []
