"""Phase 3 (Persona & Voice) — voice-rule + anti-slop seed unit tests (keyless).

This file is the Plan 03-01 test surface. Every test runs with NO API key — it
asserts on the STATIC persona constants and on the director seed string, never on a
live model call. Plan 03-02 extends this file (scrubber AI-tell pass, voice templates,
OfflineDirector degradation); Plan 03-01 covers:

  * the CD-register voice rules (D-02) — present, addressable, carrying the canonical
    good/bad example pair as DATA,
  * the anti-slop rules (D-03) — distilled from the humanize skill, addressable,
  * the two single-render ``*_block()`` helpers (one authoritative voice definition),
  * the director seed NOT re-authoring the voice — after the 04.6-05 real-engine wiring the
    persona reaches the model AS the ``.skill``, so the seed must carry no persona-block text
    (GUARD-01, ONE voice; rewritten from the old seed-consumes-blocks assertion),
  * the collapse of the one competing voice literal (``workflow.py:307``) to a persona
    reference (PERS-01 single-source invariant).
"""

from __future__ import annotations

from pathlib import Path

from london import persona
from london.director import DirectionRequest

_SRC_DIR = Path(__file__).parents[1] / "src" / "london"


# --- Task 1: CD-register voice rules + anti-slop rules (D-02 / D-03) ---


def test_cd_register_rules_present():
    """The canonical D-02 objective-over-vague pair is carried as DATA, not prose."""
    pairs = {
        (rule.example_good, rule.example_bad) for rule in persona.CD_VOICE_RULES
    }
    assert (
        "muted for a young audience",
        "needs more pop",
    ) in pairs, "the canonical objective-over-vague good/bad example pair must be data"


def test_voice_rules_are_addressable():
    """Five D-02 rules, each with a stable unique id, addressable by id."""
    ids = [rule.id for rule in persona.CD_VOICE_RULES]
    assert all(ids), "every voice rule needs a non-empty stable id"
    assert len(ids) == len(set(ids)), "voice-rule ids must be unique"
    expected = {
        "what_why_how",
        "strength_before_tension",
        "objective_over_vague",
        "direction_with_rationale",
        "register",
    }
    assert expected.issubset(set(ids)), (
        "the five D-02 concepts must each be present by stable id; "
        f"missing: {expected - set(ids)}"
    )


def test_anti_slop_rules_present():
    """Anti-slop rules are addressable (non-empty) and the rendered block names the
    distilled humanize concepts — not a single opaque paragraph."""
    assert persona.ANTI_SLOP_RULES, "ANTI_SLOP_RULES must be non-empty"
    # addressable, not an opaque blob: each rule has a stable id + instruction
    ids = [rule.id for rule in persona.ANTI_SLOP_RULES]
    assert all(ids), "every anti-slop rule needs a non-empty stable id"
    assert len(ids) == len(set(ids)), "anti-slop rule ids must be unique"
    block = persona.anti_slop_block().lower()
    # the distilled humanize concepts must surface in the seed text
    assert "ai tell" in block or "ai-tell" in block, "block must warn off AI tells"
    assert "cadence" in block or "sentence" in block, "block must vary cadence/length"
    assert "concrete" in block, "block must prefer concrete over abstract"
    assert "hedg" in block, "block must forbid hedging"


def test_voice_rules_block_renders_once():
    """voice_rules_block() is the ONE authoritative render — every rule instruction
    appears exactly once (anti-drift: no duplicated voice definition)."""
    block = persona.voice_rules_block()
    assert block.strip(), "voice_rules_block() must be non-empty"
    for rule in persona.CD_VOICE_RULES:
        assert block.count(rule.instruction) == 1, (
            f"rule {rule.id!r} instruction must render exactly once in the block"
        )


# --- Task 2: director seed consumes the blocks + single voice source (D-03 / D-01) ---


def _seed_request() -> DirectionRequest:
    """Mirror of tests/test_director.py:48-61 ``_request`` — keyless, no API key."""
    return DirectionRequest(
        brief={"title": "Quiet luxury fragrance", "text": "A solid scent for a young audience."},
        brain_findings={"research": [{"title": "Quiet material drama beats loud packaging"}]},
        product_tokens=["fragrance", "scent", "ritual"],
    )


