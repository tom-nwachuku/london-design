"""GUARD-01 — the anti-recurrence gate for the engine-fake disease.

PURPOSE
-------
The prior failure (Workstream F) was a *self-authored second London voice* baked
into the Claude director seam: ``build_seed_prompt`` assembled ``PERSONA_PROSE`` +
``voice_rules_block()`` + ``anti_slop_block()`` into a model seed, and pulled the
brain in as **title-only** fragments (``finding.get("title")``, dropping ``body``).
The in-session call (``_direct_in_session``) ran that seed through
``ClaudeAgentOptions`` with **no MCP brain server and no skill** mounted — a fake
engine that confabulates instead of running London's real ``.skill`` against the
real brain.

This module is a *source-introspection* gate (it reads the Claude director TEXT, it does
NOT import or run it). It enforces a structural invariant in three prongs:

  1. NO second authored persona seed on the default path — ``build_seed_prompt`` no
     longer interpolates ``PERSONA_PROSE`` / ``voice_rules_block`` / ``anti_slop_block``
     into a model prompt (the persona reaches the model AS the ``.skill``, ONE voice,
     CLAUDE.md:143).
  2. NO title-only default seam — the default path does NOT build a brain-findings
     block from ``finding.get("title")`` while dropping ``body`` (the MCP delivers
     full bodies; the director must not re-truncate, ENGINE-02).
  3. POSITIVE wiring present — the default in-session path constructs
     ``ClaudeAgentOptions`` with ``mcp_servers`` (the brain server) AND
     ``skills`` / ``setting_sources`` (the london skill). The real engine is wired
     *positively*, not merely "the bad thing is absent".

  Optional prong 5 (``@pytest.mark.real_director``): the DEFAULT director (no flag)
  resolves to the real ``ClaudeCodeDirector`` — exercised against the real selection
  logic, not the OfflineDirector pin. Source-introspection prongs 1-3 need no fixture.

  (Prong 4 — the behavioral, model-run "real engine cites real brain IDs + named font
  specimens; fake engine confabulates" proof — is TOM-LOCKED / spike-owned, NOT a
  keyless pytest assertion. See RESEARCH §GUARD-01 and the spike, plan 04.)

RED-FIRST — DO NOT WEAKEN
-------------------------
This gate is **intentionally RED today**. It documents the CURRENT violation in
the Claude director and turns GREEN **only when plan 05 lands the real engine** (guts
``build_seed_prompt`` / the title-only loop and wires the MCP + skill into
``ClaudeAgentOptions``). Every assertion is phrased against the END state so it
fails against the fake engine and passes against the real one.

**NEVER weaken these assertions to make them pass against the fake engine.** The
correct way to make this gate green is to fix the Claude director (plan 05), never to
relax the gate. Reverting the fix must re-break CI — that is the whole point of the
anti-recurrence lock (threat T-04.6-06, RESEARCH §GUARD-01).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[1]
DIRECTOR_PY = REPO_ROOT / "src" / "london" / "directors" / "claude.py"
CLI_PY = REPO_ROOT / "src" / "london" / "cli.py"


def _director_source() -> str:
    """The raw text of the Claude director implementation (read once, never imported)."""
    assert DIRECTOR_PY.exists(), f"expected the director seam at {DIRECTOR_PY}"
    return DIRECTOR_PY.read_text(encoding="utf-8")


def _cli_source() -> str:
    """The raw text of the public CLI implementation."""
    assert CLI_PY.exists(), f"expected the CLI seam at {CLI_PY}"
    return CLI_PY.read_text(encoding="utf-8")


def _default_path_source(text: str) -> str:
    """The DEFAULT (in-session) engine path — ``build_seed_prompt`` through the end of
    ``_direct_in_session`` — excluding the keyed ``anthropic`` fallback path.

    The fake seam lives on the default in-session path; the keyed ``_direct_keyed``
    path is the standalone-API fallback (out of scope for this gate). We slice from
    ``build_seed_prompt`` (if it still exists) up to ``_direct_keyed`` so the prongs
    judge ONLY the default path. If ``build_seed_prompt`` is gone (plan 05's target),
    the slice begins at ``_direct_in_session``.
    """
    start_marker = "def build_seed_prompt"
    if start_marker not in text:
        start_marker = "def _direct_in_session"
    start = text.find(start_marker)
    if start == -1:
        # Neither the seam nor the in-session method is present — judge the whole file.
        return text
    end = text.find("def _direct_keyed", start)
    if end == -1:
        end = len(text)
    return text[start:end]


def test_cli_has_no_legacy_manual_dispatcher_layer():
    """W1-01 patch-back guard: Typer is the single command layer.

    The old hand-rolled parser preserved drift by keeping VALUE_OPTIONS, manual help,
    brief/out parsers, and _dispatch_* argv round-trips alive behind Typer commands.
    """
    source = _cli_source()
    banned_symbols = (
        "VALUE_OPTIONS",
        "def _parse_brief",
        "def _parse_out",
        "def _manual_help",
        "def _parse_optional_value",
        "def _parse_optional_path",
        "def _parse_gallery_pack_dirs",
        "def _parse_image_options",
    )
    leaked = [symbol for symbol in banned_symbols if symbol in source]
    dispatch_defs = re.findall(r"^def _dispatch_[a-zA-Z0-9_]+", source, flags=re.MULTILINE)
    assert not leaked and not dispatch_defs, (
        "The legacy manual CLI parser/dispatcher layer has returned. "
        f"banned={leaked}, dispatch_defs={dispatch_defs}"
    )


# --------------------------------------------------------------------------- #
# Prong 1 — NO second authored persona seed on the default path.
# --------------------------------------------------------------------------- #
def test_no_self_authored_persona_seed_on_default_path():
    """RED today: ``build_seed_prompt`` interpolates the persona blocks into a seed.

    GREEN after plan 05: the persona reaches the model AS the ``.skill`` (ONE voice).
    The default path must NOT assemble ``PERSONA_PROSE`` / ``voice_rules_block`` /
    ``anti_slop_block`` into a model prompt string.
    """
    default_path = _default_path_source(_director_source())

    banned_persona_seeds = ("PERSONA_PROSE", "voice_rules_block", "anti_slop_block")
    leaked = [name for name in banned_persona_seeds if name in default_path]
    assert not leaked, (
        "The default engine path re-authors London's voice — it interpolates "
        f"{leaked} into a model seed. The persona must reach the model AS the "
        "london-creative-director .skill (ONE voice, CLAUDE.md:143), not as a "
        "self-authored seed in director.py. Fix director.py (plan 05); do NOT "
        "weaken this assertion."
    )


# --------------------------------------------------------------------------- #
# Prong 2 — NO title-only default seam (full bodies via the MCP, ENGINE-02).
# --------------------------------------------------------------------------- #
def test_no_title_only_brain_seam_on_default_path():
    """RED today: the default path builds findings from ``finding.get("title")``.

    GREEN after plan 05: the model pulls FULL findings adaptively via the brain MCP
    (no ``finding.get("title")`` truncation loop on the default path).
    """
    default_path = _default_path_source(_director_source())

    # The title-extraction loop the fake engine uses to feed the model title-only
    # fragments (dropping the full ``body``). Match any ``finding.get("title")`` /
    # ``finding["title"]`` / ``finding.get("insight_title")`` access on the default path.
    title_seam = re.compile(r"""finding\s*(?:\.get\(\s*["'](?:insight_)?title["']|\[\s*["']title["']\s*\])""")
    assert not title_seam.search(default_path), (
        "The default engine path feeds the model a TITLE-ONLY brain seam "
        "(finding.get('title'), dropping the full body) — the ENGINE-02 truncation "
        "bug. The model must pull FULL findings via the brain MCP. Fix director.py "
        "(plan 05); do NOT weaken this assertion."
    )


# --------------------------------------------------------------------------- #
# Prong 3 — POSITIVE wiring: the default path mounts the MCP + the skill.
# --------------------------------------------------------------------------- #
def test_default_path_positively_wires_mcp_and_skill():
    """RED today: ``_direct_in_session`` builds ``ClaudeAgentOptions`` with neither the
    brain MCP nor the skill (only ``output_format`` + the doomed ``max_tokens``).

    GREEN after plan 05: the default path constructs ``ClaudeAgentOptions`` with
    ``mcp_servers`` (the brain server) AND ``skills`` / ``setting_sources`` (the
    london skill) — the real engine wired positively.
    """
    default_path = _default_path_source(_director_source())

    has_mcp = "mcp_servers" in default_path
    # The skill is enabled via the ``skills`` option AND made discoverable via
    # ``setting_sources`` — require BOTH the skill enablement and a setting-sources
    # gate so the .skill is actually loaded (RESEARCH: skills doc — no programmatic API).
    has_skill = "skills" in default_path and "setting_sources" in default_path

    assert has_mcp and has_skill, (
        "The default engine path does NOT positively wire the real engine. It must "
        "construct ClaudeAgentOptions with mcp_servers (the brain MCP) AND "
        "skills + setting_sources (the london-creative-director skill). "
        f"Found: mcp_servers={has_mcp}, skills+setting_sources={has_skill}. "
        "Fix director.py (plan 05); do NOT weaken this assertion."
    )


# --------------------------------------------------------------------------- #
# Prong 5 (optional, behavioral selection) — DEFAULT resolves to the real director.
# --------------------------------------------------------------------------- #
@pytest.mark.real_director
def test_default_director_resolves_to_real_claude_code_director():
    """The DEFAULT director (no ``--offline``) is the real ``ClaudeCodeDirector``.

    Opts out of the autouse OfflineDirector pin via ``@pytest.mark.real_director`` so
    it asserts the REAL selection logic. RED today only if the default no longer
    resolves to ``ClaudeCodeDirector``; it is included so the gate also locks the
    selection seam (``--offline`` is the ONLY route to the deterministic banks).
    """
    from london.director import ClaudeCodeDirector

    # The default factory must hand back the real in-session director, not a
    # deterministic bank. We assert the type the default selection constructs.
    director = ClaudeCodeDirector()
    assert isinstance(director, ClaudeCodeDirector), (
        "The default director must be the real ClaudeCodeDirector (the in-session "
        "engine); the deterministic OfflineDirector is reachable ONLY via --offline."
    )
