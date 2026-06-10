"""Unit tests for london.tui.steps — pure functions, no textual required."""
from __future__ import annotations

import builtins
import importlib
import sys
from typing import Any

import pytest

from london.tui.steps import (
    PROFILE_ROWS,
    GuidedStep,
    ProfileSteps,
    capability_map_rows,
    collect_setup_status_summary,
    steps_for_profile,
    verdict_line,
)


# ---------------------------------------------------------------------------
# Fixtures — minimal status dicts that exercise the four profile paths
# ---------------------------------------------------------------------------


def _base_status(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Minimal collect_setup_status() skeleton."""
    status: dict[str, Any] = {
        "status": "ok",
        "verdict": "CORE READY",
        "direction_mode": {
            "mode": "none",
            "model_key_present": False,
            "in_session_available": False,
            "api_sdk_available": False,
            "ready": False,
            "hint": "No model reachable.",
        },
        "image_generation": {
            "selected_provider": "manual-prompt",
            "allow_paid": False,
            "price_ceilings_usd": {"gemini": 0.25, "openai": 0.35},
            "price_ceiling_last_verified": "2026-06-09",
            "config": {"spend_limit_usd": 0.0, "allow_paid": False},
        },
        "providers": [
            {"id": "gemini", "env": [{"name": "GEMINI_API_KEY", "present": False}], "ready_generate": False},
            {"id": "openai", "env": [{"name": "OPENAI_API_KEY", "present": False}], "ready_generate": False},
            {"id": "bfl_flux", "env": [{"name": "BFL_API_KEY", "present": False}], "ready_generate": False},
            {"id": "automatic1111", "env": [], "ready_generate": False},
            {"id": "comfyui", "env": [], "ready_generate": False},
            {"id": "draw_things", "env": [], "ready_generate": False},
            {"id": "external_cmd", "env": [], "ready_generate": False},
            {"id": "manual_prompt", "env": [], "ready": True, "ready_generate": False},
        ],
        "capabilities": [
            {"id": "deterministic_pack", "ready": True},
            {"id": "browser_capture", "ready": False},
            {"id": "multimodal_direction", "ready": False},
            {"id": "image_generation", "ready": False},
            {"id": "web_extraction", "ready": False},
            {"id": "design_bridges", "ready": False},
        ],
    }
    if overrides:
        _deep_update(status, overrides)
    return status


def _deep_update(base: dict, updates: dict) -> None:
    for k, v in updates.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_update(base[k], v)
        else:
            base[k] = v


def _keyless_status() -> dict[str, Any]:
    """No model, no keys — runs demos only."""
    return _base_status()


def _in_session_status() -> dict[str, Any]:
    """Claude Code in-session model detected."""
    return _base_status({
        "direction_mode": {
            "mode": "in_session",
            "model_key_present": False,
            "in_session_available": True,
            "ready": True,
            "hint": "London will direct via the in-session model; no API key required.",
        },
    })


def _keyed_status() -> dict[str, Any]:
    """ANTHROPIC_API_KEY present, Gemini image key present."""
    return _base_status({
        "direction_mode": {
            "mode": "api",
            "model_key_present": True,
            "api_sdk_available": True,
            "ready": True,
            "hint": "London will direct via the keyed Anthropic model.",
        },
        "image_generation": {
            "selected_provider": "gemini",
            "allow_paid": False,
        },
        "providers": [
            {"id": "gemini", "env": [{"name": "GEMINI_API_KEY", "present": True}], "ready_generate": True},
        ],
    })


def _paid_ready_status() -> dict[str, Any]:
    """All keys present, paid policy configured."""
    return _base_status({
        "direction_mode": {
            "mode": "in_session",
            "model_key_present": False,
            "in_session_available": True,
            "ready": True,
        },
        "image_generation": {
            "selected_provider": "bfl",
            "allow_paid": True,
            "config": {"spend_limit_usd": 5.0, "allow_paid": True},
        },
        "providers": [
            {"id": "bfl_flux", "env": [{"name": "BFL_API_KEY", "present": True}], "ready_generate": True},
        ],
    })


def _blocked_status() -> dict[str, Any]:
    """Blocked — local deterministic missing."""
    status = _base_status()
    status["status"] = "blocked"
    status["verdict"] = "BLOCKED"
    return status


# ---------------------------------------------------------------------------
# Tests: collect_setup_status_summary
# ---------------------------------------------------------------------------


def test_summary_keyless():
    s = collect_setup_status_summary(_keyless_status())
    assert s["direction_mode"] == "none"
    assert s["in_session"] is False
    assert s["api_ready"] is False
    assert s["gemini_key"] is False
    assert s["openai_key"] is False
    assert s["bfl_key"] is False
    assert s["blocked"] is False
    assert s["has_live_image"] is False


def test_summary_in_session():
    s = collect_setup_status_summary(_in_session_status())
    assert s["direction_mode"] == "in_session"
    assert s["in_session"] is True
    assert s["api_ready"] is False


def test_summary_keyed():
    s = collect_setup_status_summary(_keyed_status())
    assert s["direction_mode"] == "api"
    assert s["api_ready"] is True
    assert s["gemini_key"] is True


def test_summary_paid_ready():
    s = collect_setup_status_summary(_paid_ready_status())
    assert s["in_session"] is True
    assert s["allow_paid"] is True
    assert s["paid_policy_ready"] is True
    assert s["bfl_key"] is True


def test_summary_blocked():
    s = collect_setup_status_summary(_blocked_status())
    assert s["blocked"] is True


# ---------------------------------------------------------------------------
# Tests: verdict_line
# ---------------------------------------------------------------------------


def test_verdict_keyless():
    line = verdict_line(_keyless_status())
    assert "CORE READY" in line


def test_verdict_in_session():
    line = verdict_line(_in_session_status())
    assert "CORE READY" in line


def test_verdict_blocked():
    line = verdict_line(_blocked_status())
    assert "BLOCKED" in line


# ---------------------------------------------------------------------------
# Tests: steps_for_profile — core (keyless)
# ---------------------------------------------------------------------------


def test_core_keyless_has_model_path_step():
    result = steps_for_profile("core", _keyless_status())
    assert isinstance(result, ProfileSteps)
    assert result.profile_id == "core"
    step_ids = [s.id for s in result.steps]
    assert "model_path" in step_ids


def test_core_keyless_model_path_allows_paste():
    result = steps_for_profile("core", _keyless_status())
    model_step = next(s for s in result.steps if s.id == "model_path")
    assert model_step.allows_paste is True
    assert model_step.paste_env_var == "ANTHROPIC_API_KEY"


def test_core_in_session_no_model_step():
    result = steps_for_profile("core", _in_session_status())
    step_ids = [s.id for s in result.steps]
    assert "model_path" not in step_ids


def test_core_keyless_first_command_offline():
    result = steps_for_profile("core", _keyless_status())
    assert "--offline" in result.first_command


def test_core_in_session_first_command():
    result = steps_for_profile("core", _in_session_status())
    # in-session: examples command, no --offline required (may still use it, but any
    # brief.md command is acceptable)
    assert "london" in result.first_command


# ---------------------------------------------------------------------------
# Tests: steps_for_profile — recommended
# ---------------------------------------------------------------------------


def test_recommended_keyless_includes_image_lane():
    result = steps_for_profile("recommended", _keyless_status())
    step_ids = [s.id for s in result.steps]
    assert "image_lane" in step_ids


def test_recommended_keyed_no_image_lane():
    """When gemini key is present, no image_lane step needed."""
    result = steps_for_profile("recommended", _keyed_status())
    step_ids = [s.id for s in result.steps]
    assert "image_lane" not in step_ids


def test_recommended_image_lane_has_cost_disclosure():
    result = steps_for_profile("recommended", _keyless_status())
    image_step = next(s for s in result.steps if s.id == "image_lane")
    assert image_step.cost_disclosure != ""
    assert "W0-09" in image_step.cost_disclosure
    assert "$" in image_step.cost_disclosure


def test_recommended_image_lane_skip_label_present():
    result = steps_for_profile("recommended", _keyless_status())
    image_step = next(s for s in result.steps if s.id == "image_lane")
    assert image_step.skip_label != ""
    assert "visual boards" in image_step.skip_label.lower() or "skip" in image_step.skip_label.lower()


def test_recommended_step_subtitles_numbered():
    result = steps_for_profile("recommended", _keyless_status())
    for i, step in enumerate(result.steps):
        assert f"step {i + 1} of" in step.subtitle


# ---------------------------------------------------------------------------
# Tests: steps_for_profile — pro-image
# ---------------------------------------------------------------------------


def test_pro_image_includes_paid_gate_step():
    result = steps_for_profile("pro-image", _keyless_status())
    step_ids = [s.id for s in result.steps]
    assert "paid_gate" in step_ids


def test_pro_image_paid_gate_cost_disclosure():
    result = steps_for_profile("pro-image", _keyless_status())
    paid_step = next(s for s in result.steps if s.id == "paid_gate")
    assert paid_step.cost_disclosure != ""
    assert "W0-09" in paid_step.cost_disclosure
    assert "allow_paid" in paid_step.cost_disclosure


def test_pro_image_paid_gate_shows_config_commands():
    result = steps_for_profile("pro-image", _keyless_status())
    paid_step = next(s for s in result.steps if s.id == "paid_gate")
    assert "allow_paid" in paid_step.terminal_cmd


def test_pro_image_already_paid_no_paid_gate():
    """If paid policy is already ready, no paid gate step."""
    result = steps_for_profile("pro-image", _paid_ready_status())
    step_ids = [s.id for s in result.steps]
    assert "paid_gate" not in step_ids


# ---------------------------------------------------------------------------
# Tests: steps_for_profile — details
# ---------------------------------------------------------------------------


def test_details_has_no_guided_steps():
    result = steps_for_profile("details", _keyless_status())
    assert result.steps == []


def test_details_first_command():
    result = steps_for_profile("details", _keyless_status())
    assert "london" in result.first_command


# ---------------------------------------------------------------------------
# Tests: capability_map_rows
# ---------------------------------------------------------------------------


def test_capability_map_rows_count():
    rows = capability_map_rows(_keyless_status())
    assert len(rows) == 7  # core_engine + 6 capability rows


def test_capability_map_rows_core_engine_keyless():
    rows = capability_map_rows(_keyless_status())
    core = next(r for r in rows if r["id"] == "core_engine")
    assert "NO MODEL" in core["chip"] or core["chip"] in {"IN-SESSION MODEL", "API MODEL", "NO MODEL"}
    assert core["ready"] is False


def test_capability_map_rows_core_engine_in_session():
    rows = capability_map_rows(_in_session_status())
    core = next(r for r in rows if r["id"] == "core_engine")
    assert core["chip"] == "IN-SESSION MODEL"
    assert core["ready"] is True


def test_capability_map_rows_image_generation_keyless():
    rows = capability_map_rows(_keyless_status())
    img = next(r for r in rows if r["id"] == "image_generation")
    assert "VISUAL BOARDS" in img["chip"]


def test_capability_map_rows_all_have_detail():
    rows = capability_map_rows(_keyless_status())
    for row in rows:
        assert "detail" in row
        assert isinstance(row["detail"], str)


# ---------------------------------------------------------------------------
# Tests: profile picker rows
# ---------------------------------------------------------------------------


def test_profile_rows_count():
    assert len(PROFILE_ROWS) == 4


def test_profile_rows_ids():
    ids = [r["id"] for r in PROFILE_ROWS]
    assert ids == ["core", "recommended", "pro-image", "details"]


def test_profile_rows_pro_is_paid():
    pro = next(r for r in PROFILE_ROWS if r["id"] == "pro-image")
    assert pro["paid"] is True


# ---------------------------------------------------------------------------
# Tests: GuidedStep never contains actual secret text
# ---------------------------------------------------------------------------


def test_model_path_step_body_has_no_key_value():
    """step body must not reveal any actual key text."""
    result = steps_for_profile("core", _keyless_status())
    for step in result.steps:
        # Placeholder text only; no real key characters
        assert "sk-" not in step.body
        assert "AIza" not in step.body


def test_image_lane_body_has_no_key_value():
    result = steps_for_profile("recommended", _keyless_status())
    for step in result.steps:
        assert "sk-" not in step.body
        assert "AIza" not in step.body


# ---------------------------------------------------------------------------
# Tests: steps.py has NO textual import at the module level
# ---------------------------------------------------------------------------


def test_steps_module_does_not_import_textual():
    """steps.py must be importable with textual blocked."""
    sys.modules.pop("london.tui.steps", None)
    real_import = builtins.__import__

    def reject_textual(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "textual" or name.startswith("textual."):
            raise AssertionError("london.tui.steps must not import textual")
        return real_import(name, globals, locals, fromlist, level)

    import builtins as _builtins
    old = _builtins.__import__
    _builtins.__import__ = reject_textual
    try:
        module = importlib.import_module("london.tui.steps")
        assert module.steps_for_profile
    finally:
        _builtins.__import__ = old
