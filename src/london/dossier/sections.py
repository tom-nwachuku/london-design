"""Dossier section order contract."""

from __future__ import annotations

# The 10 dossier sections, in the locked visual-first order. Each tuple is
# (anchor id, subnav label). The subnav, scroll-spy, and render loop derive from
# this single source of truth.
SECTIONS: tuple[tuple[str, str], ...] = (
    ("moodboard", "Moodboard"),
    ("routes", "Routes"),
    ("comparison", "Comparison"),
    ("font-lab", "Font Lab"),
    ("conversation", "Conversation"),
    ("constraints", "Constraints"),
    ("evidence", "Evidence"),
    ("grader", "Quality Check"),
    ("handoff", "Handoff"),
    ("receipts", "Audit"),
)

__all__ = ["SECTIONS"]
