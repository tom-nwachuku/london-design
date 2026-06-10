from __future__ import annotations

import importlib.util
import json
import os
import platform
import re
import shutil
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from london import __version__
from london.config import DEFAULT_CONFIG, normalize_provider_choice
from london.director import _ANTHROPIC_SECRET_KEYS
from london.image_generation import (
    IMAGE_PROVIDER_PRICE_CEILINGS_USD,
    IMAGE_PROVIDER_PRICE_LAST_VERIFIED,
    METERED_IMAGE_PROVIDERS,
)
from london.providers import CAPABILITIES, PROVIDERS, ProviderSpec

ModuleFinder = Callable[[str], bool]

SECRET_FIELD_MARKERS = ("api_key", "apikey", "secret", "token", "password", "credential")
NON_SECRET_FIELDS = {"secrets_printed"}
SECRET_LOOKING_ENV_RE = re.compile(r"(_API_KEY|_KEY|_TOKEN|_SECRET)$")
ENV_EXAMPLE_KEYS = ("GEMINI_API_KEY", "BFL_API_KEY", "OPENAI_API_KEY", "FIRECRAWL_API_KEY")
LOCAL_IMAGE_ENV_KEYS = (
    "LONDON_AUTOMATIC1111_URL",
    "LONDON_AUTOMATIC1111_STEPS",
    "LONDON_AUTOMATIC1111_CFG_SCALE",
    "LONDON_COMFYUI_URL",
    "LONDON_COMFYUI_WORKFLOW",
    "LONDON_COMFYUI_MODEL_PROFILE",
    "LONDON_COMFYUI_PROFILE",
    "LONDON_COMFYUI_MODEL_FAMILY",
    "LONDON_COMFYUI_LICENSE_POSTURE",
    "LONDON_COMFYUI_COMMERCIAL_USE",
    "LONDON_COMFYUI_CHECKPOINTS",
    "LONDON_COMFYUI_MAX_POLLS",
    "LONDON_COMFYUI_POLL_SECONDS",
    "LONDON_EXTERNAL_IMAGE_COMMAND",
    "LONDON_LOCAL_IMAGE_COMMAND",
    "LONDON_EXTERNAL_IMAGE_OUTPUT_DIR",
    "LONDON_EXTERNAL_IMAGE_RESULT",
    "LONDON_EXTERNAL_IMAGE_TIMEOUT",
    "LONDON_EXTERNAL_IMAGE_EXTENSION",
    "LONDON_DRAW_THINGS_COMMAND",
    "LONDON_DRAW_THINGS_CLI",
    "LONDON_GEMINI_API_VERSION",
    "LONDON_GEMINI_IMAGE_MODEL",
    "LONDON_GEMINI_IMAGE_ASPECT_RATIO",
    "LONDON_GEMINI_IMAGE_SIZE",
    "LONDON_GEMINI_RESPONSE_MODALITIES",
    "LONDON_GEMINI_REQUEST_CONFIG_MODE",
    "LONDON_GEMINI_GENERATION_CONFIG_MODE",
    "LONDON_BFL_BASE_URL",
    "LONDON_BFL_MODEL_PATH",
    "LONDON_BFL_IMAGE_WIDTH",
    "LONDON_BFL_IMAGE_HEIGHT",
    "LONDON_BFL_MAX_POLLS",
    "LONDON_BFL_POLL_SECONDS",
    "LONDON_OPENAI_IMAGE_MODEL",
    "LONDON_OPENAI_IMAGE_SIZE",
    "LONDON_OPENAI_IMAGE_QUALITY",
    "LONDON_OPENAI_IMAGE_OUTPUT_FORMAT",
    "LONDON_OPENAI_IMAGE_OUTPUT_COMPRESSION",
    "LONDON_OPENAI_IMAGE_BACKGROUND",
    "LONDON_OPENAI_IMAGE_MODERATION",
    "LONDON_FAL_IMAGE_URL",
    "LONDON_REPLICATE_MODEL_URL",
    "LONDON_REPLICATE_MAX_POLLS",
    "LONDON_REPLICATE_POLL_SECONDS",
    "LONDON_ALLOW_POLLINATIONS",
)
IMAGE_PROVIDER_TO_REGISTRY = {
    "automatic1111": "automatic1111",
    "comfyui": "comfyui",
    "external-cmd": "external_cmd",
    "draw-things": "draw_things",
    "gemini": "gemini",
    "bfl": "bfl_flux",
    "openai": "openai",
    "fal": "fal",
    "replicate": "replicate",
    "pollinations": "pollinations",
    "manual-prompt": "manual_prompt",
    "fixture": "local_deterministic",
}
REGISTRY_TO_IMAGE_PROVIDER = {value: key for key, value in IMAGE_PROVIDER_TO_REGISTRY.items()}
PREMIUM_IMAGE_PROVIDERS = set(METERED_IMAGE_PROVIDERS)
PROVIDER_STATES = (
    "ready_generate",
    "detected_needs_setup",
    "missing",
    "failed",
    "manual_only",
    "MISSING",
    "INSTALLED",
    "KEY PRESENT",
    "READY",
    "UNVERIFIED",
    "FAILED",
    "PAID",
    "PAID_BLOCKED",
    "LOCAL",
)
ENV_EXAMPLE_TEXT = "\n".join(f"{key}=" for key in ENV_EXAMPLE_KEYS) + "\n"
COMFYUI_MODEL_PROFILES: tuple[dict[str, object], ...] = (
    {
        "id": "flux-schnell",
        "label": "FLUX.1 schnell",
        "best_for": "fast permissive local fallback",
        "license_posture": "apache-2.0",
        "commercial_use": "permitted",
    },
    {
        "id": "ideogram-4",
        "label": "Ideogram 4",
        "best_for": "design layouts, posters, typography, literal text",
        "license_posture": "non-commercial public weights unless licensed",
        "commercial_use": "label required unless commercial license configured",
    },
    {
        "id": "hidream-i1",
        "label": "HiDream-I1",
        "best_for": "commercial-friendly local quality lane",
        "license_posture": "MIT per ComfyUI docs",
        "commercial_use": "permitted",
        "hardware_note": "FP8 versions need more than 16GB VRAM per ComfyUI docs",
    },
)


