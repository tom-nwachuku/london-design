from __future__ import annotations

import hashlib
from html import unescape
import json
import re
from pathlib import Path
from typing import Any, Mapping

from .grader import DISTINCTNESS_DE_THRESHOLD, _avg_nearest_de
from .route_refs import resolve_route_ref
from .text import display_text


LAUNCH_GATE_IDS = (
    "image_artifact_present",
    "image_receipt_real",
    "font_claim_verified",
    "fallback_label_visible",
    "recommended_route_resolves",
    "first_viewport_visual",
    "actual_image_or_blocked",
    "actual_font_or_blocked",
    "public_route_labels_human",
    "route_visual_delta",
    "prompt_card_not_primary",
)

_LAUNCH_ACTUAL_IMAGE_KINDS = {"generated-concept-image"}
_PROMPT_PRIMARY_KINDS = {"manual-prompt-card", "generation-unavailable"}
_BLOCKED_RECEIPT_MARKERS = ("offline", "fixture", "fake")
_BLOCKED_IMAGE_STATUSES = {"images_disabled", "fixture_system_sketch"}


def evaluate_launch_gates(pack_dir: str | Path) -> dict[str, Any]:
    """Evaluate the Phase 8 visual-fidelity gates for one written London pack.

    This is deliberately static and local: it reads the generated pack JSON plus the
    rendered dossier/prototype HTML and never calls a model or provider. Browser-based
    font checks can still run after this; this helper verifies that the launch-bound
    artifact is structurally honest before it is worth screenshotting or grading.
    """

    root = Path(pack_dir)
    pack_path = root / "london-pack.json"
    if not pack_path.exists():
        raise FileNotFoundError(f"Missing london-pack.json in {root}")
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    dossier_html = _read_optional(root / "index.html")
    prototype_html = _read_optional(root / "prototype" / "index.html")
    combined_html = f"{dossier_html}\n{prototype_html}"

    routes = [route for route in pack.get("routes", []) if isinstance(route, Mapping)]
    receipts = [receipt for receipt in pack.get("receipts", []) if isinstance(receipt, Mapping)]
    image_receipts = [receipt for receipt in receipts if receipt.get("kind") == "image-generation"]
    route_assets = [_primary_asset(route) for route in routes]

    gates = {
        "image_artifact_present": _image_artifact_present(root, pack, routes, route_assets),
        "image_receipt_real": _image_receipt_real(pack, routes, image_receipts, receipts),
        "font_claim_verified": _font_claim_verified(combined_html),
        "fallback_label_visible": _fallback_label_visible(combined_html),
        "recommended_route_resolves": _recommended_route_resolves(pack, routes, combined_html),
        "first_viewport_visual": _first_viewport_visual(dossier_html, prototype_html),
        "actual_image_or_blocked": _actual_image_or_blocked(root, pack, routes, route_assets, image_receipts),
        "actual_font_or_blocked": _actual_font_or_blocked(root, combined_html),
        "public_route_labels_human": _public_route_labels_human(combined_html),
        "route_visual_delta": _route_visual_delta(root, routes, route_assets),
        "prompt_card_not_primary": _prompt_card_not_primary(route_assets, combined_html),
    }
    ok = all(gate["ok"] for gate in gates.values())
    return {
        "ok": ok,
        "pack_dir": str(root),
        "route_count": len(routes),
        "gate_ids": list(LAUNCH_GATE_IDS),
        "gates": gates,
    }


