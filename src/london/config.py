from __future__ import annotations

import os
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

IMAGE_PROVIDER_CHOICES = {
    "auto",
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
}

DEFAULT_CONFIG: dict[str, Any] = {
    "image": {
        "primary": "auto",
        "backups": ["gemini", "openai", "manual-prompt"],
        "allow_paid": False,
        "spend_limit_usd": 0.0,
        "allow_experimental_free_network": False,
    }
}


def default_config_path(env: Mapping[str, str] | None = None) -> Path:
    resolved_env = os.environ if env is None else env
    config_home = resolved_env.get("XDG_CONFIG_HOME")
    if config_home:
        return Path(config_home) / "london" / "config.toml"
    home = resolved_env.get("HOME")
    if home:
        return Path(home) / ".config" / "london" / "config.toml"
    return Path(".config") / "london" / "config.toml"


def load_config(path: str | Path | None = None, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    config = deepcopy(DEFAULT_CONFIG)
    config_path = Path(path) if path is not None else default_config_path(env)
    if not config_path.exists():
        return config
    with config_path.open("rb") as handle:
        loaded = tomllib.load(handle)
    image = loaded.get("image") if isinstance(loaded, Mapping) else None
    if isinstance(image, Mapping):
        if isinstance(image.get("primary"), str):
            config["image"]["primary"] = normalize_provider_choice(str(image["primary"]))
        if isinstance(image.get("backups"), list):
            config["image"]["backups"] = [
                normalize_provider_choice(str(item))
                for item in image["backups"]
                if str(item).strip()
            ]
        if isinstance(image.get("allow_paid"), bool):
            config["image"]["allow_paid"] = bool(image["allow_paid"])
        if isinstance(image.get("allow_experimental_free_network"), bool):
            config["image"]["allow_experimental_free_network"] = bool(image["allow_experimental_free_network"])
        if image.get("spend_limit_usd") is not None:
            try:
                config["image"]["spend_limit_usd"] = float(image["spend_limit_usd"])
            except (TypeError, ValueError):
                pass
    return config


def normalize_provider_choice(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    aliases = {
        "local": "manual-prompt",
        "local-deterministic": "fixture",
        "local-renderer": "fixture",
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
    if normalized not in IMAGE_PROVIDER_CHOICES:
        raise ValueError("Unknown image provider choice; expected auto, a ready generator, external-cmd, manual-prompt, none, or fixture")
    return normalized


def set_config_value(key: str, value: str, *, path: str | Path | None = None, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    if not key.startswith("image."):
        raise ValueError("Unsupported London config key; currently supports image.* keys only")
    config = load_config(path=path, env=env)
    field = key.split(".", 1)[1]
    if field == "primary":
        config["image"]["primary"] = normalize_provider_choice(value)
    elif field == "backups":
        config["image"]["backups"] = [
            normalize_provider_choice(item)
            for item in value.split(",")
            if item.strip()
        ]
    elif field == "allow_paid":
        normalized = value.strip().lower()
        if normalized not in {"true", "false", "1", "0", "yes", "no"}:
            raise ValueError("image.allow_paid requires true or false")
        config["image"]["allow_paid"] = normalized in {"true", "1", "yes"}
    elif field == "allow_experimental_free_network":
        normalized = value.strip().lower()
        if normalized not in {"true", "false", "1", "0", "yes", "no"}:
            raise ValueError("image.allow_experimental_free_network requires true or false")
        config["image"]["allow_experimental_free_network"] = normalized in {"true", "1", "yes"}
    elif field == "spend_limit_usd":
        try:
            amount = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("image.spend_limit_usd requires a non-negative number") from exc
        if amount < 0:
            raise ValueError("image.spend_limit_usd must be non-negative")
        config["image"]["spend_limit_usd"] = amount
    else:
        raise ValueError("Unsupported image config key; supported keys are primary, backups, allow_paid, spend_limit_usd, and allow_experimental_free_network")
    config_path = Path(path) if path is not None else default_config_path(env)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(render_config(config), encoding="utf-8")
    return config


def render_config(config: Mapping[str, Any]) -> str:
    image = config.get("image") if isinstance(config.get("image"), Mapping) else {}
    primary = normalize_provider_choice(str(image.get("primary", "auto")))
    backups = [
        normalize_provider_choice(str(item))
        for item in image.get("backups", ["gemini", "openai", "manual-prompt"])
    ]
    allow_paid = bool(image.get("allow_paid", False))
    spend_limit = float(image.get("spend_limit_usd", 0.0))
    allow_experimental = bool(image.get("allow_experimental_free_network", False))
    backup_rows = ", ".join(f'"{item}"' for item in backups)
    return "\n".join(
        [
            "[image]",
            f'primary = "{primary}"',
            f"backups = [{backup_rows}]",
            f"allow_paid = {str(allow_paid).lower()}",
            f"spend_limit_usd = {spend_limit:.2f}",
            f"allow_experimental_free_network = {str(allow_experimental).lower()}",
            "",
        ]
    )
