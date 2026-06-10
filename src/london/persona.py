"""Single source of truth for London Osei's persona prose and the seven-gate model.

This module collapses four previously-duplicated encodings of "London's persona +
seven gates" into one canonical copy (WALK-01):

  #1  ``models.py``      — ``GATE_IDS`` / ``GATE_NAMES``           (re-exported from here)
  #2  ``session.py``     — ``GATE_QUERY_TEMPLATES`` / ``INTAKE_QUESTIONS`` + the persona
                           approver literal                         (imported from here)
  #3  ``workbench.py``   — ``_gate_question`` / ``_gate_critique``  (sourced from here)
  #4  ``*.skill``        — persona prose + the "7 Phases"           (reconciled in Phase 6)

Everything here is a VERBATIM relocation of constants that already lived in
``models.py`` and ``session.py`` — no string value changed, so the existing pytest
suite proves zero behaviour change. New consumers (the ``director.py`` seam, the
sanitization chokepoint, the ``.skill`` reconciliation) hang off this module in later
sub-steps; A1 only establishes it as the source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping

# --- Persona prose (single source; the ``.skill`` is reconciled onto this in Phase 6) ---

# The approver name stamped on every gate approval in a local (no live provider) session.
# Relocated verbatim from session.py (the ``"approver"`` literal on each gate approval).
PERSONA_LABEL = "London Osei local session"

# London's persona voice in one line — the opinionated, product-first creative director.
# Phase 6 / Workstream F reconciles the full ``.skill`` prose onto this constant; for now
# it documents the voice the engine and skill must agree on.
PERSONA_PROSE = (
    "London Osei is an opinionated, product-first creative director. London names the "
    "tired category move, refuses the borrowed reference, and turns every brief into a "
    "specific point of view — taste before decoration, proof before polish."
)


# --- HOW London speaks: the single structured voice definition (D-01 / D-02) ---
#
# There is exactly ONE London voice. These structured rules ARE that definition;
# ``director.build_seed_prompt`` CONSUMES ``voice_rules_block()`` to seed the model —
# it never re-declares voice (re-declaring voice anywhere else is the banned
# Workstream-F drift failure mode, project CLAUDE.md). The model, seeded with these
# rules, writes London's copy; Python never writes the voice. The offline/fake banks
# are the plain un-voiced fallback (D-06) and are NEVER routed through these rules.
#
# The five rules are the research-grounded creative-director register (CONTEXT D-02):
# observation→reason→consequence, strength-before-tension, objective-over-vague (with
# the canonical "muted for a young audience" vs "needs more pop" pair carried as DATA),
# direction-with-rationale, and the Slack-clarity + Nike-conviction register.


@dataclass(frozen=True)
class VoiceRule:
    """One addressable CD-register rule.

    ``id`` is a stable handle for tests and the Phase 4-6 consumers; ``instruction`` is
    the seed text the model reads. The optional ``example_good`` / ``example_bad`` pair
    carries the canonical D-02 example as DATA, not prose.
    """

    id: str
    name: str
    instruction: str
    example_good: str = ""
    example_bad: str = ""


CD_VOICE_RULES: tuple[VoiceRule, ...] = (
    VoiceRule(
        id="what_why_how",
        name="Observation, then reason, then consequence",
        instruction=(
            "Every read names WHAT is on the page, WHY it matters, and WHAT it implies "
            "for the build. Never an observation without its consequence."
        ),
    ),
    VoiceRule(
        id="strength_before_tension",
        name="Open with the strength, then the tension",
        instruction=(
            "Start with what is already working before naming what has to change. The "
            "critique lands harder once the strength is on the table."
        ),
    ),
    VoiceRule(
        id="objective_over_vague",
        name="Objective, specific language over vague feeling",
        instruction=(
            "Name the concrete property, not a mood. Say what is true about the work, "
            "not how it makes you feel."
        ),
        example_good="muted for a young audience",
        example_bad="needs more pop",
    ),
    VoiceRule(
        id="direction_with_rationale",
        name="Direction with a rationale, never a bare diktat",
        instruction=(
            "Give the reason with the direction. London hands the team a decision they "
            "can defend, not an order they have to obey."
        ),
    ),
    VoiceRule(
        id="register",
        name="Clarity plus conviction, warm-but-clinical, no hype",
        instruction=(
            "Slack-clarity plus Nike-conviction: confident, plain, and specific, never "
            "breathless. Warm enough to trust, clinical enough to act on."
        ),
    ),
)


def voice_rules_block() -> str:
    """The ONE render of the CD-register rules into seed text (D-02).

    ``director.build_seed_prompt`` interpolates this; it is the single authoritative
    voice definition (anti-Workstream-F-drift). Each rule's ``instruction`` appears
    exactly once.
    """

    lines = ["London's creative-director voice rules — write every read this way:"]
    for rule in CD_VOICE_RULES:
        line = f"  - {rule.name}: {rule.instruction}"
        if rule.example_good:
            line += f' (good: "{rule.example_good}"; not: "{rule.example_bad}")'
        lines.append(line)
    return "\n".join(lines)


# --- Anti-slop rules baked into the SEED (D-03) ---
#
# Distilled from the global ``~/.claude/skills/humanize`` skill (phrases.md tiers,
# structures.md structural tells, tropes.md promotional drift, ledger-classes.md) —
# the DURABLE rules, not a copy of the skill file (the skill is a user-global file, not
# shippable). These are the PRIMARY anti-slop mechanism: the model, seeded with them,
# writes human copy before any scrub runs. The lexical scrubber (Plan 03-02) is only the
# belt-and-suspenders backstop. Structural rules (cadence, no Binary-Contrast) live here
# in the seed — a regex cannot safely rewrite structure (RESEARCH Pitfall 4).
#
# Em-dash nuance (RESEARCH State of the Art): at most one em dash per paragraph, NOT a
# zero-ban — a zero-em-dash rule is itself a 2026 AI tell.


@dataclass(frozen=True)
class AntiSlopRule:
    """One addressable anti-slop rule distilled from the humanize taxonomy."""

    id: str
    name: str
    instruction: str


ANTI_SLOP_RULES: tuple[AntiSlopRule, ...] = (
    AntiSlopRule(
        id="no_ai_tells",
        name="No AI-tell vocabulary",
        instruction=(
            "Avoid the AI-tell words: delve, tapestry, robust, comprehensive, leverage, "
            "seamless, testament, pivotal, intricate, realm. Use the plain word instead."
        ),
    ),
    AntiSlopRule(
        id="no_throat_clearing",
        name="No throat-clearing or hedging",
        instruction=(
            "Cut openers like \"It's worth noting that\" and \"Let's dive in\". No "
            "hedging (\"arguably\", \"in many ways\"). Start with the actual point and "
            "commit to it."
        ),
    ),
    AntiSlopRule(
        id="vary_cadence",
        name="Vary cadence and sentence length",
        instruction=(
            "Mix short and long sentences. No metronomic rhythm, no Rule-of-Three "
            "tricolon abuse, no dramatic one-line fragments for effect."
        ),
    ),
    AntiSlopRule(
        id="no_binary_contrast",
        name="No Not-X-it's-Y binary contrast",
        instruction=(
            "Drop the \"Not X, it's Y\" / negative-parallelism construction — it is the "
            "number-one structural AI tell. State the thing directly."
        ),
    ),
    AntiSlopRule(
        id="concrete_over_abstract",
        name="Concrete over abstract",
        instruction=(
            "Prefer concrete nouns and specific detail over abstract summary. Show the "
            "decision; do not narrate that a decision is being made."
        ),
    ),
    AntiSlopRule(
        id="no_hype",
        name="No hype, puffery, or press-release register",
        instruction=(
            "No significance inflation (\"stands as a testament to\"), no manufactured "
            "warmth, no press-release sentences. Plain conviction, not promotion."
        ),
    ),
    AntiSlopRule(
        id="em_dash_restraint",
        name="Em-dash restraint, not a ban",
        instruction=(
            "At most one em dash per paragraph, and not in every paragraph. Do not strip "
            "em dashes entirely — a zero-em-dash text is itself an AI tell."
        ),
    ),
)


def anti_slop_block() -> str:
    """The ONE render of the anti-slop rules into seed text (D-03).

    Interpolated by ``director.build_seed_prompt`` alongside ``voice_rules_block()``.
    Each rule's ``instruction`` appears exactly once.
    """

    lines = ["Write like a person, not a model. Anti-slop rules for every line:"]
    for rule in ANTI_SLOP_RULES:
        lines.append(f"  - {rule.name}: {rule.instruction}")
    return "\n".join(lines)


# --- Fillable voice templates (D-05) — the contract Phases 4-6 fill ---
#
# These are CONTRACTS the MODEL fills, NOT pre-written copy. Each template carries a
# stable ``id`` (Phases 4-6 reference templates by id), a ``slots`` tuple naming the
# fields the model/caller supplies, and an ``instruction`` telling London HOW to fill it
# in the CD register (the same voice the seed rules define — D-02). The model writes the
# voice into the slots; Python never writes the copy (project CLAUDE.md). Phase 3 ships
# the dataclass/dict contract only — no JSON Schema this phase (03-RESEARCH Open
# Question 2; Phase 5 adds one if it needs schema-validated fills). Offline/fake paths do
# NOT fill these templates — they emit the plain deterministic banks (D-06).


@dataclass(frozen=True)
class VoiceTemplate:
    """One fillable voice template (D-05).

    ``id`` is the stable handle Phases 4-6 reference; ``slots`` names the fields the
    model/caller supplies (the testable contract); ``instruction`` directs London on HOW
    to fill it in the CD register. It carries the directive, not finished marketing copy.
    """

    id: str
    slots: tuple[str, ...]
    instruction: str


VOICE_TEMPLATES: dict[str, VoiceTemplate] = {
    "section_intro": VoiceTemplate(
        id="section_intro",
        slots=("kicker", "framing"),
        instruction=(
            "One-line framing of a section. Open with the strength, then name what the "
            "section proves. Plain and specific, no hype."
        ),
    ),
    "tooltip": VoiceTemplate(
        id="tooltip",
        slots=("what", "how_to_use"),
        instruction=(
            "Explain what this section is and how to read it. Plain, useful, no hype — a "
            "reader should know what to look at and why after one line."
        ),
    ),
    "exec_summary": VoiceTemplate(
        id="exec_summary",
        slots=("read", "recommended_route", "why"),
        instruction=(
            "London's read of the brief: which route she would ship and why. Lead with "
            "the read, name the route, give the rationale — direction with a reason, "
            "never a bare verdict."
        ),
    ),
    "londons_read": VoiceTemplate(
        id="londons_read",
        slots=("section", "one_line"),
        instruction=(
            "Per-section lead-in: why this section matters and how to read it. One line, "
            "in London's voice — observation, then what it implies for the build."
        ),
    ),
}


# --- The seven gates (duplication site #1 — moved verbatim out of models.py) ---

GATE_IDS: tuple[str, ...] = (
    "research",
    "creative_direction",
    "typography_color",
    "image_direction",
    "layout_mockups",
    "build_motion",
    "quality_review",
)

GATE_NAMES: dict[str, str] = {
    "research": "Research",
    "creative_direction": "Creative Direction",
    "typography_color": "Typography/Color",
    "image_direction": "Image Direction",
    "layout_mockups": "Layout/Mockups",
    "build_motion": "Build/Motion",
    "quality_review": "Quality Review",
}


# --- Per-gate brain-query templates + intake questions (duplication site #2 — ---
# --- moved verbatim out of session.py:463-505) ---

GATE_QUERY_TEMPLATES: dict[str, tuple[tuple[str, str], ...]] = {
    "research": (
        ("category void", "{product_noun} aesthetic void category assumptions {aesthetic}"),
        ("admired references", "brands London admires {product_noun} packaging typography product design"),
    ),
    "creative_direction": (
        ("reframe", "how to position {product_noun} anti positioning reframe vessel unboxing"),
        ("voice", "opinionated product first creative direction taste differentiator {aesthetic}"),
    ),
    "typography_color": (
        ("type proof", "typography for {aesthetic} Fonts In Use Fontshare brand system"),
        ("color proof", "color system palette bold intentional brand guidelines {product_noun}"),
    ),
    "image_direction": (
        ("image rules", "art directed photography product imagery packaging avoid generic stock {product_noun}"),
        ("visual examples", "visual examples on screen {aesthetic} material product photography"),
    ),
    "layout_mockups": (
        ("layout grammar", "web composition landing page product page route mockup {product_noun}"),
        ("components", "component inspiration interface packaging grid prototype {aesthetic}"),
    ),
    "build_motion": (
        ("build handoff", "build handoff tokens motion prototype route receipts {product_noun}"),
        ("motion", "motion principles scroll hover product ritual interface {aesthetic}"),
    ),
    "quality_review": (
        ("quality", "what makes design premium versus cheap generic mid stock typography"),
        ("anti patterns", "anti patterns DaFont Canva Pinterest generic template grid modern clean"),
    ),
}

INTAKE_QUESTIONS: dict[str, tuple[str, ...]] = {
    "research": ("Who has to care first?", "What looks tired in this category?", "What proof would make the work credible?"),
    "creative_direction": ("What assumption are we refusing?", "What should the object/interface actually feel like?", "What is this not?"),
    "typography_color": ("What tone must type carry before imagery?", "Which colors are product states, not decoration?"),
    "image_direction": ("What must the imagery prove?", "What stock-photo trap would kill this?"),
    "layout_mockups": ("Which route should get the first prototype?", "What screens or sections prove the idea?"),
    "build_motion": ("What stack can show the decision without pretending live providers ran?", "Which motion earns its place?"),
    "quality_review": ("What would make London call this mid?", "What evidence proves the pack is specific?"),
}


# --- Workbench conversation prose (duplication site #3 — moved verbatim out of ---
# --- workbench.py:959-981 ``_gate_question`` / ``_gate_critique``) ---
#
# Kept as a distinct constant from INTAKE_QUESTIONS above: the workbench conversation
# view renders these SECOND, divergent gate questions today, so merging them into
# INTAKE_QUESTIONS would change rendered output. Preserve both named sources verbatim;
# reconciling the two sets is out of scope for this pure refactor.

WORKBENCH_GATE_QUESTIONS: dict[str, str] = {
    "research": "What category assumption is London refusing?",
    "creative_direction": "What sharper point of view should the work take?",
    "typography_color": "What must type and color prove before imagery arrives?",
    "image_direction": "What should the image system show instead of generic stock?",
    "layout_mockups": "Which route should get built first?",
    "build_motion": "What build proof and motion behavior earns its place?",
    "quality_review": "What would make London reject this as generic?",
}

WORKBENCH_GATE_QUESTION_FALLBACK = "What did London decide?"

WORKBENCH_GATE_CRITIQUES: dict[str, str] = {
    "research": "Do not start with references until the tired category move is named: {anti}.",
    "creative_direction": "The reframe has to change what gets built, not just rename the mood.",
    "typography_color": "A type system is only useful if it can survive real product copy and labels.",
    "image_direction": "Imagery must prove material, ritual, and interface behavior before it tries to be pretty.",
    "layout_mockups": "A route is not approved until it produces a different first screen and section rhythm.",
    "build_motion": "Motion should clarify the ritual; otherwise keep the prototype still and legible.",
    "quality_review": "Reject anything that collapses into {anti}.",
}

WORKBENCH_GATE_CRITIQUE_FALLBACK = "Keep checking the route against {anti}."


# --- The single QA-vocab sanitization chokepoint (HON-01 / D-08) ---
#
# London's internal QA/testing register ("fresh lane", "borrowed route", "prior
# profile", "recycled profile", "reusable template", "fixture") must NEVER reach a
# public-copy field, AND must never seed the model prompt (so the model is never
# taught the QA vocabulary in the first place — D-08 / Pitfall 3+5). This is the ONE
# place that scrub happens: every public-prose string and every prompt-seed string
# passes through ``sanitize_public_text`` before it is shown or before it seeds the
# model. The banned list lives here, alongside the persona/gate single-source, exactly
# as D-08 requires ("next to ``BANNED_TEMPLATE_NAMES``", which A6 adds beside this).
#
# Receipts / debug / mode markers are NOT scrubbed — the offline-template-preview
# origin marker legitimately carries "template"/"preview" in receipts, and stamping
# the director mode there is the whole point of mode-only-in-receipts (ENG-06).

# The 6 banned QA phrases (D-08). Each maps to a neutral public-register replacement so
# the OfflineDirector path (which keeps the deterministic banks and thus the vocabulary)
# is scrubbed belt-and-suspenders, and any model output that imitates leaked vocabulary
# is caught too. Order matters: longer/compound phrases are replaced before their
# substrings (e.g. "fresh lane proof" handled before bare "fresh lane").
BANNED_QA_VOCAB: tuple[str, ...] = (
    "fresh lane",
    "borrowed route",
    "prior profile",
    "recycled profile",
    "reusable template",
    "fixture",
)

# Public-register replacements (case-insensitive match → register-neutral phrase). These
# are the only words that ever surface to the user in place of the QA register.
_QA_VOCAB_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    # Plurals / compounds first so the bare-phrase rules below do not split them.
    ("recycled profiles", "other projects"),
    ("recycled profile", "another project"),
    ("prior profile route", "another project's route"),
    ("prior profiles", "earlier projects"),
    ("prior profile", "an earlier project"),
    ("reusable templates", "generic project shells"),
    ("reusable template", "a generic project shell"),
    ("borrowed routes", "routes from other projects"),
    ("borrowed route", "a route from another project"),
    ("fresh lane proof", "this brief's own proof"),
    ("fresh lanes", "this brief's own direction"),
    ("fresh lane", "this brief's own direction"),
    ("fixtures", "deterministic samples"),
    ("fixture", "deterministic sample"),
)


# --- The residual-AI-tell pass (D-04) — PASS 2 of the SAME single chokepoint ---
#
# The SEED (Plan 03-01's voice + anti-slop rules) is the PRIMARY mechanism: the model,
# seeded with those rules, writes human copy before any scrub runs. This lexical table
# is the belt-and-suspenders BACKSTOP that catches residue, added INSIDE
# ``sanitize_public_text`` so BOTH inheriting call sites — the prompt-seed scrub in
# ``director.build_seed_prompt`` and ``scrub_pack`` — get it for free (no second scrub
# site — D-08).
#
# DISTILLED (not copied) from the global ``~/.claude/skills/humanize`` taxonomy
# (phrases.md Tier-1 Red-Flag Words + Throat-Clearing/Hedging openers; tropes.md
# Significance Inflation) — the durable entries only. Replacements are register-neutral
# (Pitfall 5): "robust"→"solid" reads fine in real copy, so a brief's own vocabulary and
# the FakeDirector echo tokens survive. The list is CONSERVATIVE — high-confidence Tier-1
# tells only, no Tier-2 context-dependent words.
#
# TWO LOAD-BEARING DIVERGENCES from ``_QA_VOCAB_REPLACEMENTS`` (RESEARCH Pitfalls 1+2):
#   1. Single-word tells are ``\b``-anchored in the pass below (``" " not in phrase``),
#      because a plain substring ``re.sub`` corrupts longer words ("delved"→"look atd").
#      Multi-word phrases stay unanchored, matching the QA idiom.
#   2. Throat-clearing openers delete-to-empty, so a final whitespace tidy collapses the
#      doubled spaces / stray space-before-punctuation they leave (kept idempotent).
#
# This pass is LEXICAL only (word/phrase swaps) — it can delete or replace but never ADDS
# a factual claim, and it never rewrites structure (cadence / Binary-Contrast live in the
# SEED, where the model handles them — RESEARCH Pitfall 4). Order: longest/compound first.
_AI_TELL_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    # Multi-word throat-clearing / hedging / meta-commentary openers — delete to empty
    # (substring-safe, matching the QA idiom; the whitespace tidy cleans up after them).
    ("it's worth noting that", ""),
    ("it is worth noting that", ""),
    ("it's important to note that", ""),
    ("it is important to note that", ""),
    ("it should be noted that", ""),
    ("it bears mentioning that", ""),
    ("needless to say", ""),
    ("without further ado", ""),
    # Multi-word significance-inflation phrases — register-neutral rewrites (tropes.md).
    ("stands as a testament to", "shows"),
    ("plays a vital role in", "matters for"),
    ("plays a pivotal role in", "matters for"),
    # Single-word Tier-1 red-flag tells (``\b``-anchored in the pass below). Plurals /
    # inflections come first so the bare-word rule does not split them.
    ("comprehensive", "complete"),
    ("multifaceted", "many-sided"),
    ("delving", "looking"),
    ("delve", "look"),
    ("tapestry", "mix"),
    ("robust", "solid"),
    ("leverage", "use"),
    ("seamless", "smooth"),
    ("testament", "sign"),
    ("pivotal", "key"),
    ("intricate", "detailed"),
    ("holistic", "whole"),
    ("noteworthy", "notable"),
)


def sanitize_public_text(text: str, *, scrub_ai_tells: bool = True) -> str:
    """Scrub QA-vocab (PASS 1) and residual AI-tells (PASS 2) from one public-copy /
    prompt-seed string at the SINGLE chokepoint (D-08).

    This is THE sanitization chokepoint. It is called (1) on every prompt-seed string
    BEFORE the model is invoked (so the model never learns the QA register) and (2) on
    every public-prose field via :func:`scrub_pack`. Receipts/debug strings are NOT
    passed through it — the offline origin marker and the director-mode receipt
    legitimately use "template"/"preview"/mode words.

    Two passes, same function, both inherited by both call sites:

    * **PASS 1 — QA-vocab** (UNCHANGED, ALWAYS runs, FIRST). Compound phrases,
      substring-safe; byte-identical to the pre-Plan-03-02 behaviour so the honesty
      guards (no-QA-vocab / mode-blind) cannot regress (RESEARCH Pitfall 3).
    * **PASS 2 — AI-tells** (Plan 03-02, D-04). Single-word tells are ``\b``-anchored so
      innocent longer words survive (Pitfall 1); multi-word phrases stay unanchored.
      A final whitespace tidy collapses the gaps left by delete-to-empty openers
      (Pitfall 2), kept idempotent.

    ``scrub_ai_tells`` gates PASS 2 ONLY (PASS 1 always runs, so the QA-vocab discipline
    is never weakened). It defaults to ``True`` — every public-output path and brief /
    finding text gets the full two-pass scrub. The ONE caller that passes ``False`` is
    ``director.build_seed_prompt`` for London's OWN static anti-slop instruction blocks,
    which deliberately NAME the tell-words as examples to avoid ("avoid: delve, robust,
    …", 'cut "It''s worth noting that"'). Running PASS 2 over those instructions would
    corrupt London's directions to the model (e.g. turn the example
    "stands as a testament to" into "shows") — the model must read them verbatim. This is
    a parameter on the ONE chokepoint, not a second scrub function or call site (D-08).
    """

    if not text:
        return text
    result = text
    # PASS 1 — QA-vocab (UNCHANGED; compound phrases, substring-safe; ALWAYS runs FIRST).
    for phrase, replacement in _QA_VOCAB_REPLACEMENTS:
        result = re.sub(re.escape(phrase), replacement, result, flags=re.IGNORECASE)
    if not scrub_ai_tells:
        return result
    # PASS 2 — residual AI-tells (NEW; single words \b-anchored, see Pitfall 1).
    for phrase, replacement in _AI_TELL_REPLACEMENTS:
        pattern = rf"\b{re.escape(phrase)}\b" if " " not in phrase else re.escape(phrase)
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    # Tidy the gaps left by delete-to-empty openers (Pitfall 2). Idempotent: a second run
    # over already-tidied text is a no-op (no double spaces / stray space-before-punct /
    # leading-comma / doubled-comma artifacts remain to collapse).
    result = re.sub(r"\s+([,.;:!?])", r"\1", result)  # space before punctuation
    result = re.sub(r"([,;:])\s*([,.;:!?])", r"\2", result)  # doubled punct -> keep last
    result = re.sub(r"[ \t]{2,}", " ", result)  # runs of spaces/tabs -> single space
    # A deleted opener that was followed by a comma leaves a leading ", ..." — strip the
    # orphaned leading comma/semicolon (and its space) at the very start of the string.
    result = re.sub(r"^[\s,;:]+", "", result)
    return result


# Pack keys that carry PUBLIC creative prose and MUST be scrubbed. Receipts/debug
# (``receipts``, ``provider_selection``, ``setup_context``, mode markers) are excluded
# by omission — they legitimately carry mode/template/preview words.
_SCRUB_TOP_LEVEL_STRING_KEYS: tuple[str, ...] = (
    "title",
    "summary",
    "category_assumption",
    "aesthetic_void",
    "london_reframe",
    "vessel_interface_expression",
    "recurring_loop",
    "unboxing_first_moment",
    "anti_position",
)

# Per-route / per-section / per-block prose keys to scrub (string-valued or list-of-str).
_SCRUB_ROUTE_STRING_KEYS: tuple[str, ...] = (
    "title",
    "headline",
    "subhead",
    "lore",
    "mood",
    "type",
    "type_note",
    "rationale",
)
_SCRUB_ROUTE_LIST_KEYS: tuple[str, ...] = ("tags", "steal", "do_not_copy")


def _scrub_str(value: Any) -> Any:
    return sanitize_public_text(value) if isinstance(value, str) else value


def _scrub_str_list(value: Any) -> Any:
    if isinstance(value, list):
        return [sanitize_public_text(v) if isinstance(v, str) else v for v in value]
    return value


def _scrub_mapping_prose(node: MutableMapping[str, Any], string_keys: tuple[str, ...], list_keys: tuple[str, ...] = ()) -> None:
    for key in string_keys:
        if key in node:
            node[key] = _scrub_str(node[key])
    for key in list_keys:
        if key in node:
            node[key] = _scrub_str_list(node[key])


# Copy-block kinds that contain machine-generated code or config — exempt from the
# whitespace/punctuation tidy passes.  QA-vocab PASS 1 still applies (in case a
# prompt-seed fixture somehow carries a "fixture" or "borrowed route" token), but the
# tidy passes must never reflow code indentation or eat the leading `:` of `:root {`.
_MACHINE_COPY_KINDS: frozenset[str] = frozenset({"css_variables", "import_hint"})


def _scrub_copy_block(entry: MutableMapping[str, Any]) -> None:
    """Scrub a copy_block entry, exempting machine-kind text from tidy passes."""
    kind = entry.get("kind", "")
    if isinstance(kind, str) and kind in _MACHINE_COPY_KINDS:
        # PASS 1 (QA-vocab) only — no AI-tell rewrites, no tidy (preserves code layout).
        if "label" in entry and isinstance(entry["label"], str):
            entry["label"] = sanitize_public_text(entry["label"])
        if "text" in entry and isinstance(entry["text"], str):
            entry["text"] = sanitize_public_text(entry["text"], scrub_ai_tells=False)
    else:
        _scrub_mapping_prose(entry, ("label", "text"))


def scrub_pack(pack: MutableMapping[str, Any]) -> None:
    """Belt-and-suspenders pass scrubbing QA-vocab from PUBLIC pack prose in place.

    Runs over the lane/route/section/conversation/copy/next-step prose fields the
    renderer surfaces — NOT over ``receipts``/``provider_selection``/``setup_context``
    or any debug/mode marker (those legitimately carry mode/template/preview words). This
    is the second of the two D-08 call sites; the first is the per-string scrub on the
    prompt-seed inside ``director.py`` before the model is invoked.
    """

    if not isinstance(pack, Mapping):
        return

    _scrub_mapping_prose(pack, _SCRUB_TOP_LEVEL_STRING_KEYS)

    session_lane = pack.get("session_lane")
    if isinstance(session_lane, MutableMapping):
        _scrub_mapping_prose(
            session_lane,
            ("label", "category_assumption", "aesthetic_void", "london_reframe", "anti_position", "voice", "aesthetic"),
        )

    routes = pack.get("routes")
    if isinstance(routes, list):
        for route in routes:
            if not isinstance(route, MutableMapping):
                continue
            _scrub_mapping_prose(route, _SCRUB_ROUTE_STRING_KEYS, _SCRUB_ROUTE_LIST_KEYS)
            sections = route.get("sections")
            if isinstance(sections, list):
                for section in sections:
                    if isinstance(section, MutableMapping):
                        _scrub_mapping_prose(section, ("title", "body"))

    for entry in _iter_mappings(pack.get("conversation")):
        _scrub_mapping_prose(entry, ("gate", "decision", "rationale", "critique", "answer"))

    for entry in _iter_mappings(pack.get("route_comparison")):
        _scrub_mapping_prose(
            entry,
            ("title", "thesis", "best_for", "visual_world", "type", "palette_logic", "steal", "do_not_copy", "first_build_move", "risk"),
        )

    for entry in _iter_mappings(pack.get("copy_blocks")):
        _scrub_copy_block(entry)

    for entry in _iter_mappings(pack.get("next_steps")):
        _scrub_mapping_prose(entry, ("label", "description"))

    for group in _iter_mappings(pack.get("font_options")):
        _scrub_mapping_prose(group, ("route_title",))
        for option in _iter_mappings(group.get("options")):
            _scrub_mapping_prose(
                option,
                ("name", "best_use", "why_london_chose_it", "why_this_route_not_other_route", "what_makes_it_wrong", "import_hint"),
            )

    # D-11 / GRADE-02: the grader block joins THIS single chokepoint — one more block-walk,
    # never a second scrubber. The grader's receipts carry ONLY public-safe query strings (+
    # source-… IDs and counts, which are already public-safe and NOT scrubbed); raw brain
    # finding BODIES are never carried, so the only thing to sanitize is the adaptive query
    # STRINGS that London chose. They appear in THREE places in the grader block — the scrubbed
    # `telemetry` receipts view, the collapsible two-layer `detail` layer, and the humanized
    # `headline` summary — so the single chokepoint walks all three (Plan 03 grader shape).
    grader = pack.get("grader")
    if isinstance(grader, MutableMapping):
        for view_key in ("telemetry", "detail"):
            view = grader.get(view_key)
            if isinstance(view, MutableMapping):
                for trace in _iter_mappings(view.get("brain_queries")):
                    _scrub_mapping_prose(trace, ("query",))
        headline = grader.get("headline")
        if isinstance(headline, MutableMapping):
            _scrub_mapping_prose(headline, ("summary",))
            for verdict in _iter_mappings(headline.get("inspectors")):
                _scrub_mapping_prose(verdict, ("line",))


def _iter_mappings(value: Any):
    if isinstance(value, list):
        for item in value:
            if isinstance(item, MutableMapping):
                yield item


__all__ = [
    "PERSONA_LABEL",
    "PERSONA_PROSE",
    "VoiceRule",
    "CD_VOICE_RULES",
    "voice_rules_block",
    "AntiSlopRule",
    "ANTI_SLOP_RULES",
    "anti_slop_block",
    "VoiceTemplate",
    "VOICE_TEMPLATES",
    "GATE_IDS",
    "GATE_NAMES",
    "GATE_QUERY_TEMPLATES",
    "INTAKE_QUESTIONS",
    "WORKBENCH_GATE_QUESTIONS",
    "WORKBENCH_GATE_QUESTION_FALLBACK",
    "WORKBENCH_GATE_CRITIQUES",
    "WORKBENCH_GATE_CRITIQUE_FALLBACK",
    "BANNED_QA_VOCAB",
    "sanitize_public_text",
    "scrub_pack",
]
