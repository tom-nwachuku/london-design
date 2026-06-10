"""Pack-building pipeline for London public handoff artifacts.

This module is intentionally Typer-free. CLI commands translate ``LondonUsageError`` at
the boundary; library callers get product-specific exceptions without importing the CLI.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import sys
from importlib.resources import files
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import unquote

import jsonschema

from london.assets import pack_routes, slugify
from london.companion import load_selection_context
from london.config import load_config
from london.director import (
    ClaudeCodeDirector,
    CreativeDirector,
    LondonNoModelError,
    OfflineDirector,
    _DIRECTOR_MODE_ENV,
)
from london.errors import LondonUsageError
from london.image_generation import (
    METERED_IMAGE_PROVIDERS,
    generate_route_concept,
    normalize_image_provider,
)
from london.persona import scrub_pack
from london.prototype import write_static_prototype
from london.render import write_dossier
from london.route_refs import resolve_route_ref
from london.setup_checks import (
    collect_setup_status,
    merge_env_file,
    recommend_image_provider,
)
from london.session import ARTIFACT_RESOLUTION_KEY, run_london_session
from london.text import clean_title, display_text
from london.type_shelf import TypeShelfError, apply_bundled_font_to_pack, enrich_font_reference_visuals
from london.workbench import enrich_workbench_pack

_PACK_SCHEMA_RESOURCE = "london-pack.schema.json"
DEFAULT_IMAGE_QUALITY_LEVEL = "model-default"
IMAGE_QUALITY_LEVELS = ("model-default", "gemini", "bfl")
_PREMIUM_IMAGE_QUALITY_LEVELS = {"bfl"}
_LOCAL_FONT_EXTENSIONS = {".otf", ".ttf", ".woff", ".woff2"}

PromptImageQuality = Callable[[Sequence[str]], str]
ResolveImageQuality = Callable[..., str]
ResolveDirector = Callable[..., CreativeDirector]
ValidatePack = Callable[[Mapping[str, object]], None]
EnrichPack = Callable[[dict[str, object]], None]
GenerateRouteConcept = Callable[..., Any]


def _image_quality_options(
    *,
    readiness: Mapping[str, bool],
    allow_paid: bool,
) -> list[str]:
    """Return selectable image-quality levels from readiness booleans only."""

    options = ["model-default"]
    for level in ("gemini", "bfl"):
        if not bool(readiness.get(level, False)):
            continue
        if level in _PREMIUM_IMAGE_QUALITY_LEVELS and not allow_paid:
            continue
        options.append(level)
    return options


def _image_quality_readiness(env: Mapping[str, str]) -> tuple[dict[str, bool], bool]:
    """Readiness booleans for the quality menu, sourced from provider recommendation."""

    config = load_config()
    recommendation = recommend_image_provider(env=env, config=config)
    ready_by_provider: dict[str, bool] = {}
    for row in recommendation.get("fallback_chain", []):
        if isinstance(row, dict) and row.get("provider"):
            ready_by_provider[str(row["provider"])] = bool(row.get("ready_generate"))
    readiness = {level: ready_by_provider.get(level, False) for level in ("gemini", "bfl")}
    allow_paid = bool(recommendation.get("allow_paid", False))
    return readiness, allow_paid


def _resolve_image_quality(
    image_quality: str | None,
    *,
    env: Mapping[str, str],
    assume_yes: bool = False,
    prompt_image_quality: PromptImageQuality | None = None,
) -> str:
    """Resolve the image-quality level without importing CLI prompt machinery."""

    if image_quality:
        level = str(image_quality).strip().lower()
        if level not in IMAGE_QUALITY_LEVELS:
            raise LondonUsageError(
                f"--image-quality must be one of {', '.join(IMAGE_QUALITY_LEVELS)}"
            )
        return level

    is_ci = bool(env.get("CI"))
    stdin_tty = bool(getattr(sys.stdin, "isatty", lambda: False)())
    stdout_tty = bool(getattr(sys.stdout, "isatty", lambda: False)())
    interactive = (not assume_yes) and (not is_ci) and stdin_tty and stdout_tty
    if not interactive or prompt_image_quality is None:
        return "model-default"

    readiness, allow_paid = _image_quality_readiness(env)
    options = _image_quality_options(readiness=readiness, allow_paid=allow_paid)
    return prompt_image_quality(options)


def _image_quality_to_provider(level: str, requested_provider: str) -> str:
    """Map a chosen image-quality level to the requested provider."""

    if level == "model-default":
        return requested_provider
    if level in ("gemini", "bfl"):
        return level
    return requested_provider


def validate_pack(pack: Mapping[str, object]) -> None:
    """Hard-gate the assembled pack against the public schema before any file write."""

    schema_text = files("london.data").joinpath(_PACK_SCHEMA_RESOURCE).read_text(encoding="utf-8")
    schema = json.loads(schema_text)
    try:
        jsonschema.Draft202012Validator(schema).validate(pack)
    except jsonschema.ValidationError as exc:
        json_path = "/".join(str(part) for part in exc.absolute_path) or "<root>"
        raise LondonUsageError(
            f"director output missing/invalid: {json_path}: {exc.message}"
        ) from None


def _resolve_director(
    *,
    offline: bool,
    director: CreativeDirector | None,
    env: Mapping[str, str],
) -> CreativeDirector:
    """Select the creative director without silently degrading to offline mode."""

    if director is not None:
        return director
    forced_mode = str(env.get(_DIRECTOR_MODE_ENV, "")).strip().lower()
    if offline or forced_mode == "offline":
        return OfflineDirector()
    return ClaudeCodeDirector(env=env)


def _director_mode(director: CreativeDirector, *, offline: bool) -> str:
    """Human-readable mode label for receipts."""

    if offline or isinstance(director, OfflineDirector):
        return "offline-template-preview"
    if isinstance(director, ClaudeCodeDirector):
        try:
            return director.detect_mode()
        except LondonNoModelError:
            return type(director).__name__
    return type(director).__name__


def write_london_pack(
    brief_path: Path,
    out_dir: Path,
    *,
    fixture: bool = False,
    offline: bool = False,
    image_provider: str | None = None,
    image_quality: str | None = None,
    assume_yes: bool = False,
    max_generated_routes: int | None = None,
    env_file: Path | None = None,
    director: CreativeDirector | None = None,
    artifact_type: str | None = None,
    show_me_selection: Path | Mapping[str, object] | None = None,
    font_asset: Path | None = None,
    font_shelf_family: str | None = None,
    font_family: str | None = None,
    font_source_label: str | None = None,
    font_license_note: str | None = None,
    force: bool = False,
    resolve_director: ResolveDirector | None = None,
    resolve_image_quality: ResolveImageQuality | None = None,
    validate_pack_func: ValidatePack | None = None,
    enrich_workbench_pack_func: EnrichPack | None = None,
    generate_route_concept_func: GenerateRouteConcept | None = None,
) -> dict[str, object]:
    """Run the canonical London session and write the public handoff pack."""

    if not brief_path.exists():
        raise LondonUsageError(f"Brief not found: {brief_path}")
    if (out_dir / "london-pack.json").exists() and not force:
        raise LondonUsageError(
            f"Output already contains london-pack.json: {out_dir}. Use --force to overwrite it."
        )
    command_env, env_file_status = merge_env_file(os.environ, env_file)
    quality_resolver = resolve_image_quality or _resolve_image_quality
    quality_level = quality_resolver(image_quality, env=command_env, assume_yes=assume_yes)
    director_resolver = resolve_director or _resolve_director
    resolved_director = director_resolver(offline=offline, director=director, env=command_env)
    director_mode = _director_mode(resolved_director, offline=offline)
    requested_provider = image_provider or "auto"
    requested_provider = _image_quality_to_provider(quality_level, requested_provider)
    provider_selection: dict[str, object] = {}
    try:
        if requested_provider == "auto":
            setup_status = collect_setup_status(env=command_env, config=load_config())
            image_generation = setup_status.get("image_generation") if isinstance(setup_status.get("image_generation"), dict) else {}
            provider = str(image_generation.get("selected_provider") or "manual-prompt")
            provider_selection = dict(image_generation)
        else:
            provider = normalize_image_provider(requested_provider)
            provider_selection = _explicit_provider_selection(
                requested_provider=requested_provider,
                provider=provider,
                env=command_env,
            )
    except ValueError as exc:
        raise LondonUsageError(str(exc)) from exc

    out_dir.mkdir(parents=True, exist_ok=True)
    selection_context: Mapping[str, object] | None
    if isinstance(show_me_selection, Path):
        selection_context = load_selection_context(show_me_selection)
    elif isinstance(show_me_selection, Mapping):
        selection_context = show_me_selection
    else:
        selection_context = None
    pack: dict[str, object] = run_london_session(
        brief_path,
        fixture=fixture,
        director=resolved_director,
        artifact_type=artifact_type,
        visual_selection=selection_context,
    )
    pack["provider_selection"] = provider_selection
    if env_file_status:
        pack.setdefault("setup_context", {})
        if isinstance(pack["setup_context"], dict):
            pack["setup_context"]["env_file"] = env_file_status
    route_assets, image_receipts = _write_visual_routes(
        pack,
        out_dir,
        generate_images=bool(requested_provider != "none"),
        image_provider=provider,
        requested_provider=requested_provider,
        provider_selection=provider_selection,
        env=command_env,
        max_generated_routes=max_generated_routes,
        image_quality=quality_level,
        generate_route_concept_func=generate_route_concept_func,
    )
    pack["routes"] = route_assets
    director_receipt = {
        "receipt_id": "director-selection",
        "kind": "director",
        "summary": f"Creative direction produced via {director_mode}.",
        "provider": director_mode,
        "deterministic": bool(offline or isinstance(resolved_director, OfflineDirector)),
    }
    artifact_resolution = pack.pop(ARTIFACT_RESOLUTION_KEY, None)
    resolved_artifact = (
        artifact_resolution.get("resolved") if isinstance(artifact_resolution, dict) else None
    ) or pack.get("artifact_type") or "generic"
    artifact_source = (
        artifact_resolution.get("source") if isinstance(artifact_resolution, dict) else None
    ) or "generic-default"
    artifact_receipt = {
        "receipt_id": "artifact-resolution",
        "kind": "artifact-resolution",
        "summary": f"Artifact type '{resolved_artifact}' resolved via {artifact_source}.",
        "provider": director_mode,
        "deterministic": bool(offline or isinstance(resolved_director, OfflineDirector)),
        "status": artifact_source,
    }
    pack["receipts"] = (
        list(pack.get("receipts", []))
        + image_receipts
        + _pack_receipts(pack, out_dir)
        + [director_receipt, artifact_receipt]
    )
    pack_enricher = enrich_workbench_pack_func or enrich_workbench_pack
    pack_enricher(pack)
    enrich_font_reference_visuals(pack)
    if font_asset is not None and display_text(font_shelf_family):
        raise LondonUsageError("--font-shelf-family cannot be combined with --font-asset")
    font_receipt = _apply_launch_font_shelf(
        pack,
        out_dir,
        font_shelf_family=font_shelf_family,
    )
    if font_receipt is None:
        font_receipt = _apply_launch_font_asset(
            pack,
            out_dir,
            font_asset=font_asset,
            font_family=font_family,
            font_source_label=font_source_label,
            font_license_note=font_license_note,
        )
    if font_receipt:
        pack["receipts"].append(font_receipt)

    _write_public_pack_files(pack, out_dir, validate_pack_func=validate_pack_func)
    return pack


def _write_public_pack_files(
    pack: dict[str, object],
    out_dir: Path,
    *,
    validate_pack_func: ValidatePack | None = None,
) -> None:
    scrub_pack(pack)
    validator = validate_pack_func or validate_pack
    validator(pack)
    pack_text = json.dumps(pack, indent=2, sort_keys=True, allow_nan=False)
    session_text = json.dumps(build_london_session_artifact(pack), indent=2, allow_nan=False)
    receipts_text = json.dumps(pack["receipts"], indent=2, sort_keys=True, allow_nan=False)
    (out_dir / "london-pack.json").write_text(pack_text, encoding="utf-8")
    (out_dir / "london-session.json").write_text(
        session_text,
        encoding="utf-8",
    )
    (out_dir / "receipts.json").write_text(receipts_text, encoding="utf-8")
    write_dossier(pack, out_dir / "index.html")
    write_static_prototype(pack, out_dir)
    _write_handoff_docs(pack, out_dir)


def _compact_brain_finding(finding: Mapping[str, Any]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for source_key, target_key in (
        ("id", "id"),
        ("title", "title"),
        ("evidence_class", "evidence_class"),
        ("why_london_used_this", "why_london_used_this"),
    ):
        value = display_text(finding.get(source_key))
        if value:
            payload[target_key] = value
    terms = [display_text(term) for term in finding.get("matched_terms", []) if display_text(term)]
    if terms:
        payload["matched_terms"] = terms
    return payload


def _compact_source(source: Mapping[str, Any]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key in ("source_id", "title", "evidence_class", "status", "why_london_used_this"):
        value = display_text(source.get(key))
        if value:
            payload[key] = value
    return payload


def _compact_receipt(receipt: Mapping[str, Any], *, include_summary: bool = False) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key in ("receipt_id", "kind"):
        value = display_text(receipt.get(key))
        if value:
            payload[key] = value
    if include_summary:
        summary = display_text(receipt.get("summary"))
        if summary:
            payload["summary"] = summary
    return payload


def _compact_query(query: Mapping[str, Any]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key in ("intent", "query"):
        value = display_text(query.get(key))
        if value:
            payload[key] = value
    return payload


def _conversation_session_entry(entry: Mapping[str, Any]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key in ("id", "order", "gate", "decision", "answer", "rationale", "critique", "question"):
        value = entry.get(key)
        if key == "order" and isinstance(value, int):
            payload[key] = value
            continue
        text = display_text(value)
        if text:
            payload[key] = text

    provenance: dict[str, object] = {}
    evidence_classes = entry.get("evidence_classes")
    if isinstance(evidence_classes, Mapping):
        provenance["evidence_classes"] = {
            display_text(key): int(value or 0)
            for key, value in evidence_classes.items()
            if display_text(key)
        }
    if isinstance(entry.get("evidence_count"), int):
        provenance["evidence_count"] = entry["evidence_count"]

    queries = [_compact_query(query) for query in _as_session_mappings(entry.get("brain_queries"))]
    findings = [_compact_brain_finding(finding) for finding in _as_session_mappings(entry.get("brain_findings"))]
    sources = [_compact_source(source) for source in _as_session_mappings(entry.get("sources"))]
    receipts = [_compact_receipt(receipt) for receipt in _as_session_mappings(entry.get("receipts"))]
    if queries:
        provenance["brain_queries"] = [query for query in queries if query]
    if findings:
        provenance["brain_findings"] = [finding for finding in findings if finding]
    if sources:
        provenance["sources"] = [source for source in sources if source]
    if receipts:
        provenance["receipts"] = [receipt for receipt in receipts if receipt]
    if provenance:
        payload["provenance"] = provenance
    return payload


def _as_session_mappings(value: object) -> list[Mapping[str, Any]]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def build_london_session_artifact(pack: Mapping[str, object]) -> dict[str, object]:
    """Build a public-safe, human-inspectable summary of London's current session."""

    routes = _as_session_mappings(pack.get("routes"))
    ref = display_text(pack.get("recommended_route_ref"))
    matched = resolve_route_ref(ref, routes)
    recommended_title = display_text(matched.get("title")) if matched else ref
    brief = pack.get("brief") if isinstance(pack.get("brief"), Mapping) else {}
    evidence_summary = pack.get("evidence_summary") if isinstance(pack.get("evidence_summary"), Mapping) else {}
    composite = {}
    grader = pack.get("grader") if isinstance(pack.get("grader"), Mapping) else {}
    if isinstance(grader.get("composite"), Mapping):
        composite = dict(grader["composite"])

    return {
        "artifact": "london-session",
        "version": 1,
        "brief": {
            key: value
            for key, value in {
                "title": clean_title(pack, fallback="London Pack"),
                "source_label": display_text(brief.get("source_label")),
                "source_ref": display_text(brief.get("source_ref")),
            }.items()
            if value
        },
        "london": {
            "reframe": display_text(pack.get("london_reframe")),
            "recommended_route": {
                "ref": ref,
                "title": recommended_title,
                "recommendation": display_text(pack.get("recommended_route")),
            },
        },
        "routes": [
            {
                key: value
                for key, value in {
                    "id": display_text(route.get("id")),
                    "title": display_text(route.get("title")),
                    "headline": display_text(route.get("headline")),
                }.items()
                if value
            }
            for route in routes
        ],
        "conversation": [
            _conversation_session_entry(entry)
            for entry in _as_session_mappings(pack.get("conversation"))
        ],
        "provenance_summary": {
            "brain_findings": len(evidence_summary.get("brain", [])) if isinstance(evidence_summary.get("brain"), list) else len(_as_session_mappings(pack.get("brain_findings"))),
            "source_targets": len(evidence_summary.get("sources", [])) if isinstance(evidence_summary.get("sources"), list) else 0,
            "live_artifacts": len(evidence_summary.get("live_artifacts", [])) if isinstance(evidence_summary.get("live_artifacts"), list) else 0,
            "receipts": [
                receipt
                for receipt in (
                    _compact_receipt(item, include_summary=True)
                    for item in _as_session_mappings(pack.get("receipts"))
                )
                if receipt
            ],
        },
        "run_details": {
            key: value
            for key, value in {
                "mode": display_text(pack.get("mode")),
                "artifact_type": display_text(pack.get("artifact_type")),
                "grader_score": composite.get("score"),
                "telemetry_available": composite.get("telemetry_available"),
            }.items()
            if value not in ("", None)
        },
    }


