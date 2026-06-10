"""London guided installer TUI — lazy-imported by cli.py only in a real TTY.

Entry point: ``run_setup_tui(status_provider)`` receives a callable that returns
the ``collect_setup_status()`` dict and launches the Textual App.
"""
from __future__ import annotations

from typing import Callable

StatusProvider = Callable[[], dict]


def run_setup_tui(status_provider: StatusProvider | None = None) -> int:
    """Launch the guided installer TUI.

    Returns the exit code (0 = done/quit cleanly, 130 = Ctrl-C).
    Only import textual here — never at module top-level so that the ``--json``
    / machine-mode paths are completely free of textual.
    """
    import sys  # noqa: PLC0415

    # Defense-in-depth: the cli guard should never route a non-TTY here, but if
    # it does, refuse loudly instead of blocking on a terminal that isn't there.
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise RuntimeError(
            "The guided installer needs an interactive terminal. "
            "Use `london setup --text` (or --json) in non-interactive contexts."
        )

    from london.tui.app import SetupApp  # noqa: PLC0415 — intentional lazy import

    if status_provider is None:
        from london.setup_checks import collect_setup_status
        from london.config import load_config

        def status_provider() -> dict:  # type: ignore[no-redef]
            return collect_setup_status(config=load_config())

    app = SetupApp(status_provider=status_provider)
    result = app.run()
    return result if isinstance(result, int) else 0
