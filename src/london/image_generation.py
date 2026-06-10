from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Mapping, Sequence

from .assets import fallback_asset, normalize_palette, slugify, visual_direction_board_data_uri
from .errors import LondonError
from .text import clean_brief_text, display_text

IMAGE_PROVIDERS = (
    "automatic1111",
    "comfyui",
    "external-cmd",
    "draw-things",
    "gemini",
    "bfl",
    "openai",
    "fal",
    "replicate",
    "pollinations",
    "manual-prompt",
    "none",
    "fixture",
)
METERED_IMAGE_PROVIDERS = frozenset({"gemini", "openai", "bfl", "fal", "replicate"})
IMAGE_PROVIDER_PRICE_LAST_VERIFIED = "2026-06-09"
IMAGE_PROVIDER_PRICE_CEILINGS_USD = {
    "gemini": 0.25,
    "openai": 0.35,
    "bfl": 0.10,
    "fal": 0.20,
    "replicate": 0.10,
}
SCRUB_ERROR_MESSAGE_CAP = 240
SCRUB_ERROR_HTTP_CAP = 600
MAX_IMAGE_RESPONSE_BYTES = 30 * 1024 * 1024
MAX_JSON_RESPONSE_BYTES = 1 * 1024 * 1024
_SECRET_ENV_NAME_RE = re.compile(r"(_API_KEY|_KEY|_TOKEN|_SECRET)$")
_ORIGINAL_URLOPEN = urllib.request.urlopen


@dataclass(frozen=True)
class ImageGenerationRequest:
    """Provider-neutral request for one route concept image."""

    pack: Mapping[str, Any]
    route: Mapping[str, Any]
    route_index: int
    requested_provider: str
    resolved_provider: str
    fallback_chain: Sequence[Mapping[str, Any]] = ()
    selection_reason: str = ""
    spend_policy: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ImageGenerationResult:
    """Asset plus receipt payload for the public London Pack."""

    asset: dict[str, Any]
    receipt: dict[str, Any]


class ImageGenerator:
    """Small adapter facade for real provider image lanes and honest visual boards."""

    def __init__(self, provider: str = "local", env: Mapping[str, str] | None = None) -> None:
        self.provider = normalize_image_provider(provider)
        self.env = os.environ if env is None else env

    def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        # GATE-03: read artifact_type AS GIVEN from the pack the request already carries
        # (the pack has artifact_type by now — run_london_session assembles it before
        # _write_visual_routes). No renderer-side re-derivation.
        artifact_type = request.pack.get("artifact_type", "generic")
        prompt = build_image_prompt(request.pack, request.route, artifact_type=artifact_type)
        if self.provider == "manual-prompt":
            return _manual_prompt_result(request, prompt, status="manual_prompt_ready")
        if self.provider == "none":
            return _unavailable_result(request, prompt, status="images_disabled")
        if self.provider == "fixture":
            return _fixture_result(request, prompt, status="fixture_system_sketch")

        try:
            if self.provider == "automatic1111":
                return _automatic1111_result(request, prompt, self.env)
            if self.provider == "comfyui":
                return _comfyui_result(request, prompt, self.env)
            if self.provider == "external-cmd":
                return _external_cmd_result(request, prompt, self.env)
            if self.provider == "draw-things":
                return _draw_things_result(request, prompt, self.env)
            if self.provider == "pollinations":
                return _pollinations_result(request, prompt, self.env)
            if self.provider == "gemini":
                return _gemini_result(request, prompt, self.env)
            if self.provider == "bfl":
                return _bfl_result(request, prompt, self.env)
            if self.provider == "openai":
                return _openai_result(request, prompt, self.env)
            if self.provider == "fal":
                return _fal_result(request, prompt, self.env)
            if self.provider == "replicate":
                return _replicate_result(request, prompt, self.env)
        except ProviderUnavailable as exc:
            return _manual_prompt_result(
                request,
                prompt,
                status=str(exc),
                failure=exc.failure,
                request_config=exc.request_config,
                attempted_request_configs=exc.attempted_request_configs,
                model=exc.model,
                error_class=exc.error_class,
            )
        except Exception as exc:  # pragma: no cover - live-provider defensive path
            return _manual_prompt_result(
                request,
                prompt,
                status="fallback_provider_error",
                failure=_scrub_error(exc, self.env),
                error_class=_provider_error_class(exc),
            )

        return _manual_prompt_result(request, prompt, status="fallback_unknown_provider")


class ProviderUnavailable(LondonError):
    """Raised when an optional live provider is not configured."""

    def __init__(
        self,
        status: str,
        *,
        failure: str | None = None,
        request_config: Mapping[str, Any] | None = None,
        attempted_request_configs: Sequence[Mapping[str, Any]] | None = None,
        model: str | None = None,
        error_class: str | None = None,
    ) -> None:
        super().__init__(status)
        self.status = status
        self.failure = failure
        self.request_config = request_config
        self.attempted_request_configs = list(attempted_request_configs or [])
        self.model = model
        self.error_class = error_class or _provider_error_class(status)


def _env_int(env: Mapping[str, str], key: str, default: int) -> int:
    value = env.get(key)
    if value is None or str(value).strip() == "":
        return default
    try:
        return int(str(value))
    except ValueError as exc:
        raise ProviderUnavailable(
            "fallback_invalid_env_value",
            failure=f"{key} must be an integer.",
            error_class="configuration",
        ) from exc


def _env_float(env: Mapping[str, str], key: str, default: float) -> float:
    value = env.get(key)
    if value is None or str(value).strip() == "":
        return default
    try:
        return float(str(value))
    except ValueError as exc:
        raise ProviderUnavailable(
            "fallback_invalid_env_value",
            failure=f"{key} must be numeric.",
            error_class="configuration",
        ) from exc


def _poll_seconds(env: Mapping[str, str], key: str, default: float) -> float:
    return max(0.25, _env_float(env, key, default))