def _read_optional(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _primary_asset(route: Mapping[str, Any]) -> Mapping[str, Any]:
    assets = route.get("assets")
    if isinstance(assets, list):
        for asset in assets:
            if isinstance(asset, Mapping):
                return asset
    return {}


def _asset_path(root: Path, asset: Mapping[str, Any]) -> Path | None:
    src = str(asset.get("src") or "")
    if not src or src.startswith("data:") or re.match(r"^https?://", src):
        return None
    return root / src


def _image_artifact_present(
    root: Path,
    pack: Mapping[str, Any],
    routes: list[Mapping[str, Any]],
    route_assets: list[Mapping[str, Any]],
) -> dict[str, Any]:
    ref = display_text(pack.get("recommended_route_ref"))
    matched = resolve_route_ref(ref, routes)
    missing: list[str] = []
    asset: Mapping[str, Any] = {}
    if matched is None:
        missing.append("recommended public-proof route is unresolved.")
    else:
        index = _route_index(routes, matched)
        asset = route_assets[index] if index is not None and index < len(route_assets) else {}
        title = display_text(matched.get("title") or matched.get("id"), fallback="untitled route")
        kind = display_text(asset.get("kind"))
        src = display_text(asset.get("src"))
        path = _asset_path(root, asset)
        if kind not in _LAUNCH_ACTUAL_IMAGE_KINDS:
            missing.append(
                f"{title}: public proof blocked; primary visual kind is {kind or '<missing>'}, "
                "not generated/local image proof."
            )
        elif not src:
            missing.append(f"{title}: missing generated image asset src")
        elif path is None:
            missing.append(f"{title}: generated image asset is not a local written path")
        elif not path.exists():
            missing.append(f"{title}: generated image asset file not found: {src}")
    return {
        "ok": bool(routes) and not missing,
        "detail": "Selected public-proof route has a generated/local image artifact; fallback boards are internal only.",
        "recommended_route_ref": ref,
        "recommended_route_title": display_text(matched.get("title")) if matched else "",
        "asset_kind": display_text(asset.get("kind")) if isinstance(asset, Mapping) else "",
        "asset_src": display_text(asset.get("src")) if isinstance(asset, Mapping) else "",
        "failures": missing,
    }


def _image_receipt_real(
    pack: Mapping[str, Any],
    routes: list[Mapping[str, Any]],
    image_receipts: list[Mapping[str, Any]],
    receipts: list[Mapping[str, Any]],
) -> dict[str, Any]:
    failures: list[str] = []
    if len(image_receipts) < len(routes):
        failures.append(f"Only {len(image_receipts)} image receipts for {len(routes)} routes.")
    for receipt in image_receipts:
        status = str(receipt.get("status") or "")
        if status in _BLOCKED_IMAGE_STATUSES:
            failures.append(f"Image receipt {receipt.get('receipt_id') or '<unknown>'} has blocked status {status}.")
        blocked = _blocked_receipt_marker(receipt)
        if blocked:
            failures.append(f"Image receipt {receipt.get('receipt_id') or '<unknown>'} contains blocked marker {blocked}.")
    for receipt in receipts:
        if receipt.get("kind") != "director":
            continue
        if bool(receipt.get("deterministic")):
            failures.append("Director receipt is deterministic; launch pilots require the model path.")
        blocked = _blocked_receipt_marker(receipt)
        if blocked:
            failures.append(f"Director receipt contains blocked marker {blocked}.")
    if str(pack.get("mode") or "") == "offline":
        failures.append("Pack mode is offline.")
    return {
        "ok": bool(routes) and bool(image_receipts) and not failures,
        "detail": "Receipts are honest and launch-eligible; no offline, fixture, fake, or disabled image state.",
        "failures": failures,
    }


def _blocked_receipt_marker(receipt: Mapping[str, Any]) -> str:
    fields = (
        receipt.get("provider"),
        receipt.get("requested_provider"),
        receipt.get("resolved_provider"),
        receipt.get("status"),
        receipt.get("model"),
        receipt.get("generation_mode"),
    )
    haystack = " ".join(str(field or "").lower() for field in fields)
    for marker in _BLOCKED_RECEIPT_MARKERS:
        if marker in haystack:
            return marker
    return ""


def _font_claim_verified(html: str) -> dict[str, Any]:
    actual_count = len(re.findall(r'data-font-preview-status="actual_loaded"', html))
    helper_present = "londonVerifyFontPreviews" in html and "document.fonts.ready" in html
    local_face_present = "@font-face" in html
    failures: list[str] = []
    if actual_count and not helper_present:
        failures.append("actual_loaded claims exist but the font verification helper is missing.")
    if actual_count and not local_face_present:
        failures.append("actual_loaded claims exist without local @font-face CSS.")
    helper_detail = "browser helper present" if helper_present else "no browser helper present"
    return {
        "ok": not failures,
        "detail": f"{actual_count} actual_loaded font claim(s); {helper_detail}.",
        "actual_loaded_claims": actual_count,
        "helper_present": helper_present,
        "failures": failures,
    }


def _fallback_label_visible(html: str) -> dict[str, Any]:
    lower = html.lower()
    fallback_count = lower.count('data-font-preview-status="fallback_approximation"')
    reference_count = lower.count('data-font-preview-status="reference_only"')
    failures: list[str] = []
    if fallback_count and "fallback approximation" not in _visible_text(html).lower():
        failures.append("Fallback font previews exist but no visible fallback approximation label is present.")
    return {
        "ok": not failures,
        "detail": "Fallback/reference font states are retained in secondary preview metadata.",
        "fallback_count": fallback_count,
        "reference_count": reference_count,
        "failures": failures,
    }


def _recommended_route_resolves(
    pack: Mapping[str, Any], routes: list[Mapping[str, Any]], html: str
) -> dict[str, Any]:
    ref = display_text(pack.get("recommended_route_ref"))
    matched = resolve_route_ref(ref, routes)
    route_labels = [
        f"{display_text(route.get('id'), fallback='<missing id>')} / "
        f"{display_text(route.get('title'), fallback='<missing title>')}"
        for route in routes
    ]
    failures: list[str] = []
    chip_texts = _recommended_chip_texts(html)
    if not ref:
        failures.append("recommended_route_ref is missing.")
    if ref and matched is None:
        failures.append(
            "recommended_route_ref did not resolve: "
            f"{ref}; available routes: {', '.join(route_labels) or '<none>'}."
        )
    if html and not chip_texts:
        failures.append("No public recommended chip was found in rendered HTML.")
    if matched is not None:
        title = display_text(matched.get("title"))
        if chip_texts and title not in chip_texts:
            failures.append(
                "recommended chip does not show the resolved route title: "
                f"expected {title}; saw {', '.join(chip_texts)}."
            )
        if _looks_like_machine_ref(ref) and ref in chip_texts:
            failures.append(f"recommended chip exposes raw machine ref: {ref}.")
    return {
        "ok": bool(routes) and not failures,
        "detail": "Recommended route resolves to a packed route and the public chip is human-readable.",
        "recommended_route_ref": ref,
        "resolved_route_title": display_text(matched.get("title")) if matched else "",
        "chip_texts": chip_texts,
        "available_routes": route_labels,
        "failures": failures,
    }


def _first_viewport_visual(dossier_html: str, prototype_html: str) -> dict[str, Any]:
    failures: list[str] = []
    prototype_hero = _section_markup(prototype_html, "prototype-hero")
    prototype_states = _visual_states(prototype_hero)
    dossier_prefix = dossier_html[:6000]
    dossier_states = _visual_states(dossier_prefix)
    if not prototype_states and not dossier_states:
        failures.append(
            "No visual artifact appears in the prototype hero or dossier first viewport contract."
        )
    return {
        "ok": not failures,
        "detail": "Public proof leads with a visual surface before report-style receipts.",
        "prototype_hero_visual_states": sorted(set(prototype_states)),
        "dossier_first_viewport_visual_states": sorted(set(dossier_states)),
        "proof_surface": "prototype" if prototype_states else ("dossier" if dossier_states else ""),
        "failures": failures,
    }


def _actual_image_or_blocked(
    root: Path,
    pack: Mapping[str, Any],
    routes: list[Mapping[str, Any]],
    route_assets: list[Mapping[str, Any]],
    image_receipts: list[Mapping[str, Any]],
) -> dict[str, Any]:
    ref = display_text(pack.get("recommended_route_ref"))
    matched = resolve_route_ref(ref, routes)
    eligible_route_ids = [
        display_text(route.get("id"))
        for route, asset in zip(routes, route_assets, strict=False)
        if display_text(asset.get("kind")) in _LAUNCH_ACTUAL_IMAGE_KINDS
    ]
    blocked_route_ids = [
        display_text(route.get("id"))
        for route, asset in zip(routes, route_assets, strict=False)
        if display_text(asset.get("kind")) not in _LAUNCH_ACTUAL_IMAGE_KINDS
    ]
    failures: list[str] = []
    if matched is None:
        failures.append("blocked_for_real_image: recommended route is unresolved.")
        asset: Mapping[str, Any] = {}
    else:
        index = _route_index(routes, matched)
        asset = route_assets[index] if index is not None and index < len(route_assets) else {}
        kind = display_text(asset.get("kind"))
        src = display_text(asset.get("src"))
        path = _asset_path(root, asset)
        if kind not in _LAUNCH_ACTUAL_IMAGE_KINDS:
            failures.append(
                "blocked_for_real_image: recommended route hero is "
                f"{kind or '<missing>'}, not generated-concept-image."
            )
        elif path is None:
            failures.append(
                "blocked_for_real_image: recommended route hero is not a local written image path."
            )
        elif not path.exists():
            failures.append(
                f"blocked_for_real_image: recommended route hero file is missing: {src}."
            )
        receipt = _image_receipt_for_route(image_receipts, matched)
        if not receipt:
            failures.append("blocked_for_real_image: no image-generation receipt for the recommended route.")
        else:
            status = display_text(receipt.get("status"))
            if status != "generated_live":
                failures.append(
                    "blocked_for_real_image: recommended route receipt status is "
                    f"{status or '<missing>'}, not generated_live."
                )
    return {
        "ok": not failures,
        "detail": "Public gallery proof selects generated/local image routes only; fallback boards stay internal or blocked.",
        "recommended_route_ref": ref,
        "recommended_route_title": display_text(matched.get("title")) if matched else "",
        "asset_kind": display_text(asset.get("kind")) if isinstance(asset, Mapping) else "",
        "asset_src": display_text(asset.get("src")) if isinstance(asset, Mapping) else "",
        "public_gallery_eligible_route_ids": [route_id for route_id in eligible_route_ids if route_id],
        "public_gallery_blocked_route_ids": [route_id for route_id in blocked_route_ids if route_id],
        "failures": failures,
    }


def _actual_font_or_blocked(root: Path, html: str) -> dict[str, Any]:
    actual_count = len(re.findall(r'data-font-preview-status="actual_loaded"', html))
    helper_present = "londonVerifyFontPreviews" in html and "document.fonts.ready" in html
    local_face_present = "@font-face" in html
    asset_hrefs = _font_asset_hrefs(html)
    missing_assets = [href for href in asset_hrefs if not (root / href).exists()]
    failures: list[str] = []
    if actual_count < 1:
        failures.append("blocked_for_actual_font: no actual_loaded font preview is present.")
    if actual_count and not helper_present:
        failures.append("blocked_for_actual_font: browser font verification helper is missing.")
    if actual_count and not local_face_present:
        failures.append("blocked_for_actual_font: actual_loaded preview has no local @font-face CSS.")
    if missing_assets:
        failures.append(
            "blocked_for_actual_font: local font assets are missing: " + ", ".join(missing_assets) + "."
        )
    return {
        "ok": not failures,
        "detail": "At least one local font asset is claimed actual_loaded and ready for browser verification.",
        "actual_loaded_claims": actual_count,
        "helper_present": helper_present,
        "font_face_present": local_face_present,
        "asset_hrefs": asset_hrefs,
        "failures": failures,
    }


def _public_route_labels_human(html: str) -> dict[str, Any]:
    text = _visible_text(html)
    machine_refs = sorted(set(re.findall(r"\broute_[a-z0-9_]+\b", text)))
    failures = [f"Public text exposes raw machine route refs: {', '.join(machine_refs)}."] if machine_refs else []
    return {
        "ok": not failures,
        "detail": "Public route labels are human-readable; raw route_ refs stay out of visible text.",
        "machine_refs": machine_refs,
        "failures": failures,
    }


def _recommended_chip_texts(html: str) -> list[str]:
    values: list[str] = []
    for match in re.findall(r'<span class="recommended-chip"[^>]*>(.*?)</span>', html, flags=re.S):
        text = unescape(re.sub(r"<[^>]+>", "", match)).strip()
        if text:
            values.append(text)
    return values


def _looks_like_machine_ref(value: str) -> bool:
    return bool(re.fullmatch(r"route[_-][a-z0-9][a-z0-9_-]*", value))


def _section_markup(html: str, class_name: str) -> str:
    match = re.search(
        rf'<section[^>]*class="[^"]*\b{re.escape(class_name)}\b[^"]*"[\s\S]*?</section>',
        html,
    )
    return match.group(0) if match else ""


def _visual_states(html: str) -> list[str]:
    return re.findall(r'data-visual-state="([^"]+)"', html)


def _route_index(routes: list[Mapping[str, Any]], matched: Mapping[str, Any]) -> int | None:
    matched_id = display_text(matched.get("id"))
    matched_title = display_text(matched.get("title"))
    for index, route in enumerate(routes):
        if display_text(route.get("id")) == matched_id and display_text(route.get("title")) == matched_title:
            return index
    return None


def _image_receipt_for_route(
    image_receipts: list[Mapping[str, Any]], route: Mapping[str, Any]
) -> Mapping[str, Any] | None:
    route_id = display_text(route.get("id"))
    for receipt in image_receipts:
        if display_text(receipt.get("route_id")) == route_id:
            return receipt
    return None


def _visible_text(html: str) -> str:
    stripped = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    stripped = re.sub(r"<style[\s\S]*?</style>", " ", stripped, flags=re.I)
    stripped = re.sub(r"<[^>]+>", " ", stripped)
    return unescape(re.sub(r"\s+", " ", stripped))


def _route_visual_delta(
    root: Path, routes: list[Mapping[str, Any]], route_assets: list[Mapping[str, Any]]
) -> dict[str, Any]:
    titles = [str(route.get("title") or "") for route in routes]
    palettes = [route.get("palette", []) for route in routes]
    asset_hashes = [_asset_hash(root, asset) for asset in route_assets]
    failures: list[str] = []
    if len(routes) < 2:
        failures.append("Need at least two routes to prove visual delta.")
    if len(set(titles)) != len(titles):
        failures.append("Route titles are not distinct.")
    distinct_palette_pairs = 0
    for index, palette in enumerate(palettes):
        for other in palettes[index + 1 :]:
            delta = _avg_nearest_de(
                list(palette) if isinstance(palette, list) else [],
                list(other) if isinstance(other, list) else [],
            )
            if delta is not None and delta >= DISTINCTNESS_DE_THRESHOLD:
                distinct_palette_pairs += 1
    if len(routes) > 1 and distinct_palette_pairs == 0:
        failures.append("Route palettes do not show meaningful variation.")
    non_empty_hashes = [value for value in asset_hashes if value]
    if len(set(non_empty_hashes)) < min(2, len(routes)):
        failures.append("Route visual assets are missing or identical.")
    return {
        "ok": not failures,
        "detail": "Routes show distinct titles, palettes, and visual artifacts.",
        "unique_titles": len(set(titles)),
        "distinct_palette_pairs": distinct_palette_pairs,
        "unique_asset_hashes": len(set(non_empty_hashes)),
        "failures": failures,
    }


def _font_asset_hrefs(html: str) -> list[str]:
    values = re.findall(r'data-font-asset-href="([^"]+)"', html)
    return [unescape(value).strip() for value in values if unescape(value).strip()]


def _asset_hash(root: Path, asset: Mapping[str, Any]) -> str:
    path = _asset_path(root, asset)
    src = str(asset.get("src") or "")
    if path is not None and path.exists():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    if src.startswith("data:"):
        return hashlib.sha256(src.encode("utf-8")).hexdigest()
    return ""


def _prompt_card_not_primary(route_assets: list[Mapping[str, Any]], html: str) -> dict[str, Any]:
    failures: list[str] = []
    primary_kinds = [str(asset.get("kind") or "") for asset in route_assets]
    prompt_primary = [kind for kind in primary_kinds if kind in _PROMPT_PRIMARY_KINDS]
    if prompt_primary:
        failures.append(f"Prompt-only visual kinds are primary route assets: {sorted(set(prompt_primary))}.")
    visual_states = re.findall(r'data-visual-state="([^"]+)"', html)
    bad_states = [state for state in visual_states if state in _PROMPT_PRIMARY_KINDS]
    if visual_states and len(bad_states) == len(visual_states):
        failures.append("All rendered visual states are prompt-only.")
    return {
        "ok": bool(route_assets) and not failures,
        "detail": "Primary route visuals are not prompt-card-only.",
        "primary_kinds": primary_kinds,
        "visual_states": sorted(set(visual_states)),
        "failures": failures,
    }
