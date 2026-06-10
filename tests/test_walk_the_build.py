"""Walk-the-build parity guard (Workstream F, scaffolded in A1).

Two cross-layer invariants:

1. PERSONA / GATE PARITY (passes today): the gate list single-sourced in
   ``london.persona`` is the same list re-exported through ``london.models`` — proof
   that the four persona/gate duplication sites collapsed onto one source (WALK-01).

2. NO ``bytedance`` IN THE SKILL (green since 04.6-03): the
   ``london-creative-director.skill`` zip's brain-query block was repackaged off the
   author's machine — the stale ``cd /Users/bytedance/Projects/creative-director``  # EXPECTED-FIXTURE
   path in ``SKILL.md`` and ``references/phase1-research-tools.md`` was replaced with
   the portable ``london brain query "..."`` / ``london_brain_query`` MCP-tool
   instruction (ENGINE-01 correctness). The ``xfail`` marker was removed in 04.6-03,
   so this is now a plain green assertion.

   The ``.skill`` zip is gitignored and is NOT present in CI / fresh checkouts. When
   it is absent the bytedance test ``skip``s (nothing to guard); when it is present
   (a local working tree) it asserts the repackaged skill is portable.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from london import models, persona

REPO_ROOT = Path(__file__).parents[1]
SKILL_PATH = REPO_ROOT / "london-creative-director.skill"

# Files inside the skill zip that carry the stale absolute path today.
SKILL_TEXT_MEMBERS = (
    "london-creative-director/SKILL.md",
    "london-creative-director/references/phase1-research-tools.md",
)


def test_persona_is_the_single_source_for_the_seven_gates():
    # persona.py is the canonical copy; models.py must re-export the same object/values.
    assert persona.GATE_IDS == models.GATE_IDS
    assert persona.GATE_NAMES == models.GATE_NAMES
    # The gate-name map covers exactly the gate ids — no drift between the two encodings.
    assert tuple(persona.GATE_NAMES.keys()) == persona.GATE_IDS
    assert len(persona.GATE_IDS) == 7


def _read_skill_text() -> str:
    """Return the concatenated text of the skill members, or skip if the skill is absent."""
    if not SKILL_PATH.exists():
        pytest.skip(
            f"{SKILL_PATH.name} is gitignored and absent here (present only in a local "
            "working tree); nothing to guard in this environment."
        )
    chunks: list[str] = []
    with zipfile.ZipFile(SKILL_PATH) as archive:
        names = set(archive.namelist())
        for member in SKILL_TEXT_MEMBERS:
            if member in names:
                chunks.append(archive.read(member).decode("utf-8", errors="replace"))
    return "\n".join(chunks)


def test_skill_has_no_bytedance_path():
    # Flipped from xfail in 04.6-03: the .skill is repackaged with portable
    # brain-query paths (no /Users/bytedance), so this now asserts green directly.  # EXPECTED-FIXTURE
    # Still skips when the zip is absent (gitignored / not in CI) via _read_skill_text.
    text = _read_skill_text()
    assert "bytedance" not in text.lower()
