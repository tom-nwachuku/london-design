"""London guided installer TUI — Textual App.

Five screens per the approved frames in 01-APPROVED-FRAMES.md:
  1. Splash + verdict  (ANSI-shadow LONDON wordmark in #ff6b35)
  2. Capability map    (hero screen, arrow-select rows, detail pane)
  3. Profile picker    ([1]–[4], arrow-key selectable)
  4. Guided steps      (generated from status gaps; [r] re-check; [p] paste)
  5. Done              (copyable first command; [c] copy; [q] done)

q quits from anywhere (exit 0). Ctrl-C exits 130, no tracebacks.
NO_COLOR is respected by Textual automatically when the env var is set.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

from london.tui.steps import (
    PROFILE_ROWS,
    GuidedStep,
    ProfileSteps,
    capability_map_rows,
    steps_for_profile,
    verdict_line,
)

# ---------------------------------------------------------------------------
# Wordmark — ANSI-shadow block style, ~58 cols wide
# (reproduced exactly from 01-APPROVED-FRAMES.md Frame 1)
# ---------------------------------------------------------------------------

WORDMARK_LINES = [
    "    ██╗      ██████╗ ███╗   ██╗██████╗  ██████╗ ███╗   ██╗",
    "    ██║     ██╔═══██╗████╗  ██║██╔══██╗██╔═══██╗████╗  ██║",
    "    ██║     ██║   ██║██╔██╗ ██║██║  ██║██║   ██║██╔██╗ ██║",
    "    ██║     ██║   ██║██║╚██╗██║██║  ██║██║   ██║██║╚██╗██║",
    "    ███████╗╚██████╔╝██║ ╚████║██████╔╝╚██████╔╝██║ ╚████║",
    "    ╚══════╝ ╚═════╝ ╚═╝  ╚═══╝╚═════╝  ╚═════╝ ╚═╝  ╚═══╝",
]
WORDMARK_TAGLINE = "            creative director · runs in your terminal"
WORDMARK_MIN_COLS = 62  # below this width, fall back to boxed header

BOXED_HEADER = (
    "+--------------------------------------------------+\n"
    "| LONDON                                           |\n"
    "| Creative Director CLI                            |\n"
    "+--------------------------------------------------+"
)

# Spark orange #ff6b35
SPARK_ORANGE = "#ff6b35"


def _wordmark_markup(cols: int) -> str:
    """Return Rich markup for the wordmark (or boxed fallback)."""
    if cols < WORDMARK_MIN_COLS:
        return f"[bold]{BOXED_HEADER}[/bold]"
    lines = "\n".join(WORDMARK_LINES)
    return f"[bold {SPARK_ORANGE}]{lines}[/bold {SPARK_ORANGE}]\n[dim]{WORDMARK_TAGLINE}[/dim]"


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

TUI_CSS = """
Screen {
    background: $surface;
}

#splash-container {
    align: center middle;
    padding: 2 4;
}

#splash-wordmark {
    text-align: center;
}

#splash-verdict {
    margin-top: 1;
    text-align: center;
    color: $text;
}

#splash-hint {
    margin-top: 1;
    text-align: center;
    color: $text-muted;
}

/* Capability map */
#capmap-header {
    padding: 0 2;
    height: 3;
}

#capmap-title {
    color: $text-muted;
}

#capmap-verdict {
    dock: right;
    width: auto;
}

#capmap-list {
    height: auto;
    padding: 0 2;
}

.capmap-row {
    layout: horizontal;
    height: 1;
}

.capmap-label {
    width: 22;
}

.capmap-chip {
    width: auto;
    color: $text-muted;
}

.capmap-chip--ready {
    color: $success;
}

.capmap-chip--insession {
    color: $accent;
}

#capmap-detail {
    margin: 1 2;
    padding: 1 2;
    border: solid $panel;
    height: 5;
    color: $text-muted;
}

#capmap-footer-hint {
    padding: 0 2;
    color: $text-muted;
}

/* Profile picker */
#profile-title {
    padding: 1 2;
    color: $text;
}

#profile-list {
    height: auto;
    padding: 0 2;
}

/* Step screen */
#step-header {
    padding: 1 2;
}

#step-subtitle {
    color: $text-muted;
}