def test_seed_does_not_reauthor_the_voice():
    """The in-session seed must NOT re-author London's voice (GUARD-01 / ONE voice).

    REWRITTEN for the real engine (plan 04.6-05). The old fake seam interpolated the
    voice-rule + anti-slop blocks into the model prompt — a SECOND self-authored London
    voice (the Workstream-F drift). The real engine loads the persona + 7-phase method AS
    the ``london-creative-director`` ``.skill`` (``skills`` + ``setting_sources`` in
    ``_direct_in_session``), so the seed must carry NONE of the persona-block instruction
    text. The persona constants below still exist as the SINGLE source — they now reach the
    model through the skill, not the seed (CLAUDE.md:143). GUARD-01
    (``test_anti_recurrence.py``) locks the source-level invariant; this is the behavioral
    twin over the built seed string.
    """
    from london.director import ClaudeCodeDirector

    seed = ClaudeCodeDirector().build_seed_prompt(_seed_request())
    # the seed must consume NEITHER persona block (the skill carries the voice now)
    for rule in persona.CD_VOICE_RULES:
        assert rule.instruction not in seed, (
            f"voice rule {rule.id!r} leaked into the model seed — the persona must reach the "
            "model AS the .skill, never as a self-authored seed (GUARD-01, ONE voice)"
        )
    for rule in persona.ANTI_SLOP_RULES:
        assert rule.instruction not in seed, (
            f"anti-slop rule {rule.id!r} leaked into the model seed — the persona must reach "
            "the model AS the .skill, never as a self-authored seed (GUARD-01, ONE voice)"
        )
    # but the seed DOES route the model to the real engine: it names the skill + brain tool.
    assert "london-creative-director" in seed
    assert "london_brain_query" in seed


def test_single_voice_source():
    """No competing voice literal remains in src/london/*.py, and workflow.py imports
    the persona single source (PERS-01 — ONE London voice)."""
    banned = "Public London: opinionated, precise, useful, allergic to generic-clean filler."
    for path in _SRC_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert banned not in text, (
            f"the competing voice literal must be collapsed; found in {path.name}"
        )
    workflow_src = (_SRC_DIR / "workflow.py").read_text(encoding="utf-8")
    assert "from london.persona import" in workflow_src or "from .persona import" in workflow_src, (
        "workflow.py must import the persona single source"
    )


# --- Plan 03-02 Task 1: the AI-tell scrub pass at the single chokepoint (D-04) ---
#
# The seed (Plan 03-01) is the PRIMARY mechanism for human copy; this lexical pass is
# the belt-and-suspenders backstop, added INSIDE the existing ``sanitize_public_text``
# chokepoint (no second scrub site — D-08). Single-word tells are ``\b``-anchored so
# innocent longer words survive (RESEARCH Pitfall 1, demonstrated live: a substring pass
# turns "delved" into "look atd").

_AI_TELLS_PRESENT = ("delve", "delving", "tapestry", "robust", "comprehensive", "leverage", "seamless")


def test_sanitize_removes_residual_ai_tells():
    """PERS-04 named deliverable: slop-laced public copy is scrubbed of residual
    AI-tells at the single existing chokepoint."""
    dirty = (
        "It's worth noting that we delve into this comprehensive tapestry to leverage "
        "a robust, seamless solution."
    )
    clean = persona.sanitize_public_text(dirty).lower()
    for tell in _AI_TELLS_PRESENT:
        assert tell not in clean, f"AI-tell {tell!r} survived the scrubber"


def test_ai_tell_replacements_are_grammatical():
    """WR-01/WR-02 regression: the replacement text must itself read clean — the scrubber
    must not introduce slop in the copy it exists to clean. 'delve into' -> 'look into'
    (not 'look at into'); deleted throat-clearing openers leave no leading/doubled comma."""
    assert persona.sanitize_public_text("We delve into the brief.") == "We look into the brief."
    # delete-to-empty opener followed by a comma -> no orphaned leading comma
    assert persona.sanitize_public_text("Needless to say, the route holds.") == "the route holds."
    # mid-sentence interjection -> no doubled comma artifact ',,'
    assert ",," not in persona.sanitize_public_text("The plan, needless to say, is solid.")


def test_scrub_does_not_mangle_innocent_longer_words():
    """Pitfall-1 word-boundary guard: ``\\b``-anchoring means 'developer'/'delivered'/
    'delved' survive intact (a substring pass would corrupt them)."""
    text = "The developer delivered the package."
    assert persona.sanitize_public_text(text) == text


def test_ai_tell_scrub_is_idempotent_and_empty_safe():
    """Empty-safe and idempotent — the delete-to-empty whitespace tidy must not drift on
    a second pass (Pitfall 2)."""
    assert persona.sanitize_public_text("") == ""
    once = persona.sanitize_public_text("we delve into a robust tapestry")
    assert persona.sanitize_public_text(once) == once


