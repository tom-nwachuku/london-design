"""Skill path-portability guard (ENGINE-01 correctness, not publish cleanup).

The packaged ``london-creative-director.skill`` carried a hardcoded author path —
``cd /Users/bytedance/Projects/creative-director && source .venv/bin/activate &&  # EXPECTED-FIXTURE
python scripts/brand_query.py --query "..." --all`` — in its SKILL.md (Before-Anything
block) and ``references/phase1-research-tools.md`` (London's Brain Query block). On any
machine that is not the author's, that ``cd`` is a dead command: **the skill literally
cannot query the brain.** This is engine CORRECTNESS — the brain-query instruction must
be portable (``london brain query "..."`` / the ``london_brain_query`` MCP tool).

This guard asserts that NO ``.md`` member of the skill zip contains
``/Users/bytedance``. It mirrors ``test_walk_the_build.py::_read_skill_text``: the  # EXPECTED-FIXTURE
``.skill`` zip is gitignored and is NOT present in CI / fresh checkouts, so when it is
absent the test ``skip``s (nothing to guard); when it is present (a local working tree)
it asserts the repackaged skill is portable.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[1]
SKILL_PATH = REPO_ROOT / "london-creative-director.skill"

# The hardcoded author home path the skill must never carry.
FORBIDDEN_AUTHOR_PATH = "/Users/bytedance"  # EXPECTED-FIXTURE


def _md_members(archive: zipfile.ZipFile) -> list[str]:
    """Every Markdown member of the skill zip (SKILL.md + references/*.md)."""
    return [name for name in archive.namelist() if name.lower().endswith(".md")]


def test_skill_has_no_hardcoded_author_paths():
    """No ``.md`` member of the packaged skill embeds ``/Users/bytedance``.  # EXPECTED-FIXTURE

    Skips when the skill zip is absent (gitignored; not in CI / fresh checkouts),
    mirroring the skip-if-absent guard in test_walk_the_build.py.
    """
    if not SKILL_PATH.exists():
        pytest.skip(
            f"{SKILL_PATH.name} is gitignored and absent here (present only in a local "
            "working tree); nothing to guard in this environment."
        )

    offenders: list[str] = []
    with zipfile.ZipFile(SKILL_PATH) as archive:
        md_members = _md_members(archive)
        assert md_members, "expected at least one .md member in the skill zip"
        for member in md_members:
            text = archive.read(member).decode("utf-8", errors="replace")
            if FORBIDDEN_AUTHOR_PATH in text:
                offenders.append(member)

    assert not offenders, (
        "The packaged london-creative-director.skill still embeds the hardcoded author "
        f"path {FORBIDDEN_AUTHOR_PATH!r} in: {offenders}. On any other machine the "
        "brain-query command is dead. Repackage the skill with the portable "
        "'london brain query \"...\"' (or the london_brain_query MCP tool) instruction. "
        "This is engine correctness (ENGINE-01), not publish cleanup."
    )