def normalize_image_provider(provider: str | None) -> str:
    normalized = (provider or "manual-prompt").strip().lower().replace("_", "-")
    aliases = {
        "local": "manual-prompt",
        "local-deterministic": "fixture",
        "local-renderer": "fixture",
        "local-system-sketch": "fixture",
        "system-sketch": "fixture",
        "prompt": "manual-prompt",
        "prompt-card": "manual-prompt",
        "manual": "manual-prompt",
        "manual-prompt-card": "manual-prompt",
        "a1111": "automatic1111",
        "automatic-1111": "automatic1111",
        "stable-diffusion-webui": "automatic1111",
        "comfy": "comfyui",
        "external": "external-cmd",
        "external-command": "external-cmd",
        "local-command": "external-cmd",
        "local-cmd": "external-cmd",
        "bring-your-own": "external-cmd",
        "byo": "external-cmd",
        "drawthings": "draw-things",
        "draw-things-cli": "draw-things",
        "bfl-flux": "bfl",
        "flux": "bfl",
        "replicate-flux": "replicate",
        "perchance": "manual-prompt",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in IMAGE_PROVIDERS:
        raise ValueError(f"Unknown image provider: {provider}")
    return normalized


def generate_route_concept(
    pack: Mapping[str, Any],
    route: Mapping[str, Any],
    *,
    route_index: int,
    provider: str = "local",
    requested_provider: str | None = None,
    fallback_chain: Sequence[Mapping[str, Any]] = (),
    selection_reason: str = "",
    spend_policy: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> ImageGenerationResult:
    resolved_provider = normalize_image_provider(provider)
    resolved_spend_policy = _spend_policy_with_estimate(resolved_provider, spend_policy)
    request = ImageGenerationRequest(
        pack=pack,
        route=route,
        route_index=route_index,
        requested_provider=requested_provider or resolved_provider,
        resolved_provider=resolved_provider,
        fallback_chain=fallback_chain,
        selection_reason=selection_reason,
        spend_policy=resolved_spend_policy,
    )
    return ImageGenerator(provider=resolved_provider, env=env).generate(request)


def _spend_policy_with_estimate(
    provider: str,
    spend_policy: Mapping[str, Any] | None,
) -> dict[str, Any]:
    policy = dict(spend_policy or {})
    normalized = normalize_image_provider(provider)
    if normalized not in METERED_IMAGE_PROVIDERS:
        return policy
    route_count = _spend_route_count(policy)
    unit_ceiling = IMAGE_PROVIDER_PRICE_CEILINGS_USD[normalized]
    policy.update(
        {
            "metered_provider": True,
            "price_ceiling_usd": unit_ceiling,
            "price_ceiling_last_verified": IMAGE_PROVIDER_PRICE_LAST_VERIFIED,
            "routes_to_generate": route_count,
            "estimated_cost_usd": round(unit_ceiling * route_count, 4),
        }
    )
    return policy


def _spend_route_count(policy: Mapping[str, Any]) -> int:
    try:
        value = int(policy.get("routes_to_generate") or 1)
    except (TypeError, ValueError):
        value = 1
    return max(1, value)


def _raise_if_spend_blocked(request: ImageGenerationRequest, provider: str) -> None:
    policy = request.spend_policy if isinstance(request.spend_policy, Mapping) else {}
    if provider not in METERED_IMAGE_PROVIDERS:
        return
    estimate = _spend_policy_with_estimate(provider, policy)
    estimated_cost = float(estimate.get("estimated_cost_usd") or 0.0)
    try:
        spend_limit = float(estimate.get("spend_limit_usd") or 0.0)
    except (TypeError, ValueError):
        spend_limit = 0.0
    if not bool(estimate.get("allow_paid")):
        raise ProviderUnavailable(
            "fallback_paid_provider_blocked",
            failure=(
                f"{provider} is a metered image provider; set image.allow_paid=true "
                "and image.spend_limit_usd before generation."
            ),
            request_config=_spend_request_config(estimate),
        )
    if estimated_cost > spend_limit:
        raise ProviderUnavailable(
            "fallback_spend_limit_exceeded",
            failure=(
                f"Estimated {provider} image cost ${estimated_cost:.2f} exceeds "
                f"spend_limit_usd ${spend_limit:.2f}; lower route count or raise the limit."
            ),
            request_config=_spend_request_config(estimate),
        )


def _spend_request_config(policy: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "estimated_cost_usd": policy.get("estimated_cost_usd"),
        "spend_limit_usd": policy.get("spend_limit_usd", 0.0),
        "price_ceiling_usd": policy.get("price_ceiling_usd"),
        "routes_to_generate": policy.get("routes_to_generate"),
        "price_ceiling_last_verified": policy.get("price_ceiling_last_verified"),
    }


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _open_http_request(
    request: urllib.request.Request | str,
    *,
    timeout: float,
    allow_redirects: bool = True,
) -> Any:
    if allow_redirects:
        return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 - explicit provider/user-configured HTTP seam
    if urllib.request.urlopen is not _ORIGINAL_URLOPEN:
        return urllib.request.urlopen(request, timeout=timeout)  # test fakes still exercise the seam
    opener = urllib.request.build_opener(_NoRedirectHandler)
    return opener.open(request, timeout=timeout)


def _post_json(
    url: str,
    payload: Mapping[str, Any],
    *,
    headers: Mapping[str, str],
    timeout: float,
    env: Mapping[str, str],
    max_bytes: int = MAX_JSON_RESPONSE_BYTES,
) -> dict[str, Any]:
    http_request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=dict(headers),
        method="POST",
    )
    try:
        with _open_http_request(http_request, timeout=timeout) as response:
            return _decode_json_response(response, max_bytes=max_bytes, env=env)
    except ProviderUnavailable:
        raise
    except urllib.error.HTTPError:
        raise
    except TimeoutError as exc:
        raise ProviderUnavailable("fallback_provider_timeout", failure=_scrub_error(exc, env), error_class="timeout") from exc
    except (OSError, urllib.error.URLError) as exc:
        raise ProviderUnavailable("fallback_provider_error", failure=_scrub_error(exc, env), error_class="network") from exc


def _get_json(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float,
    env: Mapping[str, str],
    credential_origin: str | None = None,
    max_bytes: int = MAX_JSON_RESPONSE_BYTES,
) -> dict[str, Any]:
    safe_headers = dict(headers or {})
    allow_redirects = True
    if safe_headers and credential_origin:
        _validate_credentialed_get_url(url, credential_origin)
        allow_redirects = False
    http_request: urllib.request.Request | str = (
        urllib.request.Request(url, headers=safe_headers, method="GET") if safe_headers else url
    )
    try:
        with _open_http_request(http_request, timeout=timeout, allow_redirects=allow_redirects) as response:
            return _decode_json_response(response, max_bytes=max_bytes, env=env)
    except ProviderUnavailable:
        raise
    except urllib.error.HTTPError:
        raise
    except TimeoutError as exc:
        raise ProviderUnavailable("fallback_provider_timeout", failure=_scrub_error(exc, env), error_class="timeout") from exc
    except (OSError, urllib.error.URLError) as exc:
        raise ProviderUnavailable("fallback_provider_error", failure=_scrub_error(exc, env), error_class="network") from exc


def _get_bytes(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float,
    env: Mapping[str, str],
    max_bytes: int = MAX_IMAGE_RESPONSE_BYTES,
    credential_origin: str | None = None,
) -> tuple[bytes, str]:
    safe_headers = dict(headers or {})
    allow_redirects = True
    if safe_headers and credential_origin:
        _validate_credentialed_get_url(url, credential_origin)
        allow_redirects = False
    http_request: urllib.request.Request | str = (
        urllib.request.Request(url, headers=safe_headers, method="GET") if safe_headers else url
    )
    try:
        with _open_http_request(http_request, timeout=timeout, allow_redirects=allow_redirects) as response:
            return _read_capped_response(response, max_bytes=max_bytes, env=env), _response_mime_type(response)
    except ProviderUnavailable:
        raise
    except urllib.error.HTTPError:
        raise
    except TimeoutError as exc:
        raise ProviderUnavailable("fallback_provider_timeout", failure=_scrub_error(exc, env), error_class="timeout") from exc
    except (OSError, urllib.error.URLError) as exc:
        raise ProviderUnavailable("fallback_provider_error", failure=_scrub_error(exc, env), error_class="network") from exc


def _decode_json_response(response: Any, *, max_bytes: int, env: Mapping[str, str]) -> dict[str, Any]:
    payload = _read_capped_response(response, max_bytes=max_bytes, env=env)
    data = json.loads(payload.decode("utf-8"))
    if not isinstance(data, dict):
        raise ProviderUnavailable("fallback_provider_error", failure="Provider JSON response was not an object.", error_class="bad_request")
    return data


def _read_capped_response(response: Any, *, max_bytes: int, env: Mapping[str, str]) -> bytes:
    try:
        payload = response.read(max_bytes + 1)
    except TypeError:
        payload = response.read()
    if len(payload) > max_bytes:
        raise ProviderUnavailable(
            "fallback_response_too_large",
            failure=f"Provider response exceeded {max_bytes} bytes.",
            error_class="bad_request",
        )
    return payload


def _validate_credentialed_get_url(url: str, origin_url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    origin = urllib.parse.urlsplit(origin_url)
    host = (parsed.hostname or "").lower()
    origin_host = (origin.hostname or "").lower()
    if parsed.scheme != "https":
        raise ProviderUnavailable(
            "fallback_provider_error",
            failure="Credentialed provider polling URL must use https.",
            error_class="auth",
        )
    if not host or not origin_host or not (host == origin_host or host.endswith(f".{origin_host}")):
        raise ProviderUnavailable(
            "fallback_provider_error",
            failure="Credentialed provider polling URL did not match the submit host.",
            error_class="auth",
        )


def _provider_error_class(value: object) -> str | None:
    if isinstance(value, urllib.error.HTTPError):
        if value.code in {401, 403}:
            return "auth"
        if value.code == 429:
            return "quota"
        if 400 <= value.code < 500:
            return "bad_request"
        return "network"
    if isinstance(value, TimeoutError):
        return "timeout"
    if isinstance(value, (urllib.error.URLError, OSError)):
        return "network"
    status = str(value)
    if status in {"manual_prompt_ready", "images_disabled", "fixture_system_sketch", "generated_live"}:
        return None
    if "missing_key" in status:
        return "auth"
    if "paid_provider_blocked" in status or "spend_limit" in status or "quota" in status:
        return "quota"
    if "timeout" in status:
        return "timeout"
    if "no_image" in status or "no_result" in status or "no_polling" in status or "not_image" in status:
        return "no_artifact"
    if "template_invalid" in status or "response_too_large" in status:
        return "bad_request"
    return "network"


# HERO-01 / GATE-03 — artifact-typed subject + composition lines. The image prompt is
# the ONLY place artifact_type changes the *image* (RESEARCH C1: we do NOT rewrite
# pack["image_direction"], which is a deterministic lane fact — GATE-03 is delivered
# through the PROMPT). Each entry branches the opening subject line and the composition
# line; the honesty rules ("no fake brand logos, no raw archive media, no lorem ipsum")
# and the "use the current brief only" fence are appended UNCHANGED for every type
# (Pitfall 2 prompt-injection; HERO-04). `generic` is the verbatim pre-4.5 framing.
_ARTIFACT_PROMPT_FRAMES: dict[str, tuple[str, str]] = {
    "website": (
        "Create one text-free public website/product scene for a London Osei route.",
        "Composition: one large mostly wordless full-page web frame in context (hero image area, nav shapes, stacked blank content blocks, product photography/material detail, and one tactile usage moment). Use schematic blocks and icons instead of text. No readable paragraphs, tables, metrics, labels, or dashboard copy. Keep London prose and supporting proof outside the generated image.",
    ),
    "app": (
        "Create one text-free public app/tool scene for a London Osei route.",
        "Composition: one large mostly wordless product/app screen in a device or desktop frame, paired with a concrete object/hand/context cue. Show a single visual state using icons, dials, blank cards, schematic modules, photography, material detail, and one tactile usage moment. No readable dashboards, tables, numbers, price cards, batch cards as text, UI labels, or fake copy. Keep London prose and supporting proof outside the generated image.",
    ),
    "product": (
        "Create one text-free public product/object scene for a London Osei route.",
        "Composition: one large photographed product/object system in use, with packaging or vessel structure, material, form, closure, texture, real scale, and one human gesture. Use blank panels, symbolic marks, embossing, color fields, or material seams instead of readable brand labels. No type sheets, fake labels, dense packaging copy, price cards, or logo-forward mockups. Keep London prose and supporting proof outside the generated image.",
    ),
    "brand": (
        "Create one text-free public applied identity scene for a London Osei route.",
        "Composition: one applied brand scene with a simple non-readable symbol/mark, product/signage/application context, non-text swatches, material surfaces, and one tactile usage moment. No logo specimen sheets, fake brand labels, alphabets, typography boards, or dense identity-system panels. Keep London prose and supporting proof outside the generated image.",
    ),
    "generic": (
        "Create one text-free public object/interface/service scene for a London Osei route.",
        "Composition: one large route-specific object, interface, paper, or service artifact in context with physical scale, non-text swatches, simple visual states, and one tactile usage moment. Use blank cards, schematic blocks, symbolic marks, and material detail instead of readable labels. Keep London prose and supporting proof outside the generated image.",
    ),
}


_PUBLIC_PROOF_TEXT_DISCIPLINE = (
    "Public proof text discipline: make the bitmap text-free by default. Do not typeset "
    "London's route title, headline, rationale, type direction, section titles, source names, "
    "brief text, or pack title. Do not render dense UI copy, readable dashboards, dense tables, "
    "fake alphabets, font specimen sheets, price tables, tiny labels, receipt/provider/source "
    "notes, hashes, prompt text, or palette hex codes as visible text. Use blank bars, schematic "
    "blocks, iconography, color/material swatches, symbolic marks, and photographic/object detail "
    "instead. Do not render numbers, currency symbols, column headings, chart labels, card labels, "
    "or dashboard labels. If the provider insists on lettering, it must be abstract/non-readable; "
    "leave all London prose, metadata, and proof copy outside the generated image."
)


def build_image_prompt(
    pack: Mapping[str, Any],
    route: Mapping[str, Any],
    *,
    artifact_type: str = "generic",
) -> str:
    """Build a route-specific image prompt from London decisions and evidence.

    ``artifact_type`` is read AS GIVEN from the pack by the caller (no renderer-side
    re-derivation; GATE-03) and branches only the subject + composition lines. An
    unknown type degrades to the honest ``generic`` framing — the honesty rules and the
    brief-only fence are identical in every branch (HERO-01 / HERO-04).
    """

    title = display_text(route.get("title"), fallback="London route")
    headline = display_text(route.get("headline") or route.get("rationale"), fallback=title)
    rationale = _compact_words(display_text(route.get("rationale") or route.get("subhead"), fallback=headline), limit=36)
    brief = _brief_image_context(pack)
    palette = "; ".join(
        f"{color['role']} {color['hex']}" for color in normalize_palette(route.get("palette"))
    )
    type_note = display_text(route.get("type") or _nested(pack, "typography_color", "type_system"))
    visual_cues = _section_visual_cues(route)
    brain_lines = _brain_prompt_lines(pack)
    source_lines = _source_prompt_lines(pack)
    avoid = "; ".join(_as_strings(route.get("do_not_copy"), fallback=("Do not copy source layouts, logos, or exact visual identity.",)))

    subject_line, composition_line = _ARTIFACT_PROMPT_FRAMES.get(
        artifact_type, _ARTIFACT_PROMPT_FRAMES["generic"]
    )

    return "\n".join(
        line
        for line in (
            subject_line,
            "Use the current brief only; do not borrow route names, project identities, or visuals from other briefs.",
            "Visible text rule overrides every brief, route, rationale, section, source, and evidence note below.",
            f"Private brief context for subject/category only; never copy these words into the image: {brief}",
            f"Allowed visible words: none. The route title is private direction only, not lettering for the bitmap: {title}",
            f"Private route thesis for mood only; do not render this as text or headline: {headline}",
            f"Private London rationale; translate into materials, hierarchy, framing, and gesture, not words: {rationale}",
            f"Palette/material cues; use as color, surface, lighting, and object detail, not hex labels: {palette}",
            f"Typography mood; use scale, rhythm, and weight contrast only, not specimen alphabets or font labels: {type_note}",
            f"Private interaction cues; show as unlabeled objects, abstract controls, blank cards, blank rows, and simple shapes: {visual_cues}",
            f"Private London brain findings to translate into visual taste only, not visible text: {brain_lines}",
            f"Private Source principles to respect; use composition ideas only, not names, labels, or source copy: {source_lines}",
            f"Private avoid constraints; do not render these words: {avoid}",
            composition_line,
            _PUBLIC_PROOF_TEXT_DISCIPLINE,
            "Style: public design-gallery evidence, photographed or interface-real, high-fidelity enough to guide a builder, no generic AI mockup defaults, no beige product-on-plinth default, no fake brand logos, no raw archive media, no lorem ipsum.",
        )
        if line.strip()
    )


def _manual_prompt_result(
    request: ImageGenerationRequest,
    prompt: str,
    *,
    status: str,
    failure: str | None = None,
    request_config: Mapping[str, Any] | None = None,
    attempted_request_configs: Sequence[Mapping[str, Any]] | None = None,
    model: str = "london-visual-direction-board",
    error_class: str | None = None,
) -> ImageGenerationResult:
    route = request.route
    route_title = display_text(route.get("title"), fallback=f"Route {request.route_index}")
    route_id = _route_id(route, request.route_index)
    caption = (
        "No ready image provider was used. London rendered a visual direction board from the route's palette, type, composition, prompt, and evidence cues. It is not generated concept art."
        if request.requested_provider in {"auto", "manual-prompt", "local"}
        else f"{request.requested_provider} image generation was requested, but no ready image was returned. London rendered an honest visual direction board instead."
    )
    palette = normalize_palette(route.get("palette"))
    brain_cues = [item["title"] for item in _brain_evidence(request.pack) if item.get("title")]
    source_cues = [item["title"] for item in _source_evidence(request.pack) if item.get("title")]
    asset = {
        "id": f"{route_id}-visual-direction-board",
        "title": f"{route_title} visual direction board",
        "alt": f"{route_title} visual direction board, not generated concept art",
        "caption": caption,
        "kind": "visual-direction-board",
        "src": visual_direction_board_data_uri(
            route_title,
            prompt,
            palette,
            type_note=display_text(route.get("type"), fallback="Route-specific type system."),
            brain_cues=brain_cues,
            source_cues=source_cues,
        ),
        "provider": "manual-prompt",
        "requested_provider": request.requested_provider,
        "resolved_provider": request.resolved_provider,
        "generation_status": status,
        "generation_mode": "visual-direction-board",
        "model": "london-visual-direction-board",
        "receipt_id": f"{route_id}-image-generation",
        "prompt": prompt,
        "prompt_ref": f"prompt:{route_id}:image",
        "copy_label": "Copy board prompt",
        "evidence_class": "Visual Direction Board",
        "board_sections": ["palette swatches", "type specimen", "composition grid", "route prompt", "brain cues", "source cues"],
        "deterministic": True,
        "live_artifact": False,
    }
    receipt = _receipt(
        request,
        prompt,
        provider="manual-prompt",
        model=model or "london-visual-direction-board",
        status=status,
        deterministic=True,
        summary=(
            f"Rendered an honest visual direction board for {route_title}; no generated concept image artifact was claimed."
            if request.requested_provider in {"auto", "manual-prompt", "local"}
            else f"Requested {request.requested_provider} image generation for {route_title}, then rendered a visual direction board because that lane was unavailable."
        ),
        failure=failure,
        request_config=request_config,
        attempted_request_configs=attempted_request_configs,
        error_class=error_class or _provider_error_class(status),
    )
    return ImageGenerationResult(asset=asset, receipt=receipt)


def _unavailable_result(
    request: ImageGenerationRequest,
    prompt: str,
    *,
    status: str,
) -> ImageGenerationResult:
    result = _manual_prompt_result(request, prompt, status=status)
    result.asset.update(
        {
            "caption": "Image generation was disabled for this run. London kept a visual direction board and route prompt without claiming generated concept art.",
            "generation_status": status,
            "provider": "none",
        }
    )
    result.receipt["provider"] = "none"
    result.receipt["status"] = status
    result.receipt["summary"] = "Image generation was disabled; London kept a visual direction board and route prompt for handoff only."
    return result


def _fixture_result(
    request: ImageGenerationRequest,
    prompt: str,
    *,
    status: str,
) -> ImageGenerationResult:
    route = request.route
    route_title = display_text(route.get("title"), fallback=f"Route {request.route_index}")
    route_id = _route_id(route, request.route_index)
    asset = fallback_asset(
        f"{route_title} Fixture System Sketch",
        display_text(route.get("rationale") or route.get("headline"), fallback="Explicit fixture sketch."),
        route.get("palette"),
        kind="fixture-system-sketch",
    )
    asset.update(
        {
            "id": f"{route_id}-fixture-system-sketch",
            "title": f"{route_title} fixture system sketch",
            "alt": f"{route_title} deterministic fixture concept sketch",
            "caption": "Explicit fixture-mode SVG sketch. Not a provider-generated concept image.",
            "kind": "fixture-system-sketch",
            "provider": "fixture",
            "requested_provider": request.requested_provider,
            "resolved_provider": request.resolved_provider,
            "generation_status": status,
            "generation_mode": "fixture",
            "model": "london-fixture-svg",
            "receipt_id": f"{route_id}-image-generation",
            "prompt": prompt,
            "prompt_ref": f"prompt:{route_id}:image",
            "evidence_class": "Fixture",
            "deterministic": True,
            "live_artifact": False,
        }
    )
    receipt = _receipt(
        request,
        prompt,
        provider="fixture-renderer",
        model="london-fixture-svg",
        status=status,
        deterministic=True,
        summary=f"Rendered an explicit fixture SVG sketch for {route_title}; no provider-backed image artifact was claimed.",
    )
    return ImageGenerationResult(asset=asset, receipt=receipt)


def _external_cmd_result(
    request: ImageGenerationRequest,
    prompt: str,
    env: Mapping[str, str],
) -> ImageGenerationResult:
    command_template = env.get("LONDON_EXTERNAL_IMAGE_COMMAND") or env.get("LONDON_LOCAL_IMAGE_COMMAND")
    if not command_template:
        raise ProviderUnavailable("fallback_missing_external_command")
    return _local_command_result(
        request,
        prompt,
        env,
        command_template=command_template,
        provider="external-cmd",
        model_prefix="local-command",
        missing_command_status="fallback_missing_external_command",
    )


def _draw_things_result(
    request: ImageGenerationRequest,
    prompt: str,
    env: Mapping[str, str],
) -> ImageGenerationResult:
    command_template = env.get("LONDON_DRAW_THINGS_COMMAND")
    if not command_template:
        raise ProviderUnavailable("fallback_missing_draw_things_command")
    cli = env.get("LONDON_DRAW_THINGS_CLI") or shutil.which("draw-things-cli") or shutil.which("draw-things")
    if "{cli}" in command_template and not cli:
        raise ProviderUnavailable("fallback_missing_draw_things_cli")
    return _local_command_result(
        request,
        prompt,
        env,
        command_template=command_template,
        provider="draw-things",
        model_prefix="draw-things",
        missing_command_status="fallback_missing_draw_things_command",
        placeholders={"cli": shlex.quote(str(cli or ""))},
    )


def _local_command_result(
    request: ImageGenerationRequest,
    prompt: str,
    env: Mapping[str, str],
    *,
    command_template: str,
    provider: str,
    model_prefix: str,
    missing_command_status: str,
    placeholders: Mapping[str, str] | None = None,
) -> ImageGenerationResult:
    timeout = _env_float(env, "LONDON_EXTERNAL_IMAGE_TIMEOUT", 180.0)
    extension = (env.get("LONDON_EXTERNAL_IMAGE_EXTENSION") or "png").strip().lstrip(".") or "png"
    parent_dir = Path(env["LONDON_EXTERNAL_IMAGE_OUTPUT_DIR"]) if env.get("LONDON_EXTERNAL_IMAGE_OUTPUT_DIR") else None
    if parent_dir is not None:
        parent_dir.mkdir(parents=True, exist_ok=True)
    route_id = _route_id(request.route, request.route_index)

    with TemporaryDirectory(dir=str(parent_dir) if parent_dir else None) as work_dir_name:
        work_dir = Path(work_dir_name)
        prompt_file = work_dir / "prompt.txt"
        output_path = work_dir / f"{route_id}.{extension}"
        prompt_file.write_text(prompt, encoding="utf-8")
        try:
            command = command_template.format(
                prompt=shlex.quote(prompt),
                prompt_file=shlex.quote(str(prompt_file)),
                output=shlex.quote(str(output_path)),
                output_dir=shlex.quote(str(work_dir)),
                route_id=shlex.quote(route_id),
                **dict(placeholders or {}),
            )
        except (IndexError, KeyError, ValueError) as exc:
            raise ProviderUnavailable("fallback_external_command_template_invalid") from exc
        argv = shlex.split(command)
        if not argv:
            raise ProviderUnavailable(missing_command_status)
        try:
            completed = subprocess.run(  # noqa: S603 - explicit user-configured local command
                argv,
                cwd=work_dir,
                timeout=timeout,
                check=False,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProviderUnavailable("fallback_external_command_failed") from exc
        if completed.returncode != 0:
            raise ProviderUnavailable("fallback_external_command_failed")
        image_path = _external_output_path(output_path, work_dir, env)
        image = _read_local_image(image_path)
        command_name = Path(argv[0]).name or "external-cmd"
        result = _live_result(
            request,
            prompt,
            provider=provider,
            model=f"{model_prefix}:{command_name}",
            image_data=image,
        )
        result.receipt["external_command"] = {
            "name": command_name,
            "output_path_printed": False,
            "prompt_file_printed": False,
        }
        return result


def _automatic1111_result(
    request: ImageGenerationRequest,
    prompt: str,
    env: Mapping[str, str],
) -> ImageGenerationResult:
    base_url = (env.get("LONDON_AUTOMATIC1111_URL") or "http://127.0.0.1:7860").rstrip("/")
    payload = {
        "prompt": prompt,
        "negative_prompt": "logo theft, lorem ipsum, copied brand identity, raw archive image, blurry generic moodboard",
        "width": 1216,
        "height": 832,
        "steps": _env_int(env, "LONDON_AUTOMATIC1111_STEPS", 24),
        "cfg_scale": _env_float(env, "LONDON_AUTOMATIC1111_CFG_SCALE", 6.5),
    }
    data = _post_json(
        f"{base_url}/sdapi/v1/txt2img",
        payload,
        headers={"Content-Type": "application/json"},
        timeout=180,
        env=env,
    )
    images = data.get("images") if isinstance(data.get("images"), list) else []
    image_base64 = images[0] if images else ""
    if not image_base64:
        raise ProviderUnavailable("fallback_no_image_returned")
    return _live_result(
        request,
        prompt,
        provider="automatic1111",
        model=_automatic1111_model(data.get("info")),
        image_data={"mime_type": "image/png", "data": str(image_base64)},
        request_config={
            "endpoint": "/sdapi/v1/txt2img",
            "width": payload["width"],
            "height": payload["height"],
            "steps": payload["steps"],
            "cfg_scale": payload["cfg_scale"],
        },
    )


def _automatic1111_model(info: Any) -> str:
    if isinstance(info, str):
        try:
            parsed = json.loads(info)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, Mapping):
            checkpoint = display_text(parsed.get("sd_model_checkpoint"))
            if checkpoint:
                return checkpoint
    if isinstance(info, Mapping):
        checkpoint = display_text(info.get("sd_model_checkpoint"))
        if checkpoint:
            return checkpoint
    return "stable-diffusion-webui"


def _comfyui_result(
    request: ImageGenerationRequest,
    prompt: str,
    env: Mapping[str, str],
) -> ImageGenerationResult:
    workflow_path = env.get("LONDON_COMFYUI_WORKFLOW")
    if not workflow_path:
        raise ProviderUnavailable("fallback_missing_workflow")
    path = os.fspath(workflow_path)
    if not os.path.exists(path):
        raise ProviderUnavailable("fallback_missing_workflow")
    base_url = (env.get("LONDON_COMFYUI_URL") or "http://127.0.0.1:8188").rstrip("/")
    workflow = _load_comfyui_workflow(path, prompt)
    data = _post_json(
        f"{base_url}/prompt",
        {"prompt": workflow},
        headers={"Content-Type": "application/json"},
        timeout=120,
        env=env,
    )
    image = _extract_direct_image(data)
    if image is None:
        prompt_id = display_text(data.get("prompt_id") or data.get("id"))
        if prompt_id:
            image = _poll_comfyui(base_url, prompt_id, env)
    if image is None:
        raise ProviderUnavailable("fallback_no_image_returned")
    model = (
        env.get("LONDON_COMFYUI_MODEL_FAMILY")
        or env.get("LONDON_COMFYUI_MODEL_PROFILE")
        or env.get("LONDON_COMFYUI_PROFILE")
        or "configured-workflow"
    )
    request_config = _comfyui_request_config(base_url, path, env, model=model)
    return _live_result(
        request,
        prompt,
        provider="comfyui",
        model=model,
        image_data=image,
        request_config=request_config,
    )


def _gemini_result(
    request: ImageGenerationRequest,
    prompt: str,
    env: Mapping[str, str],
) -> ImageGenerationResult:
    api_key = env.get("GEMINI_API_KEY") or env.get("GOOGLE_API_KEY")
    if not api_key:
        raise ProviderUnavailable("fallback_missing_key")
    _raise_if_spend_blocked(request, "gemini")

    model = env.get("LONDON_GEMINI_IMAGE_MODEL") or "gemini-3-pro-image-preview"
    api_version = env.get("LONDON_GEMINI_API_VERSION") or _default_gemini_api_version(model)
    url = f"https://generativelanguage.googleapis.com/{api_version}/models/{model}:generateContent"
    attempts = _gemini_request_attempts(prompt, model=model, api_version=api_version, env=env)
    attempted_request_configs: list[dict[str, Any]] = []
    last_failure = ""
    data: dict[str, Any] | None = None
    request_config: dict[str, Any] = attempts[0][1]
    skip_enum_retry = False
    for payload, safe_config in attempts:
        if skip_enum_retry and safe_config.get("payload_mode") == "generation_config_enum_retry":
            continue
        attempted_request_configs.append(dict(safe_config))
        request_config = dict(safe_config)
        try:
            data = _post_json(
                url,
                payload,
                headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
                timeout=120,
                env=env,
            )
            break
        except urllib.error.HTTPError as exc:
            last_failure = _scrub_error(exc, env)
            if exc.code == 400 and _gemini_unknown_generation_config_error(last_failure):
                skip_enum_retry = True
                continue
            if exc.code == 400 and _gemini_image_config_enum_error(last_failure):
                continue
            raise ProviderUnavailable(
                "fallback_provider_error",
                failure=last_failure,
                request_config=request_config,
                attempted_request_configs=attempted_request_configs,
                model=model,
                error_class=_provider_error_class(exc),
            ) from None

    if data is None:
        raise ProviderUnavailable(
            "fallback_provider_error",
            failure=last_failure,
            request_config=request_config,
            attempted_request_configs=attempted_request_configs,
            model=model,
        )
    image = _extract_gemini_image(data)
    if image is None:
        raise ProviderUnavailable(
            "fallback_no_image_returned",
            request_config=request_config,
            attempted_request_configs=attempted_request_configs,
            model=model,
        )
    return _live_result(
        request,
        prompt,
        provider="gemini",
        model=model,
        image_data=image,
        request_config=request_config,
        attempted_request_configs=attempted_request_configs,
    )


def _gemini_request_attempts(
    prompt: str,
    *,
    model: str,
    api_version: str,
    env: Mapping[str, str],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    minimal_payload = {"contents": [{"parts": [{"text": prompt}]}]}
    minimal_config = {
        "api_version": api_version,
        "endpoint": f"/{api_version}/models/{model}:generateContent",
        "payload_mode": "minimal",
    }
    configured_payload = dict(minimal_payload)
    response_modalities = _csv_env(env, "LONDON_GEMINI_RESPONSE_MODALITIES", fallback=())
    aspect_ratio = display_text(env.get("LONDON_GEMINI_IMAGE_ASPECT_RATIO") or "16:9")
    image_size = display_text(env.get("LONDON_GEMINI_IMAGE_SIZE") or _default_gemini_image_size(model))
    image_config: dict[str, str] = {"aspectRatio": aspect_ratio}
    if image_size:
        image_config["imageSize"] = image_size
    generation_config: dict[str, Any] = {"responseFormat": {"image": image_config}}
    if response_modalities:
        generation_config["responseModalities"] = response_modalities
    configured_payload["generationConfig"] = generation_config
    configured_config = {
        "api_version": api_version,
        "endpoint": f"/{api_version}/models/{model}:generateContent",
        "payload_mode": "generation_config",
        "response_format": {"image": image_config},
    }
    if response_modalities:
        configured_config["response_modalities"] = response_modalities
    enum_image_config = _gemini_enum_image_config(aspect_ratio, image_size)
    enum_payload = dict(minimal_payload)
    enum_generation_config: dict[str, Any] = {"responseFormat": {"image": enum_image_config}}
    if response_modalities:
        enum_generation_config["responseModalities"] = response_modalities
    enum_payload["generationConfig"] = enum_generation_config
    enum_config = {
        "api_version": api_version,
        "endpoint": f"/{api_version}/models/{model}:generateContent",
        "payload_mode": "generation_config_enum_retry",
        "response_format": {"image": enum_image_config},
    }
    if response_modalities:
        enum_config["response_modalities"] = response_modalities
    mode = display_text(
        env.get("LONDON_GEMINI_REQUEST_CONFIG_MODE") or env.get("LONDON_GEMINI_GENERATION_CONFIG_MODE"),
        fallback=("configured" if "image" in model.lower() else "minimal"),
    ).strip().lower().replace("_", "-")
    if mode in {"configured", "generation-config", "full", "legacy"}:
        return [(configured_payload, configured_config), (enum_payload, enum_config), (minimal_payload, minimal_config)]
    if mode in {"compat", "fallback"}:
        return [(minimal_payload, minimal_config), (configured_payload, configured_config), (enum_payload, enum_config)]
    return [(minimal_payload, minimal_config)]


def _default_gemini_api_version(model: str) -> str:
    if model.endswith("-preview"):
        return "v1beta"
    return "v1"


def _default_gemini_image_size(model: str) -> str:
    if model.startswith("gemini-3-pro-image"):
        return "4K"
    if model.startswith("gemini-3.1-flash-image"):
        return "2K"
    return ""


def _gemini_enum_image_config(aspect_ratio: str, image_size: str) -> dict[str, str]:
    config = {"aspectRatio": _gemini_enum_aspect_ratio(aspect_ratio)}
    enum_size = _gemini_enum_image_size(image_size)
    if enum_size:
        config["imageSize"] = enum_size
    return config


def _gemini_enum_aspect_ratio(value: str) -> str:
    cleaned = display_text(value).strip()
    if cleaned.startswith("ASPECT_RATIO_"):
        return cleaned
    return {
        "1:1": "ASPECT_RATIO_ONE_BY_ONE",
        "2:3": "ASPECT_RATIO_TWO_BY_THREE",
        "3:2": "ASPECT_RATIO_THREE_BY_TWO",
        "3:4": "ASPECT_RATIO_THREE_BY_FOUR",
        "4:3": "ASPECT_RATIO_FOUR_BY_THREE",
        "4:5": "ASPECT_RATIO_FOUR_BY_FIVE",
        "5:4": "ASPECT_RATIO_FIVE_BY_FOUR",
        "9:16": "ASPECT_RATIO_NINE_BY_SIXTEEN",
        "16:9": "ASPECT_RATIO_SIXTEEN_BY_NINE",
        "21:9": "ASPECT_RATIO_TWENTY_ONE_BY_NINE",
        "1:8": "ASPECT_RATIO_ONE_BY_EIGHT",
        "8:1": "ASPECT_RATIO_EIGHT_BY_ONE",
        "1:4": "ASPECT_RATIO_ONE_BY_FOUR",
        "4:1": "ASPECT_RATIO_FOUR_BY_ONE",
    }.get(cleaned, cleaned)


def _gemini_enum_image_size(value: str) -> str:
    cleaned = display_text(value).strip()
    if not cleaned or cleaned.startswith("IMAGE_SIZE_"):
        return cleaned
    return {
        "512": "IMAGE_SIZE_FIVE_TWELVE",
        "1K": "IMAGE_SIZE_ONE_K",
        "2K": "IMAGE_SIZE_TWO_K",
        "4K": "IMAGE_SIZE_FOUR_K",
    }.get(cleaned.upper(), cleaned)


def _gemini_unknown_generation_config_error(message: str) -> bool:
    lowered = message.lower()
    return (
        "unknown name" in lowered
        and ("responsemodalities" in lowered or "responseformat" in lowered)
    )


def _gemini_image_config_enum_error(message: str) -> bool:
    message = message.lower()
    return (
        "invalid value" in message
        and "generation_config.response_format.image" in message
        and ("aspect_ratio" in message or "image_size" in message)
    )


def _bfl_result(
    request: ImageGenerationRequest,
    prompt: str,
    env: Mapping[str, str],
) -> ImageGenerationResult:
    api_key = env.get("BFL_API_KEY")
    if not api_key:
        raise ProviderUnavailable("fallback_missing_key")
    _raise_if_spend_blocked(request, "bfl")

    base_url = env.get("LONDON_BFL_BASE_URL") or "https://api.bfl.ai"
    model_path = env.get("LONDON_BFL_MODEL_PATH") or "/v1/flux-2-pro-preview"
    submit_url = base_url.rstrip("/") + "/" + model_path.strip("/")
    width = _env_int(env, "LONDON_BFL_IMAGE_WIDTH", 1536)
    height = _env_int(env, "LONDON_BFL_IMAGE_HEIGHT", 1024)
    payload = {"prompt": prompt, "width": width, "height": height}
    data = _post_json(
        submit_url,
        payload,
        headers={"Content-Type": "application/json", "x-key": api_key},
        timeout=60,
        env=env,
    )

    polling_url = data.get("polling_url") or data.get("pollingUrl")
    if not polling_url:
        raise ProviderUnavailable("fallback_no_polling_url")

    image_url = _poll_bfl(str(polling_url), api_key, env, submit_url=submit_url)
    image_bytes, mime_type = _get_bytes(image_url, timeout=60, env=env)

    image = {"mime_type": mime_type, "data": base64.b64encode(image_bytes).decode("ascii")}
    model = model_path.strip("/") or "flux-2-pro-preview"
    return _live_result(
        request,
        prompt,
        provider="bfl",
        model=model,
        image_data=image,
        request_config={
            "endpoint": "/" + model_path.strip("/"),
            "width": width,
            "height": height,
            "polling_url_used": True,
            "signed_result_url_stored": False,
        },
    )


def _openai_result(
    request: ImageGenerationRequest,
    prompt: str,
    env: Mapping[str, str],
) -> ImageGenerationResult:
    api_key = env.get("OPENAI_API_KEY")
    if not api_key:
        raise ProviderUnavailable("fallback_missing_key")
    _raise_if_spend_blocked(request, "openai")

    model = env.get("LONDON_OPENAI_IMAGE_MODEL") or "gpt-image-2"
    size = env.get("LONDON_OPENAI_IMAGE_SIZE") or "3840x2160"
    quality = env.get("LONDON_OPENAI_IMAGE_QUALITY") or "high"
    output_format = env.get("LONDON_OPENAI_IMAGE_OUTPUT_FORMAT") or ""
    background = env.get("LONDON_OPENAI_IMAGE_BACKGROUND") or ""
    moderation = env.get("LONDON_OPENAI_IMAGE_MODERATION") or ""
    payload = {"model": model, "prompt": prompt, "size": size, "quality": quality}
    if output_format:
        payload["output_format"] = output_format
    if env.get("LONDON_OPENAI_IMAGE_OUTPUT_COMPRESSION"):
        payload["output_compression"] = _env_int(env, "LONDON_OPENAI_IMAGE_OUTPUT_COMPRESSION", 0)
    if background:
        payload["background"] = background
    if moderation:
        payload["moderation"] = moderation
    data = _post_json(
        "https://api.openai.com/v1/images/generations",
        payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        timeout=120,
        env=env,
    )

    rows = data.get("data") if isinstance(data.get("data"), list) else []
    first = rows[0] if rows and isinstance(rows[0], Mapping) else {}
    image_base64 = first.get("b64_json")
    if not image_base64:
        raise ProviderUnavailable("fallback_no_image_returned")
    mime_type = _mime_type_for_format(output_format or "png")
    image = {"mime_type": mime_type, "data": image_base64}
    request_config: dict[str, Any] = {
        "endpoint": "/v1/images/generations",
        "size": size,
        "quality": quality,
        "output_format": output_format or "png",
    }
    if env.get("LONDON_OPENAI_IMAGE_OUTPUT_COMPRESSION"):
        request_config["output_compression"] = _env_int(env, "LONDON_OPENAI_IMAGE_OUTPUT_COMPRESSION", 0)
    if background:
        request_config["background"] = background
    if moderation:
        request_config["moderation"] = moderation
    return _live_result(
        request,
        prompt,
        provider="openai",
        model=model,
        image_data=image,
        request_config=request_config,
    )


def _fal_result(
    request: ImageGenerationRequest,
    prompt: str,
    env: Mapping[str, str],
) -> ImageGenerationResult:
    api_key = env.get("FAL_KEY") or env.get("FAL_API_KEY")
    if not api_key:
        raise ProviderUnavailable("fallback_missing_key")
    _raise_if_spend_blocked(request, "fal")
    model_url = env.get("LONDON_FAL_IMAGE_URL") or "https://fal.run/fal-ai/flux/dev"
    payload = {"prompt": prompt, "image_size": "landscape_4_3", "num_images": 1}
    data = _post_json(
        model_url,
        payload,
        headers={"Content-Type": "application/json", "Authorization": f"Key {api_key}"},
        timeout=120,
        env=env,
    )
    image = _extract_remote_image(data, env)
    if image is None:
        raise ProviderUnavailable("fallback_no_image_returned")
    return _live_result(
        request,
        prompt,
        provider="fal",
        model=model_url.rsplit("/", 1)[-1],
        image_data=image,
        request_config={"endpoint": urllib.parse.urlparse(model_url).path or model_url, "image_size": "landscape_4_3"},
    )


def _replicate_result(
    request: ImageGenerationRequest,
    prompt: str,
    env: Mapping[str, str],
) -> ImageGenerationResult:
    api_key = env.get("REPLICATE_API_TOKEN") or env.get("REPLICATE_API_KEY")
    if not api_key:
        raise ProviderUnavailable("fallback_missing_key")
    _raise_if_spend_blocked(request, "replicate")
    model_url = env.get("LONDON_REPLICATE_MODEL_URL") or "https://api.replicate.com/v1/models/black-forest-labs/flux-schnell/predictions"
    payload = {"input": {"prompt": prompt, "aspect_ratio": "4:3", "output_format": "png"}}
    data = _post_json(
        model_url,
        payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        timeout=90,
        env=env,
    )
    image = _extract_remote_image(data, env)
    if image is None:
        data = _poll_replicate(data, api_key, env, submit_url=model_url)
        image = _extract_remote_image(data, env)
    if image is None:
        raise ProviderUnavailable("fallback_no_image_returned")
    return _live_result(
        request,
        prompt,
        provider="replicate",
        model="flux-schnell",
        image_data=image,
        request_config={"endpoint": urllib.parse.urlparse(model_url).path or model_url, "aspect_ratio": "4:3", "output_format": "png"},
    )


def _pollinations_result(
    request: ImageGenerationRequest,
    prompt: str,
    env: Mapping[str, str],
) -> ImageGenerationResult:
    spend_policy = request.spend_policy or {}
    config_allowed = bool(spend_policy.get("allow_experimental_free_network", False))
    env_allowed = str(env.get("LONDON_ALLOW_POLLINATIONS") or "").strip().lower() in {"1", "true", "yes"}
    if not (config_allowed or env_allowed):
        raise ProviderUnavailable("fallback_experimental_network_disabled")
    encoded = urllib.parse.quote(prompt[:1800])
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1216&height=832&nologo=true&private=true"
    image_bytes, mime_type = _get_bytes(url, timeout=120, env=env)
    image = {"mime_type": mime_type, "data": base64.b64encode(image_bytes).decode("ascii")}
    return _live_result(
        request,
        prompt,
        provider="pollinations",
        model="pollinations",
        image_data=image,
        request_config={"endpoint": "/prompt", "width": 1216, "height": 832, "prompt_chars": min(len(prompt), 1800)},
    )


def _live_result(
    request: ImageGenerationRequest,
    prompt: str,
    *,
    provider: str,
    model: str,
    image_data: Mapping[str, str],
    request_config: Mapping[str, Any] | None = None,
    attempted_request_configs: Sequence[Mapping[str, Any]] | None = None,
) -> ImageGenerationResult:
    route = request.route
    route_title = display_text(route.get("title"), fallback=f"Route {request.route_index}")
    route_id = _route_id(route, request.route_index)
    mime_type = image_data.get("mime_type") or "image/png"
    data = image_data["data"]
    asset = {
        "id": f"{route_id}-{provider}-concept",
        "title": f"{route_title} generated concept",
        "alt": f"{route_title} provider-generated concept image",
        "caption": f"Provider-backed concept image generated from London route evidence via {provider}.",
        "kind": "generated-concept-image",
        "src": f"data:{mime_type};base64,{data}",
        "provider": provider,
        "requested_provider": request.requested_provider,
        "resolved_provider": request.resolved_provider,
        "generation_status": "generated_live",
        "generation_mode": "provider-backed",
        "model": model,
        "receipt_id": f"{route_id}-image-generation",
        "prompt": prompt,
        "prompt_ref": f"prompt:{route_id}:image",
        "evidence_class": "Live Artifact",
        "deterministic": False,
        "live_artifact": True,
    }
    receipt = _receipt(
        request,
        prompt,
        provider=provider,
        model=model,
        status="generated_live",
        deterministic=False,
        summary=f"Generated a provider-backed route concept image for {route_title}.",
        request_config=request_config,
        attempted_request_configs=attempted_request_configs,
    )
    return ImageGenerationResult(asset=asset, receipt=receipt)


def _receipt(
    request: ImageGenerationRequest,
    prompt: str,
    *,
    provider: str,
    model: str,
    status: str,
    deterministic: bool,
    summary: str,
    generation_mode: str | None = None,
    failure: str | None = None,
    request_config: Mapping[str, Any] | None = None,
    attempted_request_configs: Sequence[Mapping[str, Any]] | None = None,
    error_class: str | None = None,
) -> dict[str, Any]:
    route = request.route
    route_id = _route_id(route, request.route_index)
    receipt: dict[str, Any] = {
        "receipt_id": f"{route_id}-image-generation",
        "kind": "image-generation",
        "summary": summary,
        "provider": provider,
        "requested_provider": request.requested_provider,
        "resolved_provider": request.resolved_provider,
        "fallback_chain": [dict(item) for item in request.fallback_chain],
        "selection_reason": request.selection_reason,
        "spend_policy": dict(request.spend_policy or {}),
        "model": model,
        "route_id": route_id,
        "route_title": display_text(route.get("title"), fallback=f"Route {request.route_index}"),
        "status": status,
        "generation_mode": generation_mode or ("provider-backed" if status == "generated_live" else "offline"),
        "deterministic": deterministic,
        "secrets_printed": False,
        "prompt": prompt,
        "prompt_ref": f"prompt:{route_id}:image",
        "evidence_used": {
            "brain_findings": _brain_evidence(request.pack),
            "source_principles": _source_evidence(request.pack),
        },
    }
    receipt["request_config"] = dict(request_config or {"endpoint": provider})
    receipt["attempted_request_configs"] = [
        dict(item) for item in (attempted_request_configs or [receipt["request_config"]])
    ]
    if failure:
        receipt["failure"] = failure
    if error_class:
        receipt["error_class"] = error_class
    spend_policy = request.spend_policy if isinstance(request.spend_policy, Mapping) else {}
    if spend_policy.get("estimated_cost_usd") is not None:
        receipt["estimated_cost_usd"] = spend_policy.get("estimated_cost_usd")
    return receipt


def _csv_env(env: Mapping[str, str], key: str, *, fallback: Sequence[str]) -> list[str]:
    raw = env.get(key)
    if not raw:
        return list(fallback)
    values = [item.strip() for item in raw.split(",")]
    return [item for item in values if item] or list(fallback)


def _mime_type_for_format(output_format: str) -> str:
    normalized = output_format.strip().lower()
    if normalized in {"jpg", "jpeg"}:
        return "image/jpeg"
    if normalized == "webp":
        return "image/webp"
    return "image/png"


def _external_output_path(output_path: Path, work_dir: Path, env: Mapping[str, str]) -> Path:
    configured = env.get("LONDON_EXTERNAL_IMAGE_RESULT")
    candidates = [Path(configured)] if configured else []
    candidates.append(output_path)
    candidates.extend(
        path for path in work_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
    )
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    raise ProviderUnavailable("fallback_no_image_returned")


def _read_local_image(path: Path) -> dict[str, str]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ProviderUnavailable("fallback_no_image_returned") from exc
    if not payload:
        raise ProviderUnavailable("fallback_no_image_returned")
    mime_type = _local_image_mime_type(payload, path)
    if mime_type is None:
        raise ProviderUnavailable("fallback_external_output_not_image")
    return {"mime_type": mime_type, "data": base64.b64encode(payload).decode("ascii")}


def _local_image_mime_type(payload: bytes, path: Path) -> str | None:
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if payload.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return "image/webp"
    if payload.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if path.suffix.lower() == ".svg" and b"<svg" in payload[:512].lower():
        return "image/svg+xml"
    return None


def _poll_bfl(polling_url: str, api_key: str, env: Mapping[str, str], *, submit_url: str) -> str:
    max_polls = _env_int(env, "LONDON_BFL_MAX_POLLS", 45)
    poll_interval = _poll_seconds(env, "LONDON_BFL_POLL_SECONDS", 2.0)
    for _ in range(max_polls):
        data = _get_json(
            polling_url,
            headers={"x-key": api_key},
            timeout=30,
            env=env,
            credential_origin=submit_url,
        )
        status = str(data.get("status") or "").lower()
        if status == "ready":
            result = data.get("result") if isinstance(data.get("result"), Mapping) else {}
            sample = result.get("sample") or result.get("url")
            if sample:
                return str(sample)
            raise ProviderUnavailable("fallback_no_result_url")
        if status in {"error", "failed"}:
            raise ProviderUnavailable("fallback_provider_error")
        time.sleep(poll_interval)
    raise ProviderUnavailable("fallback_provider_timeout")


def _load_comfyui_workflow(path: str, prompt: str) -> Any:
    with open(path, encoding="utf-8") as workflow_file:  # noqa: PTH123 - user-configured workflow path
        workflow = json.load(workflow_file)
    return _replace_prompt_placeholder(workflow, prompt)


def _comfyui_request_config(
    base_url: str,
    workflow_path: str | Path,
    env: Mapping[str, str],
    *,
    model: str,
) -> dict[str, Any]:
    profile = env.get("LONDON_COMFYUI_MODEL_PROFILE") or env.get("LONDON_COMFYUI_PROFILE") or "custom-workflow"
    checkpoints = env.get("LONDON_COMFYUI_CHECKPOINTS") or ""
    return {
        "base_url": _redacted_local_url(base_url),
        "workflow_sha256": _file_sha256(workflow_path),
        "workflow_name": Path(workflow_path).name,
        "model_profile": profile,
        "model_family": model,
        "license_posture": env.get("LONDON_COMFYUI_LICENSE_POSTURE") or "user-supplied-workflow",
        "commercial_use": env.get("LONDON_COMFYUI_COMMERCIAL_USE") or "unknown",
        "checkpoint_count": len([item for item in checkpoints.split(",") if item.strip()]),
    }


def _file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _redacted_local_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return value.split("/", 1)[0]
    host = parsed.hostname or ""
    if not host:
        return urllib.parse.urlunsplit((parsed.scheme, "", "", "", ""))
    netloc = host
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urllib.parse.urlunsplit((parsed.scheme, netloc, "", "", ""))


def _replace_prompt_placeholder(value: Any, prompt: str) -> Any:
    if isinstance(value, str):
        return value.replace("{{prompt}}", prompt)
    if isinstance(value, list):
        return [_replace_prompt_placeholder(item, prompt) for item in value]
    if isinstance(value, Mapping):
        return {
            str(key).replace("{{prompt}}", prompt): _replace_prompt_placeholder(item, prompt)
            for key, item in value.items()
        }
    return value


def _poll_comfyui(base_url: str, prompt_id: str, env: Mapping[str, str]) -> dict[str, str] | None:
    max_polls = _env_int(env, "LONDON_COMFYUI_MAX_POLLS", 45)
    poll_interval = _poll_seconds(env, "LONDON_COMFYUI_POLL_SECONDS", 1.0)
    history_url = f"{base_url}/history/{urllib.parse.quote(prompt_id)}"
    for _ in range(max_polls):
        data = _get_json(history_url, timeout=30, env=env)
        image = _extract_direct_image(data)
        if image is not None:
            return image
        image_ref = _extract_comfyui_image_ref(data, prompt_id)
        if image_ref is not None:
            return _fetch_comfyui_image(base_url, image_ref, env)
        time.sleep(poll_interval)
    raise ProviderUnavailable("fallback_provider_timeout")


def _extract_comfyui_image_ref(data: Mapping[str, Any], prompt_id: str) -> Mapping[str, Any] | None:
    histories: list[Mapping[str, Any]] = []
    prompt_history = data.get(prompt_id)
    if isinstance(prompt_history, Mapping):
        histories.append(prompt_history)
    if isinstance(data.get("outputs"), Mapping):
        histories.append(data)
    for history in histories:
        outputs = history.get("outputs") if isinstance(history.get("outputs"), Mapping) else {}
        for node in outputs.values():
            if not isinstance(node, Mapping):
                continue
            for image in _as_mappings(node.get("images")):
                if image.get("filename"):
                    return image
    return None


def _fetch_comfyui_image(base_url: str, image_ref: Mapping[str, Any], env: Mapping[str, str]) -> dict[str, str]:
    query = urllib.parse.urlencode(
        {
            "filename": display_text(image_ref.get("filename")),
            "subfolder": display_text(image_ref.get("subfolder")),
            "type": display_text(image_ref.get("type"), fallback="output"),
        }
    )
    image_bytes, mime_type = _get_bytes(f"{base_url}/view?{query}", timeout=60, env=env)
    return {"mime_type": mime_type, "data": base64.b64encode(image_bytes).decode("ascii")}


def _poll_replicate(data: Mapping[str, Any], api_key: str, env: Mapping[str, str], *, submit_url: str) -> Mapping[str, Any]:
    current: Mapping[str, Any] = data
    max_polls = _env_int(env, "LONDON_REPLICATE_MAX_POLLS", 60)
    poll_interval = _poll_seconds(env, "LONDON_REPLICATE_POLL_SECONDS", 1.0)
    for _ in range(max_polls):
        status = display_text(current.get("status")).lower()
        if status in {"succeeded", "completed"}:
            return current
        if status in {"failed", "canceled", "cancelled"}:
            raise ProviderUnavailable("fallback_provider_error")
        urls = current.get("urls") if isinstance(current.get("urls"), Mapping) else {}
        get_url = display_text(urls.get("get"))
        if not get_url:
            return current
        time.sleep(poll_interval)
        current = _get_json(
            get_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60,
            env=env,
            credential_origin=submit_url,
        )
    raise ProviderUnavailable("fallback_provider_timeout")


def _extract_gemini_image(data: Mapping[str, Any]) -> dict[str, str] | None:
    for candidate in _as_mappings(data.get("candidates")):
        content = candidate.get("content") if isinstance(candidate.get("content"), Mapping) else {}
        for part in _as_mappings(content.get("parts")):
            inline = part.get("inlineData") or part.get("inline_data")
            if not isinstance(inline, Mapping):
                continue
            raw_data = inline.get("data")
            if raw_data:
                return {
                    "mime_type": display_text(inline.get("mimeType") or inline.get("mime_type"), fallback="image/png"),
                    "data": str(raw_data),
                }
    return None


def _extract_direct_image(data: Mapping[str, Any]) -> dict[str, str] | None:
    for key in ("image", "image_base64", "b64_json"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return {"mime_type": "image/png", "data": value}
    images = data.get("images") if isinstance(data.get("images"), list) else []
    first = images[0] if images else None
    if isinstance(first, str) and first:
        return {"mime_type": "image/png", "data": first}
    if isinstance(first, Mapping):
        value = first.get("b64_json") or first.get("data")
        if value:
            return {
                "mime_type": display_text(first.get("mime_type") or first.get("mimeType"), fallback="image/png"),
                "data": str(value),
            }
    return None


def _extract_remote_image(data: Mapping[str, Any], env: Mapping[str, str]) -> dict[str, str] | None:
    direct = _extract_direct_image(data)
    if direct is not None:
        return direct
    candidates: list[Any] = []
    for key in ("image", "url", "output"):
        value = data.get(key)
        if isinstance(value, list):
            candidates.extend(value)
        elif value:
            candidates.append(value)
    images = data.get("images")
    if isinstance(images, list):
        candidates.extend(images)
    for candidate in candidates:
        url = ""
        if isinstance(candidate, str):
            url = candidate
        elif isinstance(candidate, Mapping):
            url = display_text(candidate.get("url") or candidate.get("src"))
        if not url.startswith(("http://", "https://")):
            continue
        payload, mime_type = _get_bytes(url, timeout=90, env=env)
        return {"mime_type": mime_type, "data": base64.b64encode(payload).decode("ascii")}
    return None


def _response_mime_type(response: Any) -> str:
    headers = getattr(response, "headers", None)
    if hasattr(headers, "get_content_type"):
        return headers.get_content_type() or "image/png"
    if isinstance(headers, Mapping):
        content_type = display_text(headers.get("content-type") or headers.get("Content-Type"), fallback="image/png")
        return content_type.split(";", 1)[0] or "image/png"
    return "image/png"


def _brain_prompt_lines(pack: Mapping[str, Any]) -> str:
    return "; ".join(
        f"{display_text(finding.get('title'))}: {display_text(finding.get('body'))}"
        for finding in _as_mappings(pack.get("brain_findings"))[:4]
    ) or "Use London's generalized taste principles from the seven-gate session."


def _source_prompt_lines(pack: Mapping[str, Any]) -> str:
    source_plan = pack.get("source_plan") if isinstance(pack.get("source_plan"), Mapping) else {}
    return "; ".join(
        f"{display_text(source.get('name') or source.get('title'))}: use for {display_text(source.get('use_for'))}; avoid {display_text(source.get('avoid'))}"
        for source in _as_mappings(source_plan.get("sources") if isinstance(source_plan, Mapping) else [])[:4]
    ) or "No live source artifacts; treat source targets as planned inspiration only."


def _section_visual_cues(route: Mapping[str, Any]) -> str:
    count = len(_as_mappings(route.get("sections"))[:4])
    if not count:
        return "Use route-specific product/interface moments as non-readable visual composition cues only."
    return (
        f"Use {count} route interaction moment(s) as non-readable visual states only: "
        "blank modules, abstract controls, object detail, material contrast, and gesture."
    )


def _brief_image_context(pack: Mapping[str, Any]) -> str:
    raw = clean_brief_text(pack, fallback=display_text(pack.get("title"), fallback="London Pack"))
    lines: list[str] = []
    for line in raw.splitlines():
        cleaned = line.strip().lstrip("#").strip()
        if not cleaned:
            continue
        if cleaned.lower().startswith("brief:"):
            continue
        lines.append(cleaned)
    text = " ".join(lines) or display_text(pack.get("title"), fallback="London Pack")
    sentence = text
    for sep in (".", "?", "!"):
        before, found, _after = sentence.partition(sep)
        if found and before.strip():
            sentence = before.strip() + found
            break
    return _compact_words(sentence, limit=28)


def _compact_words(text: str, *, limit: int) -> str:
    words = text.replace("\n", " ").split()
    if len(words) <= limit:
        return " ".join(words)
    return " ".join(words[:limit]) + "..."


def _brain_evidence(pack: Mapping[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "id": display_text(finding.get("id")),
            "title": display_text(finding.get("title")),
            "evidence_class": "London Brain Finding",
        }
        for finding in _as_mappings(pack.get("brain_findings"))[:4]
    ]


def _source_evidence(pack: Mapping[str, Any]) -> list[dict[str, str]]:
    source_plan = pack.get("source_plan") if isinstance(pack.get("source_plan"), Mapping) else {}
    return [
        {
            "id": display_text(source.get("slug") or source.get("source_id")),
            "title": display_text(source.get("name") or source.get("title")),
            "evidence_class": "Source Target",
        }
        for source in _as_mappings(source_plan.get("sources") if isinstance(source_plan, Mapping) else [])[:4]
    ]


def _route_id(route: Mapping[str, Any], route_index: int) -> str:
    return display_text(route.get("id"), fallback=slugify(display_text(route.get("title"), fallback=f"route-{route_index}")))


def _as_mappings(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _as_strings(value: Any, *, fallback: Sequence[str] = ()) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        values = [str(item) for item in value if str(item).strip()]
    else:
        values = []
    return [item.strip() for item in values if item.strip()] or list(fallback)


def _nested(mapping: Mapping[str, Any], *keys: str) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _scrub_error(exc: Exception, env: Mapping[str, str]) -> str:
    message = str(exc)
    cap = SCRUB_ERROR_MESSAGE_CAP
    if isinstance(exc, urllib.error.HTTPError):
        try:
            try:
                raw_body = exc.read(SCRUB_ERROR_HTTP_CAP + 1)
            except TypeError:
                raw_body = exc.read()
            body = raw_body[:SCRUB_ERROR_HTTP_CAP].decode("utf-8", errors="replace")
        except Exception:
            body = ""
        if body:
            message = f"HTTP Error {exc.code}: {exc.reason}; body={body}"
            cap = SCRUB_ERROR_HTTP_CAP
    for value in _secret_env_values(env):
        message = message.replace(value, "[redacted]")
    return message[:cap]


def _secret_env_values(env: Mapping[str, str]) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for key, value in env.items():
        if not _SECRET_ENV_NAME_RE.search(str(key)):
            continue
        if not value or len(value) < 8:
            continue
        if value not in seen:
            seen.add(value)
            values.append(value)
    values.sort(key=len, reverse=True)
    return values