def test_scrub_stays_single_chokepoint():
    """D-08 invariant: there is exactly ONE scrub entry point. No new scrub function or
    call site is introduced — ``scrub_pack`` still routes public prose through
    ``sanitize_public_text`` only."""
    src = (_SRC_DIR / "persona.py").read_text(encoding="utf-8")
    assert src.count("def sanitize_public_text") == 1, (
        "there must be exactly one sanitize_public_text definition (single chokepoint)"
    )
    # No competing public scrub entry point: the only scrub surfaces are the existing
    # sanitize_public_text / scrub_pack pair (plus private _scrub_* helpers that route
    # through sanitize_public_text). Adding a second AI-tell-specific scrub function
    # would violate D-08.
    assert "def scrub_ai_tells" not in src, "no second AI-tell-specific scrub function"
    assert "def sanitize_ai_tells" not in src, "no second AI-tell sanitizer"
    # The AI-tell pass lives inside sanitize_public_text and reads _AI_TELL_REPLACEMENTS.
    assert "_AI_TELL_REPLACEMENTS" in src, "the AI-tell pass must use _AI_TELL_REPLACEMENTS"


# --- Plan 03-02 Task 2: fillable voice templates (PERS-05) ---
#
# The four templates are the stable contract Phases 4-6 fill — CONTRACTS the model fills,
# NOT pre-written copy (D-05).

_EXPECTED_TEMPLATE_IDS = {"section_intro", "tooltip", "exec_summary", "londons_read"}


def test_voice_templates_contract():
    """VOICE_TEMPLATES has exactly the four ids; each has a stable id, a non-empty slots
    tuple, and a non-empty instruction (the stable Phase 4-6 contract)."""
    assert set(persona.VOICE_TEMPLATES) == _EXPECTED_TEMPLATE_IDS, (
        "VOICE_TEMPLATES must key exactly the four stable template ids"
    )
    for key, template in persona.VOICE_TEMPLATES.items():
        assert template.id == key, "each template's id must match its dict key (stable handle)"
        assert isinstance(template.slots, tuple) and template.slots, (
            f"template {key!r} must carry a non-empty slots tuple"
        )
        assert all(slot for slot in template.slots), "every slot must be a non-empty named field"
        assert template.instruction.strip(), f"template {key!r} must carry a non-empty instruction"


def test_voice_templates_are_fillable_not_prewritten():
    """Each template is a DIRECTIVE (how London fills it) + named SLOTS, not pre-written
    finished copy (D-05 — the model fills the slots)."""
    for key, template in persona.VOICE_TEMPLATES.items():
        # The contract is slot names, not baked sentences of finished marketing copy.
        assert len(template.slots) >= 1, f"template {key!r} must expose at least one fillable slot"
        # Slots are short field identifiers (snake_case names), not prose sentences.
        for slot in template.slots:
            assert " " not in slot, f"slot {slot!r} should be a field name, not prose"
            assert len(slot) <= 40, f"slot {slot!r} should be a field name, not finished copy"
        # The instruction is a directive about HOW to fill — it must not itself be the
        # finished copy. A directive references the act of writing/filling, not a slogan.
        assert template.instruction.strip(), "instruction must be a non-empty directive"


# --- Plan 03-02 Task 2: OfflineDirector degradation = plain un-voiced banks (PERS-06) ---
#
# Keyless. The offline path returns PLAIN deterministic-bank prose — not a crash, not
# faked voice. The voice RULES (the seed) are NOT applied to the offline banks (D-06);
# the lexical scrubber is path-agnostic but that is separate from the rule scaffolding.


def _offline_request(brief_text: str) -> DirectionRequest:
    """Mirror of tests/test_director.py:48-61 ``_request`` — keyless, no API key."""
    title = brief_text.strip().splitlines()[0].lstrip("# ").strip()
    return DirectionRequest(
        brief={"title": title, "text": brief_text},
        brain_findings={"research": [{"title": "Quiet material drama beats loud packaging"}]},
        product_tokens=[t for t in brief_text.replace("#", " ").split() if len(t) >= 4][:6],
    )


def test_offline_director_emits_plain_unvoiced_copy():
    """PERS-06: OfflineDirector returns plain bank prose keyless — no crash, no faked
    voice, no seed-rule scaffolding (proving the voice RULES were not applied)."""
    from london.director import OfflineDirector

    from conftest import BRIEFS

    request = _offline_request(BRIEFS["fragrance"])
    result = OfflineDirector().direct(request)  # must NOT raise (keyless)

    assert result.voice and result.voice.strip(), "offline voice must be present, non-empty plain prose"
    lowered = result.voice.lower()
    # NO seed-rule scaffolding leaked in — the voice RULES were not applied to the banks.
    assert "observation → reason → consequence" not in lowered, (
        "offline output must not carry the voice-rule scaffolding (rules not applied — D-06)"
    )
    assert "slack-clarity" not in lowered, (
        "offline output must not carry the 'Slack-clarity' rule scaffolding (rules not applied — D-06)"
    )
    # And the seed rule-block headers must not appear either.
    assert "creative-director voice rules" not in lowered
    assert "anti-slop rules" not in lowered