def _apply_launch_font_shelf(
    pack: dict[str, object],
    out_dir: Path,
    *,
    font_shelf_family: str | None,
) -> dict[str, object] | None:
    family = display_text(font_shelf_family)
    if not family:
        return None
    try:
        return apply_bundled_font_to_pack(pack, out_dir, family=family)
    except TypeShelfError as exc:
        raise LondonUsageError(str(exc)) from exc


def _apply_launch_font_asset(
    pack: dict[str, object],
    out_dir: Path,
    *,
    font_asset: Path | None,
    font_family: str | None,
    font_source_label: str | None,
    font_license_note: str | None,
) -> dict[str, object] | None:
    metadata_values = [font_family, font_source_label, font_license_note]
    if font_asset is None:
        if any(display_text(value) for value in metadata_values):
            raise LondonUsageError("--font-asset is required when font proof metadata is provided")
        return None

    family = display_text(font_family)
    source_label = display_text(font_source_label)
    license_note = display_text(font_license_note)
    missing = [
        flag
        for flag, value in (
            ("--font-family", family),
            ("--font-source-label", source_label),
            ("--font-license-note", license_note),
        )
        if not value
    ]
    if missing:
        raise LondonUsageError(
            "--font-asset requires explicit local-font proof metadata: " + ", ".join(missing)
        )

    source = font_asset.expanduser()
    if not source.exists() or not source.is_file():
        raise LondonUsageError(f"--font-asset must point to a local font file: {font_asset}")
    suffix = source.suffix.lower()
    if suffix not in _LOCAL_FONT_EXTENSIONS:
        raise LondonUsageError("--font-asset must be a .otf, .ttf, .woff, or .woff2 file")

    routes = pack_routes(pack)
    matched = resolve_route_ref(pack.get("recommended_route_ref"), routes)
    if matched is None:
        raise LondonUsageError("--font-asset could not resolve recommended_route_ref for launch proof")
    route_id = display_text(matched.get("id"))
    route_title = display_text(matched.get("title"), fallback="recommended route")
    font_groups = pack.get("font_options") if isinstance(pack.get("font_options"), list) else []
    target_group = next(
        (
            group
            for group in font_groups
            if isinstance(group, dict) and display_text(group.get("route_id")) == route_id
        ),
        None,
    )
    if target_group is None:
        raise LondonUsageError("--font-asset could not find Font Lab group for the recommended route")
    options = target_group.get("options") if isinstance(target_group.get("options"), list) else []
    target_option = next(
        (
            option
            for option in options
            if isinstance(option, dict) and display_text(option.get("tier")) == "safe_local"
        ),
        None,
    )
    if target_option is None:
        target_option = next((option for option in options if isinstance(option, dict)), None)
    if target_option is None:
        raise LondonUsageError("--font-asset could not find a Font Lab option to mark actual_loaded")

    font_dir = out_dir / "assets" / "fonts"
    font_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{slugify(family, fallback='launch-font')}{suffix}"
    target = font_dir / file_name
    if source.resolve() != target.resolve():
        _copy_font_asset_contents(source, target)
    asset_href = f"assets/fonts/{file_name}"
    target_option["font_preview"] = {
        "status": "actual_loaded",
        "delivery": "local_asset",
        "rendered_family": family,
        "source_label": source_label,
        "license_note": license_note,
        "asset_href": asset_href,
    }

    return {
        "receipt_id": f"launch-font-proof-{route_id}",
        "kind": "font-proof",
        "summary": (
            f"Actual-loaded font preview for {route_title} uses {family} from "
            f"{source_label}; license note: {license_note}."
        ),
        "deterministic": True,
        "provider": "local-font-asset",
        "route_id": route_id,
        "route_title": route_title,
        "status": "actual_loaded",
        "secrets_printed": False,
    }


