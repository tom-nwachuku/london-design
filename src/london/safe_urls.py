from __future__ import annotations

from typing import Any

from .text import display_text

_BLOCKED_URL_CHARS = ('"', "'", "<", ">", "\n", "\r")
_BLOCKED_DATA_IMAGE_CHARS = ("\n", "\r")


def safe_href(value: Any, *, allow_parent_assets: bool = False) -> str:
    """Return a render-safe URL or ``""`` for model-authored unsafe values."""

    href = display_text(value).strip()
    if not href:
        return ""
    if href.startswith("data:image/"):
        return "" if any(token in href for token in _BLOCKED_DATA_IMAGE_CHARS) else href
    if any(token in href for token in _BLOCKED_URL_CHARS):
        return ""
    if href.startswith("https://"):
        return href
    if _safe_asset_path(href, prefix="assets/"):
        return href
    if allow_parent_assets and _safe_asset_path(href, prefix="../assets/"):
        return href
    return ""


def _safe_asset_path(value: str, *, prefix: str) -> bool:
    if not value.startswith(prefix) or "\\" in value:
        return False
    parts = value.split("/")
    return all(part not in {"", ".", ".."} for part in parts)