def module_is_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def redact_secret(value: str | None) -> str:
    if not value:
        return ""
    return "[redacted]"


def _secret_values(env: Mapping[str, str], providers: tuple[ProviderSpec, ...]) -> tuple[str, ...]:
    values: list[str] = []
    for provider in providers:
        for env_var in provider.env_vars:
            value = env.get(env_var)
            if value:
                values.append(value)
    return tuple(values)


def known_secret_env_vars() -> tuple[str, ...]:
    keys = {env_var for provider in PROVIDERS for env_var in provider.env_vars}
    return tuple(sorted(keys))


def sanitize_for_output(value: Any, secret_values: tuple[str, ...] = ()) -> Any:
    """Return a JSON-friendly value with secret-looking fields redacted."""

    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            key_lower = key.lower()
            if key_lower not in NON_SECRET_FIELDS and any(
                marker in key_lower for marker in SECRET_FIELD_MARKERS
            ):
                sanitized[key] = redact_secret(str(raw_value)) if raw_value else raw_value
            else:
                sanitized[key] = sanitize_for_output(raw_value, secret_values)
        return sanitized
    if isinstance(value, list):
        return [sanitize_for_output(item, secret_values) for item in value]
    if isinstance(value, tuple):
        return [sanitize_for_output(item, secret_values) for item in value]
    if isinstance(value, str):
        scrubbed = value
        for secret in secret_values:
            if secret:
                scrubbed = scrubbed.replace(secret, redact_secret(secret))
        return scrubbed
    return value


def _env_presence(env: Mapping[str, str], env_vars: tuple[str, ...]) -> list[dict[str, object]]:
    return [{"name": env_var, "present": bool(env.get(env_var))} for env_var in env_vars]


def _dependency_presence(
    provider: ProviderSpec,
    module_finder: ModuleFinder,
) -> list[dict[str, object]]:
    return [
        {"type": "python_module", "name": module_name, "present": module_finder(module_name)}
        for module_name in provider.python_modules
    ]