def _copy_font_asset_contents(source: Path, target: Path) -> None:
    try:
        with source.open("rb") as source_file, target.open("wb") as target_file:
            shutil.copyfileobj(source_file, target_file)
    except OSError as exc:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        raise LondonUsageError(
            "--font-asset could not be copied into the pack; check file permissions and destination."
        ) from exc


def _explicit_provider_selection(
    *,
    requested_provider: str,
    provider: str,
    env: dict[str, str],
    config: dict[str, object] | None = None,
) -> dict[str, object]:
    config = load_config() if config is None else config
    image_config = config.get("image") if isinstance(config.get("image"), dict) else {}
    setup_status = collect_setup_status(env=env, config=config)
    provider_row = next(
        (
            row
            for row in setup_status.get("providers", [])
            if isinstance(row, dict) and row.get("image_provider") == provider
        ),
        None,
    )
    ready = bool(provider_row and provider_row.get("ready"))
    status = str(provider_row.get("status") if provider_row else "unknown_provider")
    allow_paid = bool(image_config.get("allow_paid", False))
    spend_limit = float(image_config.get("spend_limit_usd", 0.0) or 0.0)
    paid_blocked = provider in METERED_IMAGE_PROVIDERS and not (
        allow_paid and spend_limit > 0.0
    ) and (
        ready or status == "paid_blocked"
    )
    allowed = not paid_blocked
    reason = "explicit provider selection" if ready else f"explicit provider requested; {status}"
    if paid_blocked:
        reason = (
            f"explicit {provider} requested; requires image.allow_paid=true "
            "and image.spend_limit_usd > 0"
        )
    return {
        "requested_provider": requested_provider,
        "selected_provider": provider,
        "fallback_chain": [
            {
                "provider": provider,
                "ready": ready,
                "allowed": allowed,
                "reason": reason,
            }
        ],
        "selected_reason": "explicit provider selection",
        "allow_paid": allow_paid,
        "spend_limit_usd": spend_limit,
        "config": dict(image_config),
    }