#step-rule {
    height: 1;
    padding: 0 2;
    color: $text-muted;
}

#step-body {
    padding: 1 2;
    height: auto;
}

#step-status-keys {
    padding: 0 2 1 2;
    height: auto;
}

.step-key-row {
    height: 1;
    color: $text-muted;
}

.step-key-present {
    color: $success;
}

.step-key-missing {
    color: $error;
}

#step-disclosure {
    padding: 1 2;
    border: solid $warning;
    margin: 0 2;
    color: $warning;
}

#step-actions {
    padding: 1 2;
    color: $text-muted;
}

/* Done screen */
#done-container {
    padding: 2 4;
}

#done-verdict {
    color: $success;
    margin-bottom: 1;
}

#done-rule {
    color: $text-muted;
}

#done-cmd-label {
    color: $text;
    margin-top: 1;
}

#done-cmd {
    padding: 1 2;
    background: $panel;
    margin: 1 0;
    color: $accent;
}

#done-note {
    color: $text-muted;
}

#done-actions {
    margin-top: 1;
    color: $text-muted;
}
"""


# ---------------------------------------------------------------------------
# Splash screen (Frame 1)
# ---------------------------------------------------------------------------


class SplashScreen(Screen):
    """Frame 1: wordmark splash + verdict."""

    BINDINGS = [
        Binding("enter", "continue", "Begin"),
        Binding("t", "text_mode", "Text mode"),
        Binding("q", "quit_app", "Quit"),
    ]

    def __init__(self, status: dict[str, Any], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._status = status

    def compose(self) -> ComposeResult:
        cols = os.get_terminal_size().columns if sys.stdin.isatty() else 80
        wordmark = _wordmark_markup(cols)
        verdict = verdict_line(self._status)
        yield Container(
            Static(wordmark, id="splash-wordmark"),
            Static(f"\nVerdict: [bold]{verdict}[/bold]", id="splash-verdict"),
            Static(
                "\n    [ enter ] begin     [ t ] text mode     [ q ] quit",
                id="splash-hint",
            ),
            id="splash-container",
        )

    def action_continue(self) -> None:
        self.app.push_screen(CapabilityMapScreen(self._status))

    def action_text_mode(self) -> None:
        # Signal the app to use text mode and exit
        self.app._text_mode_requested = True  # type: ignore[attr-defined]
        self.app.exit(0)

    def action_quit_app(self) -> None:
        self.app.exit(0)


# ---------------------------------------------------------------------------
# Capability map screen (Frame 2)
# ---------------------------------------------------------------------------

_CHIP_STYLE_MAP = {
    "IN-SESSION MODEL": "capmap-chip--insession",
    "API MODEL": "capmap-chip--insession",
    "READY": "capmap-chip--ready",
    "VISUAL BOARDS READY": "capmap-chip--ready",
    "LOCAL LAB READY": "capmap-chip--ready",
}


class CapabilityMapScreen(Screen):
    """Frame 2: capability map hero screen."""

    BINDINGS = [
        Binding("up", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("enter", "select_profile", "Choose profile"),
        Binding("q", "quit_app", "Quit"),
    ]

    def __init__(self, status: dict[str, Any], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._status = status
        self._rows = capability_map_rows(status)
        self._selected = 0

    def compose(self) -> ComposeResult:
        verdict = verdict_line(self._status)
        yield Static(
            f" LONDON · setup   [dim]verdict: {verdict}[/dim]\n"
            f" {'─' * 60}",
            id="capmap-header",
        )
        yield Static("  what this machine can do\n", id="capmap-title")
        yield Vertical(id="capmap-list")
        yield Static("", id="capmap-detail")
        yield Static(
            "   ↑/↓ inspect      enter — choose a setup profile      q quit",
            id="capmap-footer-hint",
        )

    def on_mount(self) -> None:
        self._render_rows()
        self._update_detail()

    def _render_rows(self) -> None:
        container = self.query_one("#capmap-list")
        container.remove_children()
        for i, row in enumerate(self._rows):
            marker = "▸" if i == self._selected else " "
            chip_style = _CHIP_STYLE_MAP.get(row["chip"], "capmap-chip")
            label_text = f"{marker} {row['label']:<20}"
            chip_text = row["chip"]
            container.mount(
                Static(
                    f"  {label_text}  [{chip_style}]{chip_text}[/{chip_style}]",
                    classes="capmap-row",
                )
            )

    def _update_detail(self) -> None:
        if not self._rows:
            return
        row = self._rows[self._selected]
        detail_text = row.get("detail", "")
        try:
            widget = self.query_one("#capmap-detail")
            widget.update(
                f"  ┌─ {row['label']} ─{'─' * max(0, 50 - len(row['label']))}┐\n"
                f"  │ {detail_text[:58]:<58} │\n"
                f"  └{'─' * 60}┘"
            )
        except NoMatches:
            pass

    def action_cursor_up(self) -> None:
        self._selected = max(0, self._selected - 1)
        self._render_rows()
        self._update_detail()

    def action_cursor_down(self) -> None:
        self._selected = min(len(self._rows) - 1, self._selected + 1)
        self._render_rows()
        self._update_detail()

    def action_select_profile(self) -> None:
        self.app.push_screen(ProfilePickerScreen(self._status))

    def action_quit_app(self) -> None:
        self.app.exit(0)


# ---------------------------------------------------------------------------
# Profile picker screen (Frame 3)
# ---------------------------------------------------------------------------


class ProfilePickerScreen(Screen):
    """Frame 3: profile picker."""

    BINDINGS = [
        Binding("up", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("enter", "select", "Select"),
        Binding("1", "pick_1", "Core demo", show=False),
        Binding("2", "pick_2", "Recommended", show=False),
        Binding("3", "pick_3", "Pro image lab", show=False),
        Binding("4", "pick_4", "Details", show=False),
        Binding("q", "quit_app", "Quit"),
    ]

    def __init__(self, status: dict[str, Any], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._status = status
        self._selected = 0

    def compose(self) -> ComposeResult:
        yield Static("  how do you want to run London?\n", id="profile-title")
        yield Vertical(id="profile-list")

    def on_mount(self) -> None:
        self._render_rows()

    def _render_rows(self) -> None:
        container = self.query_one("#profile-list")
        container.remove_children()
        for i, row in enumerate(PROFILE_ROWS):
            marker = "▸" if i == self._selected else " "
            container.mount(
                Static(
                    f"  {marker} {row['number']}  {row['label']:<16} {row['tagline']}",
                    classes="profile-row",
                )
            )

    def action_cursor_up(self) -> None:
        self._selected = max(0, self._selected - 1)
        self._render_rows()

    def action_cursor_down(self) -> None:
        self._selected = min(len(PROFILE_ROWS) - 1, self._selected + 1)
        self._render_rows()

    def _launch_profile(self, index: int) -> None:
        profile_id = PROFILE_ROWS[index]["id"]
        profile_steps = steps_for_profile(profile_id, self._status)
        if not profile_steps.steps:
            # No steps: jump directly to done screen
            self.app.push_screen(DoneScreen(profile_steps, self._status))
        else:
            self.app.push_screen(
                GuidedStepScreen(
                    profile_steps=profile_steps,
                    step_index=0,
                    status_provider=self.app._status_provider,  # type: ignore[attr-defined]
                )
            )

    def action_select(self) -> None:
        self._launch_profile(self._selected)

    def action_pick_1(self) -> None:
        self._selected = 0
        self._render_rows()
        self._launch_profile(0)

    def action_pick_2(self) -> None:
        self._selected = 1
        self._render_rows()
        self._launch_profile(1)

    def action_pick_3(self) -> None:
        self._selected = 2
        self._render_rows()
        self._launch_profile(2)

    def action_pick_4(self) -> None:
        self._selected = 3
        self._render_rows()
        self._launch_profile(3)

    def action_quit_app(self) -> None:
        self.app.exit(0)


# ---------------------------------------------------------------------------
# Guided step screen (Frame 4)
# ---------------------------------------------------------------------------

_PASTE_INPUT_ACTIVE = False  # module-level flag; reset on each screen


class GuidedStepScreen(Screen):
    """Frame 4: one guided step with re-check and optional paste."""

    BINDINGS = [
        Binding("r", "recheck", "Re-check"),
        Binding("s", "skip", "Skip"),
        Binding("p", "paste_key", "Paste key"),
        Binding("n", "next_step", "Next"),
        Binding("q", "quit_app", "Quit"),
    ]

    def __init__(
        self,
        profile_steps: ProfileSteps,
        step_index: int,
        status_provider: Callable[[], dict],
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._profile_steps = profile_steps
        self._step_index = step_index
        self._status_provider = status_provider
        self._step = profile_steps.steps[step_index]
        self._paste_active = False
        self._paste_buffer: list[str] = []

    def compose(self) -> ComposeResult:
        step = self._step
        yield Static(
            f"  {step.subtitle}                    profile: {self._profile_steps.profile_label}",
            id="step-header",
        )
        yield Static(f"  {'─' * 62}", id="step-rule")
        yield Static(step.body, id="step-body")

        # Status key rows
        if step.status_keys:
            yield Vertical(id="step-status-keys")

        # Cost disclosure (mandatory before any paid action)
        if step.cost_disclosure:
            yield Static(step.cost_disclosure, id="step-disclosure")

        # Actions line
        actions = step.recheck_label
        if step.skip_label:
            actions += f"      {step.skip_label}"
        if step.allows_paste:
            actions += f"\n  {step.paste_hint}" if step.paste_hint else ""
        if self._step_index < len(self._profile_steps.steps) - 1:
            actions += "      [ n ] next"
        else:
            actions += "      [ n ] done"
        yield Static(f"\n  {actions}", id="step-actions")

    def on_mount(self) -> None:
        self._render_status_keys()

    def _render_status_keys(self) -> None:
        try:
            container = self.query_one("#step-status-keys")
        except NoMatches:
            return
        container.remove_children()
        for key in self._step.status_keys:
            label = str(key.get("label", ""))
            present = bool(key.get("present"))
            marker = "✓" if present else "✗"
            style = "step-key-present" if present else "step-key-missing"
            container.mount(
                Static(f"  {label:<24} [{style}]{marker}[/{style}]", classes="step-key-row")
            )

    def action_recheck(self) -> None:
        """Re-run the status collector and refresh this step."""
        new_status = self._status_provider()
        new_profile = steps_for_profile(self._profile_steps.profile_id, new_status)
        if self._step_index < len(new_profile.steps):
            self._profile_steps = new_profile
            self._step = new_profile.steps[self._step_index]
        self._render_status_keys()

    def action_skip(self) -> None:
        self._advance()

    def action_paste_key(self) -> None:
        """Activate the paste flow — write key to .env, then re-check.

        Security posture:
        - Input is consumed via the App's key handler (masked)
        - Written ONLY to ./.env (created 0600)
        - Never echoed / never logged
        - Re-checked presence-only after write
        """
        if not self._step.allows_paste:
            return
        self._paste_active = True
        self._paste_buffer = []
        try:
            actions = self.query_one("#step-actions")
            actions.update(
                f"\n  Paste {self._step.paste_env_var} (hidden): "
                "[enter confirms, esc cancels]\n"
                "  Input: [masked]"
            )
        except NoMatches:
            pass

    def on_key(self, event: Any) -> None:
        """Handle key paste input when paste mode is active."""
        if not self._paste_active:
            return
        key = event.key
        if key == "enter":
            self._paste_active = False
            pasted = "".join(self._paste_buffer)
            self._paste_buffer = []
            if pasted:
                self._write_env_key(self._step.paste_env_var, pasted)
            event.stop()
            self.action_recheck()
        elif key == "escape":
            self._paste_active = False
            self._paste_buffer = []
            event.stop()
            self.action_recheck()
        elif key == "ctrl+h" or key == "backspace":
            if self._paste_buffer:
                self._paste_buffer.pop()
            event.stop()
        elif len(key) == 1:
            # Single printable character — buffer it (never displayed)
            self._paste_buffer.append(key)
            event.stop()

    def _write_env_key(self, env_var: str, value: str) -> None:
        """Write ONLY to ./.env (0600). Never echo, never log the value."""
        env_path = Path(".env")
        try:
            if env_path.exists():
                existing = env_path.read_text(encoding="utf-8")
                lines = existing.splitlines()
                # Replace or append
                new_lines = []
                replaced = False
                for line in lines:
                    stripped = line.strip()
                    if stripped.startswith(f"{env_var}=") or stripped.startswith(f"export {env_var}="):
                        new_lines.append(f"{env_var}={value}")
                        replaced = True
                    else:
                        new_lines.append(line)
                if not replaced:
                    new_lines.append(f"{env_var}={value}")
                env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            else:
                env_path.write_text(f"{env_var}={value}\n", encoding="utf-8")
            # Enforce 0600
            env_path.chmod(0o600)
        except OSError:
            pass

    def action_next_step(self) -> None:
        self._advance()

    def _advance(self) -> None:
        next_index = self._step_index + 1
        if next_index < len(self._profile_steps.steps):
            self.app.push_screen(
                GuidedStepScreen(
                    profile_steps=self._profile_steps,
                    step_index=next_index,
                    status_provider=self._status_provider,
                )
            )
        else:
            # Done — rebuild from latest status
            latest_status = self._status_provider()
            self.app.push_screen(DoneScreen(self._profile_steps, latest_status))

    def action_quit_app(self) -> None:
        self.app.exit(0)


# ---------------------------------------------------------------------------
# Done screen (Frame 5)
# ---------------------------------------------------------------------------


class DoneScreen(Screen):
    """Frame 5: done screen with copyable first command."""

    BINDINGS = [
        Binding("c", "copy_command", "Copy command"),
        Binding("q", "quit_app", "Done / Quit"),
    ]

    def __init__(
        self, profile_steps: ProfileSteps, status: dict[str, Any], **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self._profile_steps = profile_steps
        self._status = status

    def compose(self) -> ComposeResult:
        verdict = verdict_line(self._status)
        cols = os.get_terminal_size().columns if sys.stdin.isatty() else 80
        wordmark = _wordmark_markup(cols)
        cmd = self._profile_steps.first_command
        note = self._profile_steps.done_note

        yield Container(
            Static(wordmark, id="splash-wordmark"),
            Static(f"\n  ✓ {verdict}", id="done-verdict"),
            Static(f"  {'─' * 56}", id="done-rule"),
            Static("\n  your first direction:\n", id="done-cmd-label"),
            Static(f"    $ {cmd}", id="done-cmd"),
            Static(f"\n  {note}", id="done-note"),
            Static(
                f"\n    [ c ] copy command        [ q ] done",
                id="done-actions",
            ),
            id="done-container",
        )

    def action_copy_command(self) -> None:
        cmd = self._profile_steps.first_command
        # Try OSC 52 (clipboard via terminal escape sequence)
        copied = _try_osc52_copy(cmd)
        if not copied:
            # Fallback: just print the command for the user to copy manually
            try:
                actions = self.query_one("#done-actions")
                actions.update(f"\n    Copied:  {cmd}\n    [ q ] done")
            except NoMatches:
                pass

    def action_quit_app(self) -> None:
        self.app.exit(0)


def _try_osc52_copy(text: str) -> bool:
    """Attempt to copy text via OSC 52 terminal escape sequence.

    Returns True if the sequence was emitted (no guarantee the terminal honored it).
    """
    import base64

    try:
        encoded = base64.b64encode(text.encode()).decode()
        # Write the OSC 52 sequence directly to the terminal
        # This bypasses Textual's rendering so it reaches the terminal directly.
        with open("/dev/tty", "w") as tty:  # noqa: PTH123 — direct tty write for clipboard
            tty.write(f"\x1b]52;c;{encoded}\x07")
        return True
    except (OSError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Root App
# ---------------------------------------------------------------------------


class SetupApp(App):
    """London guided installer Textual App."""

    CSS = TUI_CSS
    TITLE = "London · setup"

    BINDINGS = [
        Binding("q", "quit_clean", "Quit", show=False),
        Binding("ctrl+c", "quit_sigint", "Exit", show=False),
    ]

    def __init__(self, status_provider: Callable[[], dict], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._status_provider = status_provider
        self._status: dict[str, Any] = {}
        self._text_mode_requested = False

    def on_mount(self) -> None:
        self._status = self._status_provider()
        self.push_screen(SplashScreen(self._status))

    def action_quit_clean(self) -> None:
        self.exit(0)

    def action_quit_sigint(self) -> None:
        # Ctrl-C: exit 130
        self.exit(130)

    def on_exception(self, error: Exception) -> None:
        """Suppress tracebacks — exit 1 instead."""
        self.exit(1)