def _provider_status(
    provider: ProviderSpec,
    env: Mapping[str, str],
    module_finder: ModuleFinder,
    image_config: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    image_config = image_config or DEFAULT_CONFIG["image"]
    paid_policy_ready = _paid_image_policy_ready(image_config)
    env_checks = _env_presence(env, provider.env_vars)
    dependency_checks = _dependency_presence(provider, module_finder)
    has_key = any(check["present"] for check in env_checks) if env_checks else True
    dependencies_ready = all(check["present"] for check in dependency_checks)

    dependency_installed = bool(dependency_checks) and dependencies_ready
    ready_generate = False

    if provider.id == "local_deterministic":
        status = "ready"
        ready = True
        state_labels = ["LOCAL", "READY"]
    elif provider.id == "automatic1111":
        status, ready, state_labels, ready_generate = _automatic1111_status(env)
    elif provider.id == "comfyui":
        status, ready, state_labels, ready_generate = _comfyui_status(env)
    elif provider.id == "external_cmd":
        status, ready, state_labels, ready_generate = _external_cmd_status(env)
    elif provider.id == "draw_things":
        status, ready, state_labels, ready_generate = _draw_things_status(env)
    elif provider.id == "pollinations":
        allowed = bool(image_config.get("allow_experimental_free_network", False))
        status = "ready_generate" if allowed else "detected_needs_setup"
        ready = allowed
        ready_generate = allowed
        state_labels = ["READY_GENERATE"] if allowed else ["detected_needs_setup"]
    elif provider.id == "perchance":
        status = "manual_only"
        ready = False
        state_labels = ["manual_only"]
    elif provider.id == "manual_prompt":
        status = "manual_only"
        ready = True
        state_labels = ["manual_only", "READY"]
    elif provider.env_vars and not has_key:
        status = "missing_key"
        ready = False
        state_labels = ["MISSING"]
        if dependency_installed:
            state_labels.append("INSTALLED")
    elif not dependencies_ready:
        status = "missing_dependency"
        ready = False
        state_labels = ["KEY PRESENT"]
    else:
        status = "ready_generate" if "image_generation" in provider.capabilities else "ready"
        ready = True
        ready_generate = "image_generation" in provider.capabilities
        state_labels = ["KEY PRESENT", "READY_GENERATE" if ready_generate else "READY"]
        if dependency_checks:
            state_labels.insert(1, "INSTALLED")

    provider_image_id = REGISTRY_TO_IMAGE_PROVIDER.get(provider.id)
    if provider_image_id in METERED_IMAGE_PROVIDERS:
        if has_key and not paid_policy_ready:
            status = "paid_blocked"
            ready = False
            ready_generate = False
            state_labels = ["KEY PRESENT", "PAID_BLOCKED"]
            if dependency_checks and dependencies_ready:
                state_labels.insert(1, "INSTALLED")
        state_labels.append("PAID")

    return {
        "id": provider.id,
        "image_provider": REGISTRY_TO_IMAGE_PROVIDER.get(provider.id),
        "label": provider.label,
        "kind": provider.kind,
        "priority": provider.priority,
        "status": status,
        "state_labels": state_labels,
        "ready": ready,
        "ready_generate": ready_generate,
        "optional": provider.id != "local_deterministic",
        "capabilities": list(provider.capabilities),
        "env": env_checks,
        "dependencies": dependency_checks,
        "notes": provider.notes,
        "secret_values_printed": False,
    }


def _paid_image_policy_ready(image_config: Mapping[str, Any]) -> bool:
    try:
        spend_limit = float(image_config.get("spend_limit_usd", 0.0) or 0.0)
    except (TypeError, ValueError):
        spend_limit = 0.0
    return bool(image_config.get("allow_paid", False)) and spend_limit > 0.0


def _automatic1111_status(env: Mapping[str, str]) -> tuple[str, bool, list[str], bool]:
    base_url = (env.get("LONDON_AUTOMATIC1111_URL") or "http://127.0.0.1:7860").rstrip("/")
    if _http_available(f"{base_url}/sdapi/v1/sd-models"):
        return "ready_generate", True, ["ready_generate", "READY"], True
    if env.get("LONDON_AUTOMATIC1111_URL"):
        return "detected_needs_setup", False, ["detected_needs_setup"], False
    return "missing", False, ["missing"], False


def _comfyui_status(env: Mapping[str, str]) -> tuple[str, bool, list[str], bool]:
    base_url = (env.get("LONDON_COMFYUI_URL") or "http://127.0.0.1:8188").rstrip("/")
    workflow = env.get("LONDON_COMFYUI_WORKFLOW")
    server_ready = _http_available(f"{base_url}/system_stats") or _http_available(f"{base_url}/object_info")
    workflow_ready = bool(workflow and Path(workflow).exists())
    if server_ready and workflow_ready:
        return "ready_generate", True, ["ready_generate", "READY"], True
    if server_ready or workflow:
        return "detected_needs_setup", False, ["detected_needs_setup"], False
    return "missing", False, ["missing"], False


def _comfyui_profile(env: Mapping[str, str]) -> dict[str, object]:
    profile = (
        env.get("LONDON_COMFYUI_MODEL_PROFILE")
        or env.get("LONDON_COMFYUI_PROFILE")
        or "custom-workflow"
    )
    family = env.get("LONDON_COMFYUI_MODEL_FAMILY") or profile
    license_posture = env.get("LONDON_COMFYUI_LICENSE_POSTURE") or "user-supplied-workflow"
    commercial_use = env.get("LONDON_COMFYUI_COMMERCIAL_USE") or "unknown"
    checkpoints = env.get("LONDON_COMFYUI_CHECKPOINTS") or ""
    checkpoint_count = len([item for item in checkpoints.split(",") if item.strip()])
    return {
        "profile": profile,
        "model_family": family,
        "license_posture": license_posture,
        "commercial_use": commercial_use,
        "checkpoint_count": checkpoint_count,
    }


def _external_cmd_status(env: Mapping[str, str]) -> tuple[str, bool, list[str], bool]:
    if env.get("LONDON_EXTERNAL_IMAGE_COMMAND") or env.get("LONDON_LOCAL_IMAGE_COMMAND"):
        return "ready_generate", True, ["ready_generate", "READY"], True
    if env.get("LONDON_EXTERNAL_IMAGE_OUTPUT_DIR") or env.get("LONDON_EXTERNAL_IMAGE_RESULT"):
        return "detected_needs_setup", False, ["detected_needs_setup"], False
    return "missing", False, ["missing"], False


def _draw_things_status(env: Mapping[str, str]) -> tuple[str, bool, list[str], bool]:
    command = env.get("LONDON_DRAW_THINGS_COMMAND")
    candidate = _draw_things_cli(env)
    if command and _draw_things_command_template_ready(command, candidate):
        return "ready_generate", True, ["ready_generate", "READY"], True
    if command or candidate:
        return "detected_needs_setup", False, ["detected_needs_setup"], False
    return "missing", False, ["missing"], False


def _draw_things_cli(env: Mapping[str, str]) -> str | None:
    return env.get("LONDON_DRAW_THINGS_CLI") or shutil.which("draw-things-cli") or shutil.which("draw-things")


def _draw_things_command_template_ready(command: str, cli: str | None) -> bool:
    if "{prompt_file}" not in command or "{output}" not in command:
        return False
    if "{cli}" in command and not cli:
        return False
    return True


def _http_available(url: str) -> bool:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=0.35) as response:  # noqa: S310 - localhost/user-configured readiness check
            return 200 <= getattr(response, "status", 200) < 500
    except (OSError, urllib.error.URLError, TimeoutError):
        return False


