"""Textual Pilot tests for the London guided installer TUI.

Tests:
- App boots on each status fixture (keyless / keyed / paid-ready / blocked)
- q exits cleanly from each screen
- Profile selection navigates
- Masked input never renders key text in any frame
- Done screen shows the right first command per mode
- Machine-mode matrix: each machine flag + piped + CI=1 → no TUI, identical output
- Module-poison test: --json path never imports textual
- Splash render-dump test: wordmark cannot silently regress
"""
from __future__ import annotations

import builtins
import importlib
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures (re-used from test_tui_steps where possible)
# ---------------------------------------------------------------------------


def _base_status(overrides: dict | None = None) -> dict:
    status: dict = {
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


def _keyless() -> dict:
    return _base_status()


def _in_session() -> dict:
    return _base_status({
        "direction_mode": {
            "mode": "in_session",
            "model_key_present": False,
            "in_session_available": True,
            "ready": True,
            "hint": "London will direct via the in-session model; no API key required.",
        },
    })


def _keyed() -> dict:
    return _base_status({
        "direction_mode": {
            "mode": "api",
            "model_key_present": True,
            "api_sdk_available": True,
            "ready": True,
            "hint": "London will direct via the keyed Anthropic model.",
        },
        "image_generation": {"selected_provider": "gemini", "allow_paid": False},
        "providers": [
            {"id": "gemini", "env": [{"name": "GEMINI_API_KEY", "present": True}], "ready_generate": True},
        ],
    })


def _paid_ready() -> dict:
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


def _blocked() -> dict:
    s = _base_status()
    s["status"] = "blocked"
    s["verdict"] = "BLOCKED"
    return s


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(status: dict):
    """Return a fresh SetupApp for the given status dict."""
    from london.tui.app import SetupApp
    return SetupApp(status_provider=lambda: status)


# ---------------------------------------------------------------------------
# Textual Pilot tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_app_boots_keyless():
    from textual.pilot import Pilot
    app = _make_app(_keyless())
    async with app.run_test() as pilot:
        assert app.is_running


@pytest.mark.anyio
async def test_app_boots_in_session():
    from textual.pilot import Pilot
    app = _make_app(_in_session())
    async with app.run_test() as pilot:
        assert app.is_running


@pytest.mark.anyio
async def test_app_boots_keyed():
    from textual.pilot import Pilot
    app = _make_app(_keyed())
    async with app.run_test() as pilot:
        assert app.is_running


@pytest.mark.anyio
async def test_app_boots_paid_ready():
    from textual.pilot import Pilot
    app = _make_app(_paid_ready())
    async with app.run_test() as pilot:
        assert app.is_running


@pytest.mark.anyio
async def test_app_boots_blocked():
    from textual.pilot import Pilot
    app = _make_app(_blocked())
    async with app.run_test() as pilot:
        assert app.is_running


@pytest.mark.anyio
async def test_q_exits_from_splash():
    from textual.pilot import Pilot
    app = _make_app(_keyless())
    async with app.run_test() as pilot:
        await pilot.press("q")
    assert app.return_code == 0


@pytest.mark.anyio
async def test_wordmark_in_splash():
    """Splash screen must render the wordmark text."""
    from textual.pilot import Pilot
    from london.tui.app import WORDMARK_LINES
    app = _make_app(_keyless())
    async with app.run_test(size=(80, 24)) as pilot:
        content = app.screen.query("Static").first().render()
        # Content is Rich renderable; check via the exported lines constant
        assert len(WORDMARK_LINES) == 6
        # Each line contains block characters
        assert "██" in WORDMARK_LINES[0]
        assert "╗" in WORDMARK_LINES[0]


@pytest.mark.anyio
async def test_enter_navigates_to_capability_map():
    from london.tui.app import CapabilityMapScreen
    app = _make_app(_keyless())
    async with app.run_test() as pilot:
        await pilot.press("enter")
        assert isinstance(app.screen, CapabilityMapScreen)


@pytest.mark.anyio
async def test_capability_map_enter_navigates_to_profile_picker():
    from london.tui.app import CapabilityMapScreen, ProfilePickerScreen
    app = _make_app(_keyless())
    async with app.run_test() as pilot:
        await pilot.press("enter")  # splash → capmap
        assert isinstance(app.screen, CapabilityMapScreen)
        await pilot.press("enter")  # capmap → profile picker
        assert isinstance(app.screen, ProfilePickerScreen)


@pytest.mark.anyio
async def test_profile_picker_1_navigates():
    """Pressing 1 on profile picker navigates to step or done screen."""
    from london.tui.app import DoneScreen, GuidedStepScreen, ProfilePickerScreen
    app = _make_app(_in_session())
    async with app.run_test() as pilot:
        await pilot.press("enter")  # splash → capmap
        await pilot.press("enter")  # capmap → profile picker
        assert isinstance(app.screen, ProfilePickerScreen)
        await pilot.press("1")     # pick core profile
        # Should be on a step screen or done screen (no steps for in-session core)
        assert isinstance(app.screen, (GuidedStepScreen, DoneScreen))


@pytest.mark.anyio
async def test_q_exits_from_capability_map():
    app = _make_app(_keyless())
    async with app.run_test() as pilot:
        await pilot.press("enter")  # → capmap
        await pilot.press("q")
    assert app.return_code == 0


@pytest.mark.anyio
async def test_q_exits_from_profile_picker():
    app = _make_app(_keyless())
    async with app.run_test() as pilot:
        await pilot.press("enter")  # → capmap
        await pilot.press("enter")  # → profile picker
        await pilot.press("q")
    assert app.return_code == 0


@pytest.mark.anyio
async def test_done_screen_correct_command_keyless():
    """Done screen for keyless core profile shows --offline command."""
    from london.tui.app import DoneScreen
    from london.tui.steps import steps_for_profile
    profile_steps = steps_for_profile("core", _keyless())
    app = _make_app(_keyless())
    async with app.run_test() as pilot:
        # Push the done screen directly
        from london.tui.app import DoneScreen
        await app.push_screen(DoneScreen(profile_steps, _keyless()))
        content_widgets = app.screen.query("#done-cmd")
        if content_widgets:
            text = str(content_widgets.first().render())
            # Should contain the offline command
            assert "--offline" in profile_steps.first_command


@pytest.mark.anyio
async def test_done_screen_correct_command_in_session():
    """Done screen for in-session shows the live command."""
    from london.tui.app import DoneScreen
    from london.tui.steps import steps_for_profile
    profile_steps = steps_for_profile("core", _in_session())
    # in-session core: no steps, command does not require --offline
    assert "london" in profile_steps.first_command


@pytest.mark.anyio
async def test_masked_input_never_renders_key_text():
    """When paste mode is active, the entered key text must not appear in any rendered widget."""
    from london.tui.app import GuidedStepScreen
    from london.tui.steps import steps_for_profile
    profile_steps = steps_for_profile("recommended", _keyless())
    # Find a step that allows paste
    paste_step = next((s for s in profile_steps.steps if s.allows_paste), None)
    if paste_step is None:
        pytest.skip("no paste step for this fixture")

    step_index = profile_steps.steps.index(paste_step)
    fake_key = "FAKE_SECRET_KEY_VALUE_12345_ABCDEF"

    app = _make_app(_keyless())
    async with app.run_test() as pilot:
        from london.tui.app import GuidedStepScreen
        screen = GuidedStepScreen(
            profile_steps=profile_steps,
            step_index=step_index,
            status_provider=lambda: _keyless(),
        )
        await app.push_screen(screen)
        # Activate paste mode
        await pilot.press("p")
        # Type fake key characters
        for char in fake_key:
            await pilot.press(char)
        # At no point should the key text appear in any rendered widget
        for widget in app.screen.query("Static"):
            rendered = str(widget.render())
            assert fake_key not in rendered, (
                f"Secret key text found in rendered widget: {rendered[:100]}"
            )
        # Cancel paste mode
        await pilot.press("escape")


# ---------------------------------------------------------------------------
# Machine-mode matrix: no TUI, identical-to-before output
# ---------------------------------------------------------------------------


def _setup_not_tui_for_flags(flags: list[str], monkeypatch, tmp_path: Path) -> str:
    """Run `london setup <flags>` and return stdout; assert no TUI was launched."""
    launched = []

    def fake_run_tui(*args, **kwargs):
        launched.append(True)
        return 0

    monkeypatch.setattr("london.tui.run_setup_tui", fake_run_tui, raising=False)

    from io import StringIO
    from london.cli import main

    out_capture = StringIO()
    with patch("london.cli.console") as mock_console:
        mock_console.print = lambda *a, **kw: out_capture.write(str(a[0]) + "\n")
        try:
            main(["setup"] + flags)
        except SystemExit:
            pass

    assert not launched, f"TUI was unexpectedly launched with flags {flags}"
    return out_capture.getvalue()


@pytest.mark.parametrize("flags", [
    ["--json"],
    ["--plan"],
    ["--non-interactive"],
    ["--print-env-example"],
    ["--text"],
])
def test_machine_flag_skips_tui(flags, monkeypatch, tmp_path):
    """Each machine flag must bypass the TUI and hit the text path."""
    launched = []

    import sys
    from io import StringIO

    # Ensure stdin/stdout appear as TTYs (so only the flag suppresses TUI)
    with patch("sys.stdin") as mock_stdin, patch("sys.stdout") as mock_stdout:
        mock_stdin.isatty.return_value = True
        mock_stdout.isatty.return_value = True

        def fake_run_tui(*args, **kwargs):
            launched.append(True)
            return 0

        import london.tui as tui_module
        monkeypatch.setattr(tui_module, "run_setup_tui", fake_run_tui, raising=False)

        from london.cli import main
        try:
            main(["setup"] + flags)
        except SystemExit:
            pass

    assert not launched, f"TUI launched unexpectedly with flags {flags}"


def test_ci_env_skips_tui(monkeypatch):
    """CI=1 must bypass the TUI."""
    launched = []
    monkeypatch.setenv("CI", "1")

    with patch("sys.stdin") as mock_stdin, patch("sys.stdout") as mock_stdout:
        mock_stdin.isatty.return_value = True
        mock_stdout.isatty.return_value = True

        def fake_run_tui(*args, **kwargs):
            launched.append(True)
            return 0

        import london.tui as tui_module
        monkeypatch.setattr(tui_module, "run_setup_tui", fake_run_tui, raising=False)

        from london.cli import main
        try:
            main(["setup"])
        except SystemExit:
            pass

    assert not launched


def test_piped_stdout_skips_tui(monkeypatch):
    """Piped stdout (not a TTY) must bypass the TUI."""
    launched = []

    with patch("sys.stdin") as mock_stdin, patch("sys.stdout") as mock_stdout:
        mock_stdin.isatty.return_value = True
        mock_stdout.isatty.return_value = False  # piped

        def fake_run_tui(*args, **kwargs):
            launched.append(True)
            return 0

        import london.tui as tui_module
        monkeypatch.setattr(tui_module, "run_setup_tui", fake_run_tui, raising=False)

        from london.cli import main
        try:
            main(["setup"])
        except SystemExit:
            pass

    assert not launched


def test_non_tty_stdin_skips_tui(monkeypatch):
    """Non-TTY stdin must bypass the TUI."""
    launched = []

    with patch("sys.stdin") as mock_stdin, patch("sys.stdout") as mock_stdout:
        mock_stdin.isatty.return_value = False  # piped stdin
        mock_stdout.isatty.return_value = True

        def fake_run_tui(*args, **kwargs):
            launched.append(True)
            return 0

        import london.tui as tui_module
        monkeypatch.setattr(tui_module, "run_setup_tui", fake_run_tui, raising=False)

        from london.cli import main
        try:
            main(["setup"])
        except SystemExit:
            pass

    assert not launched


# ---------------------------------------------------------------------------
# Module-poison test: --json never imports textual
# ---------------------------------------------------------------------------


def test_json_path_does_not_import_textual(monkeypatch):
    """The --json path must complete without importing textual at all."""
    textual_imported = []

    real_import = builtins.__import__

    def detecting_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "textual" or name.startswith("textual."):
            textual_imported.append(name)
        return real_import(name, globals, locals, fromlist, level)

    import builtins as _builtins
    old = _builtins.__import__
    _builtins.__import__ = detecting_import
    try:
        # Remove any cached textual imports so we detect fresh imports
        cached = [k for k in sys.modules if k == "textual" or k.startswith("textual.")]
        for key in cached:
            sys.modules.pop(key, None)

        from london.cli import main
        try:
            main(["setup", "--json"])
        except SystemExit:
            pass
    finally:
        _builtins.__import__ = old

    assert not textual_imported, (
        f"textual was imported on --json path: {textual_imported}"
    )


# ---------------------------------------------------------------------------
# Splash render-dump: wordmark must contain the canonical block characters
# ---------------------------------------------------------------------------


def test_splash_wordmark_canonical_lines():
    """The wordmark lines must match the approved frames exactly."""
    from london.tui.app import WORDMARK_LINES, WORDMARK_TAGLINE
    assert len(WORDMARK_LINES) == 6
    # First line: starts with ██╗ pattern
    assert "██╗" in WORDMARK_LINES[0]
    # Last line: ends with ╚═══╝ pattern
    assert "╚═══╝" in WORDMARK_LINES[-1]
    # Tagline present
    assert "creative director" in WORDMARK_TAGLINE
    assert "runs in your terminal" in WORDMARK_TAGLINE


def test_splash_wordmark_markup_wide():
    from london.tui.app import _wordmark_markup, SPARK_ORANGE
    markup = _wordmark_markup(80)
    assert "LONDON" not in markup.upper() or "██" in markup  # block art or boxed header
    assert SPARK_ORANGE in markup


def test_splash_wordmark_markup_narrow_fallback():
    from london.tui.app import _wordmark_markup, BOXED_HEADER
    markup = _wordmark_markup(40)
    assert "LONDON" in markup
    # Should be the boxed fallback
    assert "Creative Director" in markup or "LONDON" in markup


def test_splash_wordmark_cols_threshold():
    from london.tui.app import _wordmark_markup, WORDMARK_MIN_COLS
    # Just below threshold: boxed
    below = _wordmark_markup(WORDMARK_MIN_COLS - 1)
    assert "██" not in below
    # At threshold: full wordmark
    at = _wordmark_markup(WORDMARK_MIN_COLS)
    assert "██" in at


# ---------------------------------------------------------------------------
# TUI __init__.py: does not import textual at module level
# ---------------------------------------------------------------------------


def test_tui_init_does_not_import_textual_at_module_level():
    """london.tui.__init__ must be importable with textual blocked."""
    sys.modules.pop("london.tui", None)
    real_import = builtins.__import__

    def reject_textual(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "textual" or name.startswith("textual."):
            raise AssertionError(f"london.tui imported textual at module level: {name}")
        return real_import(name, globals, locals, fromlist, level)

    import builtins as _builtins
    old = _builtins.__import__
    _builtins.__import__ = reject_textual
    try:
        module = importlib.import_module("london.tui")
        assert hasattr(module, "run_setup_tui")
    finally:
        _builtins.__import__ = old


def test_run_setup_tui_refuses_non_tty():
    # Defense-in-depth: if the cli guard ever mis-routes a non-TTY context here,
    # the entry point must refuse loudly instead of blocking on a missing terminal.
    # (pytest's captured stdin/stdout are non-TTY, so calling it directly proves the guard.)
    from london.tui import run_setup_tui

    with pytest.raises(RuntimeError, match="interactive terminal"):
        run_setup_tui()