def _write_visual_routes(
    pack: dict[str, object],
    out_dir: Path,
    *,
    generate_images: bool = False,
    image_provider: str = "manual-prompt",
    requested_provider: str = "auto",
    provider_selection: dict[str, object] | None = None,
    env: dict[str, str] | None = None,
    max_generated_routes: int | None = None,
    image_quality: str = DEFAULT_IMAGE_QUALITY_LEVEL,
    generate_route_concept_func: GenerateRouteConcept | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    asset_dir = out_dir / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    route_concept_generator = generate_route_concept_func or generate_route_concept
    routes = pack_routes(pack)
    generated_route_ids = _route_ids_for_image_generation(
        pack,
        routes,
        generate_images=generate_images,
        max_generated_routes=max_generated_routes,
    )
    output_routes: list[dict[str, object]] = []
    image_receipts: list[dict[str, object]] = []

    for route_index, route in enumerate(routes, start=1):
        route_copy: dict[str, object] = dict(route)
        should_generate_route = display_text(route.get("id")) in generated_route_ids
        if should_generate_route:
            selection = provider_selection or {}
            result = route_concept_generator(
                pack,
                route,
                route_index=route_index,
                provider=image_provider,
                requested_provider=requested_provider,
                fallback_chain=selection.get("fallback_chain", []) if isinstance(selection.get("fallback_chain"), list) else [],
                selection_reason=str(selection.get("selected_reason") or ""),
                spend_policy={
                    "allow_paid": bool(selection.get("allow_paid", image_provider == "bfl")),
                    "spend_limit_usd": float(selection.get("spend_limit_usd", 0.0) or 0.0),
                    "routes_to_generate": len(generated_route_ids),
                    "allow_experimental_free_network": bool(
                        (selection.get("config") if isinstance(selection.get("config"), dict) else {}).get("allow_experimental_free_network", False)
                    ),
                },
                env=env,
            )
            image_receipts.append(result.receipt)
            asset_candidates = [result.asset]
        else:
            non_generated_provider = "none"
            non_generated_requested_provider = requested_provider
            non_generated_reason = "image generation disabled"
            if generate_images and image_provider != "none" and requested_provider != "none":
                non_generated_provider = "manual-prompt"
                non_generated_requested_provider = "manual-prompt"
                non_generated_reason = "route generation limit; manual visual board retained"
            result = route_concept_generator(
                pack,
                route,
                route_index=route_index,
                provider=non_generated_provider,
                requested_provider=non_generated_requested_provider,
                fallback_chain=[],
                selection_reason=non_generated_reason,
                spend_policy={"allow_paid": False, "spend_limit_usd": 0.0},
                env=env,
            )
            image_receipts.append(result.receipt)
            asset_candidates = [result.asset]
        result.receipt["image_quality"] = image_quality
        written_assets = []
        for asset_index, asset in enumerate(asset_candidates, start=1):
            asset_copy = dict(asset)
            if asset_copy.get("src"):
                asset_copy["src"] = _materialize_asset_src(
                    str(asset_copy["src"]),
                    asset_dir,
                    route_index=route_index,
                    asset_index=asset_index,
                )
            if asset_copy.get("receipt_id") == result.receipt.get("receipt_id"):
                _stamp_receipt_asset_proof(result.receipt, out_dir, asset_copy)
            written_assets.append(asset_copy)
        route_copy["assets"] = written_assets
        route_copy.setdefault("approval_state", "session-local-approved")
        route_copy.setdefault("source_inspiration", [
            finding["title"] for finding in pack.get("brain_findings", [])[:3] if isinstance(finding, dict)
        ])
        route_copy.setdefault("build_implications", [
            "Use the palette as UI state, not decoration.",
            "Prototype with large inspection frames before adding motion.",
            "Keep route critique attached to the handoff receipt.",
        ])
        output_routes.append(route_copy)

    (out_dir / "visual-routes.json").write_text(json.dumps(output_routes, indent=2, sort_keys=True), encoding="utf-8")
    return output_routes, image_receipts


def _route_ids_for_image_generation(
    pack: Mapping[str, object],
    routes: Sequence[Mapping[str, object]],
    *,
    generate_images: bool,
    max_generated_routes: int | None,
) -> set[str]:
    if not generate_images:
        return set()
    route_ids = [display_text(route.get("id")) for route in routes if display_text(route.get("id"))]
    if max_generated_routes is None:
        return set(route_ids)
    if max_generated_routes <= 0:
        return set()

    selected: list[str] = []
    matched = resolve_route_ref(pack.get("recommended_route_ref"), routes)
    matched_id = display_text(matched.get("id")) if isinstance(matched, Mapping) else ""
    if matched_id:
        selected.append(matched_id)
    for route_id in route_ids:
        if route_id not in selected:
            selected.append(route_id)
        if len(selected) >= max_generated_routes:
            break
    return set(selected[:max_generated_routes])


def _materialize_asset_src(src: str, asset_dir: Path, *, route_index: int, asset_index: int) -> str:
    if not src.startswith("data:image/"):
        return src

    header, payload = src.split(",", 1)
    mime_type = header.split(":", 1)[1].split(";", 1)[0]
    extension = {
        "image/svg+xml": "svg",
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/webp": "webp",
    }.get(mime_type, "png")
    file_name = f"route-{route_index}-{asset_index}.{extension}"
    path = asset_dir / file_name

    if ";base64" in header:
        path.write_bytes(base64.b64decode(payload))
    elif mime_type == "image/svg+xml":
        path.write_text(unquote(payload), encoding="utf-8")
    else:
        path.write_bytes(payload.encode("utf-8"))
    return f"assets/{file_name}"


def _stamp_receipt_asset_proof(receipt: dict[str, object], out_dir: Path, asset: Mapping[str, object]) -> None:
    src = display_text(asset.get("src"))
    if not src:
        return
    path = out_dir / src
    if not path.exists() or not path.is_file():
        return
    receipt["asset_src"] = src
    receipt["asset_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()


def _write_handoff_docs(pack: dict[str, object], out_dir: Path) -> None:
    title = str(pack["title"])
    routes = pack.get("routes", [])
    first_route = routes[0] if isinstance(routes, list) and routes else {}
    palette = first_route.get("palette", []) if isinstance(first_route, dict) else []
    first_font_group = pack.get("font_options", [])
    first_font = {}
    if isinstance(first_font_group, list) and first_font_group:
        options = first_font_group[0].get("options", []) if isinstance(first_font_group[0], dict) else []
        if isinstance(options, list) and options:
            first_font = options[0] if isinstance(options[0], dict) else {}
    palette_lines = "\n".join(
        f"- {color.get('name', color.get('role', 'Color'))}: `{color.get('hex')}`"
        for color in palette
        if isinstance(color, dict)
    )
    font_stack = first_font.get("fallback_stack", "See index.html Font Lab")

    design_md = f"""# DESIGN: {title}

## London Reframe
{pack['london_reframe']}

## Typography and Color
{pack['typography_color']['type_system']}

{pack['typography_color']['color_system']}

## Palette
{palette_lines}

## Font Lab Starting Point
{font_stack}

## Image Direction
{pack['image_direction']['art_direction']}

## Anti-Position
{pack['anti_position']}
"""

    handoff_md = f"""# BUILD HANDOFF: {title}

## Prototype
Open `prototype/index.html`.

## Dossier
Open `index.html` for the Pack Reader / Creative Moodboard Workbench.

## Workbench Sections
- Brief Snapshot
- London Conversation
- Route Comparison Matrix
- Moodboard Canvas
- Font Lab
- Evidence Drawer
- Copy / Handoff Console
- Receipts / Debug

## Assets
- `london-pack.json`
- `london-session.json` - human-readable London session summary for decisions, reasoning, and compact provenance.
- `visual-routes.json`
- `assets/*.svg`
- `receipts.json`

## Build Notes
- Treat `london-pack.json` as the source of truth and the workbench as its human-readable view.
- Treat `london-session.json` as the inspectable session companion, not a second canonical schema.
- Preserve London's authored conversation count and route comparison in the handoff.
- Keep desktop and mobile prototype frames route-specific.
- Treat source packs as research prompts until live extraction is configured.
- Missing provider keys are acceptable when local reasoning/rendering and manual prompt-card handoff pass.
"""

    (out_dir / "DESIGN.md").write_text(design_md, encoding="utf-8")
    (out_dir / "BUILD-HANDOFF.md").write_text(handoff_md, encoding="utf-8")


def _pack_receipts(pack: dict[str, object], out_dir: Path) -> list[dict[str, object]]:
    return [
        {
            "receipt_id": "local-brain-query",
            "kind": "brain",
            "summary": "Queried bundled sanitized SQLite brain for typography, image direction, and critique findings.",
            "provider": "local-sqlite",
            "deterministic": True,
        },
        {
            "receipt_id": "local-dossier-render",
            "kind": "renderer",
            "summary": "Rendered Creative Moodboard Workbench and static prototype with deterministic local assets.",
            "provider": "local-renderer",
            "deterministic": True,
        },
    ]