def _local_fallback_check(provider_rows: list[dict[str, object]]) -> dict[str, object]:
    local_provider = next(row for row in provider_rows if row["id"] == "local_deterministic")
    passed = bool(local_provider["ready"])
    return {
        "id": "local_deterministic_fallback",
        "label": "Deterministic local pack renderer",
        "status": "pass" if passed else "fail",
        "blocking": not passed,
        "message": "Local deterministic pack rendering is available without provider keys."
        if passed
        else "Local deterministic pack rendering is unavailable.",
    }


def direction_mode_status(
    env: Mapping[str, str] | None = None,
    module_finder: ModuleFinder = module_is_available,
) -> dict[str, object]:
    """Report which creative-direction model would run on the DEFAULT path (Pitfall 6).

    London is model-driven by default: ``setup``/``doctor`` must say which director the
    engine would select WITHOUT triggering a full run. Detection mirrors
    ``ClaudeCodeDirector.detect_mode`` (D-01) but is PRESENCE-ONLY — it never imports a
    model SDK to make a live call, never prints a key value/prefix/length, and only
    reports a boolean presence for ``ANTHROPIC_API_KEY`` (threat T-06-05).

    Modes:
      * ``in_session`` — the in-session ``claude_agent_sdk`` is importable and a Claude
        Code runtime marker is present (no key needed).
      * ``claude_cli_print`` — explicitly requested local Claude CLI print transport
        (``LONDON_CLAUDE_CLI_PRINT=1``) with ``claude_agent_sdk`` importable.
      * ``api``        — ``ANTHROPIC_API_KEY`` is present AND ``anthropic`` is importable.
      * ``none``       — neither; the default path hard-errors. The fix-it hint teaches
                         both fixes (run in Claude Code / set the key, or ``--offline``).
    """

    resolved_env = os.environ if env is None else env
    runtime_marker_present = bool(resolved_env.get("CLAUDECODE") or resolved_env.get("CLAUDE_CODE_ENTRYPOINT"))
    cli_print_requested = str(resolved_env.get("LONDON_CLAUDE_CLI_PRINT") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    in_session = module_finder("claude_agent_sdk") and runtime_marker_present and not resolved_env.get("PYTEST_CURRENT_TEST")
    cli_print = module_finder("claude_agent_sdk") and cli_print_requested and not resolved_env.get("PYTEST_CURRENT_TEST")
    api_key_present = bool(resolved_env.get("ANTHROPIC_API_KEY"))
    anthropic_available = module_finder("anthropic")
    api_ready = api_key_present and anthropic_available

    if in_session:
        mode = "in_session"
        label = "In-session model (claude-agent-sdk)"
        hint = "London will direct via the in-session model; no API key required."
    elif cli_print:
        mode = "claude_cli_print"
        label = "Local Claude CLI print transport"
        hint = "London will attempt the authenticated local Claude CLI print transport."
    elif api_ready:
        mode = "api"
        label = "API model (ANTHROPIC_API_KEY)"
        hint = "London will direct via the keyed Anthropic model."
    else:
        mode = "none"
        label = "No model reachable"
        hint = (
            "London is model-driven by default. Run inside Claude Code, set "
            "ANTHROPIC_API_KEY, or use --offline for the labeled deterministic template demo."
        )

    return {
        "id": "direction_mode",
        "mode": mode,
        "label": label,
        "ready": mode != "none",
        "in_session_available": bool(in_session),
        "claude_cli_print_available": bool(cli_print),
        "claude_cli_print_requested": cli_print_requested,
        "runtime_marker_present": runtime_marker_present,
        # PRESENCE boolean only (named to avoid the api_key secret-field redaction marker).
        "model_key_present": api_key_present,
        "api_sdk_available": bool(anthropic_available),
        "offline_available": True,
        "hint": hint,
        # Presence-only: this report never carries a key value, prefix, or length.
        "secret_values_printed": False,
    }


def _semantic_brain_check(module_finder: ModuleFinder) -> dict[str, object]:
    has_chroma = module_finder("chromadb")
    return {
        "id": "semantic_london_brain",
        "label": "Semantic London Brain index",
        "status": "pass" if has_chroma else "warn",
        "blocking": False,
        "message": "Chroma is included as the core derived retrieval path for London's taste brain."
        if has_chroma
        else "Chroma was not importable; reinstall base dependencies before release packaging.",
    }


def parse_env_file(path: str | Path) -> dict[str, Any]:
    env_path = Path(path)
    known_keys = (
        set(known_secret_env_vars())
        | set(LOCAL_IMAGE_ENV_KEYS)
        | set(_ANTHROPIC_SECRET_KEYS)
    )
    loaded: dict[str, str] = {}
    warnings: list[str] = []
    if not env_path.exists():
        raise FileNotFoundError(f"Env file not found: {env_path}")
    try:
        mode = env_path.stat().st_mode & 0o777
        if mode & 0o077:
            warnings.append("Env file permissions are broader than recommended; use chmod 600 .env.")
    except OSError:
        warnings.append("Could not inspect env file permissions.")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key.removeprefix("export ").strip()
        if key not in known_keys:
            if SECRET_LOOKING_ENV_RE.search(key):
                warnings.append(
                    f"Env file key {key} looks secret-like but is not a recognized London "
                    "setting; it was ignored."
                )
            continue
        loaded[key] = _strip_env_value(value.strip())
    return {
        "loaded": True,
        "path_label": env_path.name,
        "loaded_keys": sorted(loaded),
        "warnings": warnings,
        "env": loaded,
    }


def _strip_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return re.sub(r"\s+#.*$", "", value).strip()


def merge_env_file(
    base_env: Mapping[str, str] | None,
    env_file: str | Path | None,
) -> tuple[dict[str, str], dict[str, Any] | None]:
    merged = dict(os.environ if base_env is None else base_env)
    if env_file is None:
        return merged, None
    parsed = parse_env_file(env_file)
    merged.update(parsed["env"])
    return merged, {
        "loaded": parsed["loaded"],
        "path_label": parsed["path_label"],
        "loaded_keys": parsed["loaded_keys"],
        "warnings": parsed["warnings"],
    }


def runtime_context() -> dict[str, Any]:
    return {
        "package": "london-design",
        "version": __version__,
        "python": platform.python_version(),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "uv_project_env": bool(os.environ.get("UV_PROJECT_ENVIRONMENT") or os.environ.get("VIRTUAL_ENV")),
    }


def recommend_image_provider(
    provider_rows: list[dict[str, object]] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    module_finder: ModuleFinder = module_is_available,
    config: Mapping[str, Any] | None = None,
    profile: str = "recommended",
) -> dict[str, Any]:
    resolved_env = os.environ if env is None else env
    rows = provider_rows or [
        _provider_status(provider, resolved_env, module_finder, (config or DEFAULT_CONFIG).get("image", DEFAULT_CONFIG["image"]))
        for provider in sorted(PROVIDERS, key=lambda item: item.priority)
    ]
    image_config = dict((config or DEFAULT_CONFIG).get("image", DEFAULT_CONFIG["image"]))
    primary = normalize_provider_choice(str(image_config.get("primary", "auto")))
    backups = [
        normalize_provider_choice(str(item))
        for item in image_config.get("backups", ["gemini", "openai", "manual-prompt"])
    ]
    allow_paid = bool(image_config.get("allow_paid", False))
    spend_limit = float(image_config.get("spend_limit_usd", 0.0))
    paid_policy_ready = _paid_image_policy_ready(image_config)
    allow_experimental = bool(image_config.get("allow_experimental_free_network", False))
    ready_by_provider = {
        str(row.get("image_provider")): bool(row.get("ready_generate"))
        for row in rows
        if row.get("image_provider")
    }
    ready_by_provider["manual-prompt"] = True
    ready_by_provider["none"] = True
    ready_by_provider["fixture"] = True

    if primary == "auto":
        candidates = _profile_candidates(profile, paid_policy_ready, allow_experimental)
        selected_reason = f"{profile} profile selected the first ready provider within cost policy."
    else:
        candidates = [primary, *backups, "manual-prompt"]
        selected_reason = f"config image.primary={primary} with configured backups."

    fallback_chain: list[dict[str, Any]] = []
    selected = "manual-prompt"
    for candidate in _dedupe(candidates):
        ready = ready_by_provider.get(candidate, False)
        registry_id = IMAGE_PROVIDER_TO_REGISTRY.get(candidate)
        row = next((item for item in rows if item.get("id") == registry_id), None)
        paid_blocked = (
            candidate in PREMIUM_IMAGE_PROVIDERS
            and not paid_policy_ready
            and (ready or (row is not None and row.get("status") == "paid_blocked"))
        )
        experimental_blocked = candidate == "pollinations" and not allow_experimental
        if ready and not paid_blocked and not experimental_blocked and candidate not in {"manual-prompt", "none", "fixture"}:
            reason = "ready_generate"
        elif candidate == "none":
            reason = "images disabled"
        elif candidate == "fixture":
            reason = "fixture sketch mode"
        elif candidate == "manual-prompt":
            reason = "visual direction board"
        else:
            reason = _not_ready_reason(candidate, rows, paid_blocked or experimental_blocked)
        fallback_chain.append(
            {
                "provider": candidate,
                "ready": ready and not paid_blocked,
                "ready_generate": ready
                and not paid_blocked
                and candidate not in {"manual-prompt", "none", "fixture"},
                "paid": candidate in PREMIUM_IMAGE_PROVIDERS,
                "manual_only": candidate == "manual-prompt",
                "allowed": not paid_blocked and not experimental_blocked,
                "reason": reason,
            }
        )
        if ready and not paid_blocked and not experimental_blocked:
            selected = candidate
            break

    return {
        "primary": selected,
        "selected_provider": selected,
        "requested_provider": "auto",
        "backups": [item for item in _dedupe(candidates) if item != selected],
        "selected_reason": selected_reason,
        "fallback_chain": fallback_chain,
        "allow_paid": allow_paid,
        "spend_limit_usd": spend_limit,
        "price_ceiling_last_verified": IMAGE_PROVIDER_PRICE_LAST_VERIFIED,
        "price_ceilings_usd": dict(IMAGE_PROVIDER_PRICE_CEILINGS_USD),
        "profile": profile,
        "config": {
            "primary": primary,
            "backups": backups,
            "allow_paid": allow_paid,
            "spend_limit_usd": spend_limit,
            "allow_experimental_free_network": allow_experimental,
        },
    }


def _profile_candidates(profile: str, allow_paid: bool, allow_experimental: bool) -> list[str]:
    normalized = profile.strip().lower().replace("_", "-")
    if normalized in {"core", "core-demo", "keyless"}:
        return ["manual-prompt"]
    local_first = ["automatic1111", "comfyui", "draw-things", "external-cmd"]
    api = ["gemini", "openai"]
    premium = ["bfl"] if allow_paid else []
    external = ["fal", "replicate"]
    experimental = ["pollinations"] if allow_experimental else []
    manual = ["manual-prompt"]
    if normalized in {"pro", "pro-image", "premium"} and allow_paid:
        return [*local_first, "bfl", "gemini", "openai", *external, *experimental, *manual]
    if normalized in {"openai", "openai-native"}:
        return [*local_first, "openai", "gemini", *premium, *external, *experimental, *manual]
    return [*local_first, *api, *premium, *external, *experimental, *manual]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _not_ready_reason(candidate: str, rows: list[dict[str, object]], paid_blocked: bool) -> str:
    if paid_blocked:
        if candidate == "pollinations":
            return "requires image.allow_experimental_free_network=true"
        return "requires image.allow_paid=true and image.spend_limit_usd > 0"
    registry_id = IMAGE_PROVIDER_TO_REGISTRY.get(candidate)
    row = next((item for item in rows if item.get("id") == registry_id), None)
    if not row:
        return "not registered"
    return str(row.get("status") or "not_ready")


def setup_profiles() -> list[dict[str, Any]]:
    return [
        {
            "id": "core",
            "label": "Core demo",
            "description": "Run London keyless with the bundled brain, Chroma retrieval, and visual direction boards.",
            "paid": False,
        },
        {
            "id": "recommended",
            "label": "Recommended",
            "description": "Use ready local generators or Gemini/OpenAI when configured, with no silent paid BFL lane.",
            "paid": False,
        },
        {
            "id": "pro-image",
            "label": "Pro image lab",
            "description": "Allow premium BFL image generation after explicit paid-use configuration.",
            "paid": True,
        },
        {
            "id": "details",
            "label": "Details",
            "description": "Inspect provider modules, key presence, and exact capability readiness.",
            "paid": False,
        },
    ]


def _capability_ready(
    capability_id: str,
    provider_rows: list[dict[str, object]],
    checks_by_id: Mapping[str, dict[str, object]],
) -> bool:
    if capability_id == "semantic_london_brain":
        return checks_by_id["semantic_london_brain"]["status"] == "pass"
    return any(
        capability_id in row["capabilities"] and bool(row["ready"])
        for row in provider_rows
    )


def collect_setup_status(
    env: Mapping[str, str] | None = None,
    module_finder: ModuleFinder = module_is_available,
    env_file: str | Path | None = None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the JSON-ready setup payload used by the future CLI integration."""

    resolved_env, env_file_status = merge_env_file(env, env_file)
    image_config = dict((config or DEFAULT_CONFIG).get("image", DEFAULT_CONFIG["image"]))
    providers = sorted(PROVIDERS, key=lambda item: item.priority)
    provider_rows = [_provider_status(provider, resolved_env, module_finder, image_config) for provider in providers]
    local_check = _local_fallback_check(provider_rows)
    semantic_check = _semantic_brain_check(module_finder)
    checks_by_id = {str(check["id"]): check for check in (local_check, semantic_check)}
    blockers = [] if not local_check["blocking"] else [local_check["message"]]
    image_recommendation = recommend_image_provider(
        provider_rows,
        env=resolved_env,
        module_finder=module_finder,
        config=config,
    )
    recommended_provider = IMAGE_PROVIDER_TO_REGISTRY.get(str(image_recommendation["selected_provider"]), "manual_prompt")
    secret_values = _secret_values(resolved_env, tuple(providers))
    direction_mode = direction_mode_status(resolved_env, module_finder)

    payload: dict[str, Any] = {
        "status": "ok" if not blockers else "blocked",
        "verdict": "CORE READY" if not blockers else "BLOCKED",
        "generated_at": datetime.now(UTC).isoformat(),
        "secrets_printed": False,
        "recommended_provider": recommended_provider,
        # Which creative-direction model would run on the default path (Pitfall 6).
        # Presence-only — never carries key material.
        "direction_mode": direction_mode,
        "provider_preference": [provider.id for provider in providers],
        "runtime": runtime_context(),
        "env_policy": {
            "default": "environment variables",
            "env_file": "explicit --env-file only",
            "auto_read_dotenv": False,
            "secret_values_saved": False,
            "secret_values_hashed": False,
            "secret_values_uploaded": False,
        },
        "env_file": env_file_status or {"loaded": False, "loaded_keys": [], "warnings": []},
        "provider_states": list(PROVIDER_STATES),
        "setup_profiles": setup_profiles(),
        "comfyui_setup": _comfyui_setup_guidance(provider_rows, resolved_env),
        "draw_things_setup": _draw_things_setup_guidance(provider_rows),
        "image_generation": image_recommendation,
        "checks": [local_check, semantic_check],
        "blockers": blockers,
        "providers": provider_rows,
        "capabilities": [
            {
                "id": capability.id,
                "label": capability.label,
                "mode": capability.mode,
                "description": capability.description,
                "ready": _capability_ready(capability.id, provider_rows, checks_by_id),
                "providers": [
                    row["id"] for row in provider_rows if capability.id in row["capabilities"]
                ],
            }
            for capability in CAPABILITIES
        ],
    }
    return sanitize_for_output(payload, secret_values)


def _comfyui_setup_guidance(
    provider_rows: list[dict[str, object]],
    env: Mapping[str, str],
) -> dict[str, object]:
    local_ids = {"automatic1111", "comfyui", "external_cmd", "draw_things"}
    local_ready = any(
        row.get("id") in local_ids and bool(row.get("ready_generate"))
        for row in provider_rows
    )
    comfyui = next((row for row in provider_rows if row.get("id") == "comfyui"), {})
    status = str(comfyui.get("status") or "missing")
    partially_detected = status == "detected_needs_setup" or any(
        env.get(key)
        for key in (
            "LONDON_COMFYUI_URL",
            "LONDON_COMFYUI_WORKFLOW",
            "LONDON_COMFYUI_MODEL_PROFILE",
            "LONDON_COMFYUI_PROFILE",
            "LONDON_COMFYUI_MODEL_FAMILY",
        )
    )
    return {
        "id": "comfyui",
        "recommended": (not local_ready) or partially_detected,
        "status": status,
        "ready_generate": bool(comfyui.get("ready_generate")),
        "install_entrypoint": "london setup --install comfyui",
        "try_command": 'london image try "kids lunchbox ritual kit" --provider comfyui --out /tmp/london-comfyui-try',
        "active_profile": _comfyui_profile(env),
        "profiles": [dict(profile) for profile in COMFYUI_MODEL_PROFILES],
        "notes": "Cross-platform local workflow runner; ready only when a local server and workflow JSON are configured.",
        "secrets_printed": False,
    }


def _draw_things_setup_guidance(provider_rows: list[dict[str, object]]) -> dict[str, object]:
    local_ids = {"automatic1111", "comfyui", "external_cmd", "draw_things"}
    local_ready = any(
        row.get("id") in local_ids and bool(row.get("ready_generate"))
        for row in provider_rows
    )
    draw_things = next((row for row in provider_rows if row.get("id") == "draw_things"), {})
    recommended = platform.system() == "Darwin" and not local_ready
    return {
        "id": "draw-things",
        "recommended": recommended,
        "status": str(draw_things.get("status") or "missing"),
        "ready_generate": bool(draw_things.get("ready_generate")),
        "install_command": "brew install drawthingsai/draw-things/draw-things-cli",
        "install_entrypoint": "london setup --install draw-things",
        "try_command": 'london image try "kids lunchbox ritual kit" --provider draw-things --out /tmp/london-draw-things-try',
        "notes": "Recommended free/local Mac path, subject to local compute, model downloads, disk space, and explicit command-template setup.",
        "secrets_printed": False,
    }


def write_support_report(status: Mapping[str, Any], path: str | Path) -> Path:
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(status, indent=2, sort_keys=True), encoding="utf-8")
    return report_path
