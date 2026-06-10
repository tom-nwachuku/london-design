"""Shared pytest fixtures and constants for the London test suite.

Today this centralizes the ``BRIEFS`` dict that was duplicated verbatim across
``test_session.py`` and ``test_workbench.py`` (defined once, here). Both test files
import it from this module.

A6 (plan 01-06) adds the anti-relapse exit controls here:

* ``BANNED_TEMPLATE_NAMES`` — the 20 verified memorized route titles (10 ``PROFILES``
  route seeds + 10 ``_fresh_route_titles`` keyword-pair returns). Every route title
  in the property/contract suite is asserted ``not in`` this set, replacing the deleted
  exact-string asserts so the memorized-template disease is structurally impossible to
  reintroduce. ``Joy Object System`` / ``Utility With A Wink`` are fixture-only and
  intentionally NOT banned.
* Three NEGATIVE-CONTROL pack fixtures (``generic_pack`` / ``memorized_name_pack`` /
  ``qa_vocab_pack``) — each is a known-BAD pack that a property in ``test_properties.py``
  / ``test_honesty.py`` provably REJECTS. A property with no negative control that can
  fail it is too loose (Pitfall 8); these are the controls that prove each property has
  teeth.

A5 (plan 01-05) adds the ``default_director_is_offline`` autouse fixture: after the A5
flip the DEFAULT ``write_london_pack`` path is model-driven (``ClaudeCodeDirector``),
which hard-errors with no model in CI (D-01). The existing deterministic suite is the
OfflineDirector PARITY ORACLE, so the fixture pins the default test director to
``OfflineDirector`` (keyless, deterministic) — exactly the parity-oracle role. Tests
that explicitly exercise director SELECTION opt out with ``@pytest.mark.real_director``;
A6 then layers the FakeDirector property/contract tests on top.
"""

from __future__ import annotations

import copy
import json
import re as _re
from pathlib import Path

import pytest

# --- Phase 5 (Body-Fit) capture-backed range fixtures --------------------------------
#
# The 5 validated real captures (`.scratch/spike/captures/*.json`) are EVIDENCE OF
# LONDON'S RANGE, not templates. Their `direction_result` blocks carry variable-N
# conversations (observed N = 3,5,6,7) and a BIMODAL recommended_route (11..704 chars).
# These fixtures load them so the contract-widening tests derive expectations FROM each
# capture's own shape (e.g. `len(conversation) == that capture's gate count`) rather
# than hard-coding 5/6/7. DO NOT OVERFIT: never assert specific brief prose; only assert
# the structural degrees of freedom (count, length, no-padding).

_CAPTURE_NAMES = ("website", "product", "brand", "app", "generic")
_CAPTURES_DIR = Path(__file__).parents[1] / ".scratch" / "spike" / "captures"


def _load_capture_direction(name: str) -> dict:
    """Load one capture's `direction_result` block (range evidence, not a template)."""

    if not _CAPTURES_DIR.exists():
        pytest.skip("capture range-evidence (.scratch/spike/captures) is not shipped in public distributions")
    data = json.loads((_CAPTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))
    direction = data.get("direction_result")
    if not isinstance(direction, dict):
        raise AssertionError(f"capture {name}.json has no direction_result block")
    return direction


@pytest.fixture
def capture_directions() -> dict[str, dict]:
    """All 5 captures' `direction_result` blocks keyed by name (range evidence)."""

    return {name: _load_capture_direction(name) for name in _CAPTURE_NAMES}


def _synthetic_conversation(n: int) -> list[dict]:
    """An N-decision conversation past the observed high of 7 — anti-overfit range-end.

    Each entry is London's OWN gate label (NOT one of the internal 7 method-phases), to
    prove the display derives from `direction["conversation"]`, never from a fixed gate
    scaffold. Only gate+decision are guaranteed (D-02 optionalizes the rest).
    """

    return [
        {
            "gate": f"Decision {i + 1}",
            "decision": f"London's decision number {i + 1}.",
            "rationale": f"Rationale {i + 1}.",
            "critique": f"Critique {i + 1}.",
            "answer": f"Answer {i + 1}.",
        }
        for i in range(n)
    ]


@pytest.fixture
def synthetic_n8_direction(capture_directions) -> dict:
    """A real capture cloned with an 8-decision conversation (past the observed high of 7).

    Built from a real capture so every OTHER required field is present; only the
    conversation is swapped for the N=8 synthetic. Anti-overfit: the harness tests PAST
    the high end of the observed 3..7 range.
    """

    direction = copy.deepcopy(capture_directions["product"])
    direction["conversation"] = _synthetic_conversation(8)
    return direction


# Bimodal recommendation range-ends (D-04): the observed window is 11..704 chars; the
# synthetic 1000-char string tests PAST the high end and the 11-char string IS the
# observed low end. Both must render verbatim (no truncation, no summarizer — D-11).
SYNTHETIC_RECOMMENDATION_LONG = "London argues this route at length. " * 28  # > 1000 chars
SYNTHETIC_RECOMMENDATION_BARE = "The Almanac"  # 11 chars — the observed bare low end

assert len(SYNTHETIC_RECOMMENDATION_LONG) > 1000, "long recommendation must exceed 1000 chars"
assert len(SYNTHETIC_RECOMMENDATION_BARE) == 11, "bare recommendation must be the 11-char low end"


# Centralized brief fixtures — the single definition of the dict previously duplicated
# at test_session.py:9-22 and test_workbench.py:9-22. Kept verbatim so the existing
# property/contract assertions over these briefs are unchanged.
BRIEFS: dict[str, str] = {
    "hr": """# HR Compliance SaaS

Build an enterprise HR compliance product for policy changes, audit trails, employee evidence, and risk review.
""",
    "kids": """# Kids Lunchbox

Create a school lunchbox system for kids, parents, snack choices, stickers, backpack routines, and daily lunch reveal moments.
""",
    "fragrance": """# Luxury Fragrance Compact

Create a luxury solid fragrance compact with refillable scent, atelier packaging, bottle-like ritual, note cards, and quiet material drama.
""",
}


# The 20 verified memorized route titles the old deterministic engine emitted. These are
# the names the DELETED exact-string asserts used to pin (so the memorized-template
# behaviour stayed alive); every property/contract test now asserts route titles are
# ``not in`` this set instead. The union is 20 distinct strings (RESEARCH undercounted as
# "15"): the 10 ``PROFILES`` route seeds (session.py / now OfflineDirector banks) + the
# 10 ``_fresh_route_titles`` keyword-pair returns. ``Joy Object System`` /
# ``Utility With A Wink`` are fixture-only (gated behind ``--fixture``) and are NOT banned.
BANNED_TEMPLATE_NAMES: frozenset[str] = frozenset(
    {
        # 10 PROFILES route seeds
        "Audit Trail Atlas",
        "Calm Exception Desk",
        "Sticker Ritual Kit",
        "Lunchbox Field Guide",
        "Quiet Atelier",
        "Night Bottle Ritual",
        "Morning Sign-In",
        "Compatibility Card Studio",
        "Signal Object Manual",
        "Collector Utility",
        # 10 _fresh_route_titles keyword-pair returns
        "Safe Walk Window",
        "Care Forecast Cards",
        "Daily Chart Briefing",
        "Friend Reading Cards",
        "Refill Scent Ritual",
        "Scent Note Cabinet",
        "Kid Choice Kit",
        "Lunch Reveal Guide",
        "Proof Trail Desk",
        "Policy Signal Room",
    }
)

# Sanity: the verified union is exactly 20 distinct names (anti-relapse: if a name is ever
# dropped or duplicated this trips at collection time, not silently).
assert len(BANNED_TEMPLATE_NAMES) == 20, "BANNED_TEMPLATE_NAMES must be the 20 verified names"

# The generic "modern clean" filler set the no-generic-filler property rejects. A model
# that regressed to stock-deck vocabulary (Pitfall 4) would collapse onto these phrases.
GENERIC_FILLER_PHRASES: tuple[str, ...] = (
    "modern clean",
    "sleek minimal",
    "bold vibrant",
    "clean modern",
    "minimal sleek",
)


# --- Negative-control packs (TST-03) ------------------------------------------------
#
# Each fixture is a KNOWN-BAD pack the matching property provably REJECTS, proving the
# property has teeth (Pitfall 8). They are deliberately tiny — only the fields the
# property under test reads. The shape mirrors the public london-pack route/conversation
# vocabulary so the same assertion logic that passes on a FakeDirector pack fails here.


@pytest.fixture
def generic_pack() -> dict:
    """All routes titled "Modern Clean Route" with filler-only prose.

    Rejected by: title-contains-brief-vocab (property 2), routes-distinct (property 3),
    and no-generic-filler (property 6) — the title carries none of the brief's tokens,
    both routes are identical, and the prose is pure "modern clean" filler.
    """

    route = {
        "title": "Modern Clean Route",
        "rationale": "A modern clean, sleek minimal, bold vibrant direction for any product.",
        "palette": [{"role": "primary", "name": "Neutral", "hex": "#cccccc"}],
        "sections": [{"title": "Modern Clean", "body": "Sleek minimal and bold vibrant."}],
    }
    return {
        "brief": {"title": "Luxury Fragrance Compact", "text": BRIEFS["fragrance"]},
        "routes": [dict(route), dict(route)],
        "conversation": [
            {"gate": "Research", "rationale": "A modern clean, sleek minimal take.", "brain_findings": []}
        ],
    }


@pytest.fixture
def memorized_name_pack() -> dict:
    """Route titles drawn straight from ``BANNED_TEMPLATE_NAMES``.

    Rejected by: title-not-in-BANNED (property 1) — exactly the memorized-template
    relapse the deleted exact-string asserts used to keep ALIVE.
    """

    return {
        "brief": {"title": "Luxury Fragrance Compact", "text": BRIEFS["fragrance"]},
        "routes": [
            {"title": "Refill Scent Ritual", "rationale": "memorized", "palette": [], "sections": []},
            {"title": "Quiet Atelier", "rationale": "memorized", "palette": [], "sections": []},
        ],
        "conversation": [{"gate": "Research", "rationale": "memorized", "brain_findings": []}],
    }


@pytest.fixture
def qa_vocab_pack() -> dict:
    """Public prose carrying the QA register ("fresh lane" / "borrowed route" / ...).

    Rejected by: no-QA-vocab (property 7, ``test_honesty.py``) — the honesty grep guard
    must fail when the QA vocabulary reaches a user-facing creative-prose field.
    """

    return {
        "brief": {"title": "Luxury Fragrance Compact", "text": BRIEFS["fragrance"]},
        "category_assumption": "This names the fresh lane, not a borrowed route from a prior profile.",
        "routes": [
            {
                "title": "Fresh Lane Object",
                "rationale": "A fresh lane direction, not a borrowed route.",
                "palette": [],
                "sections": [{"title": "Fresh Lane", "body": "Not a borrowed route or recycled profile."}],
            }
        ],
        "conversation": [
            {"gate": "Research", "rationale": "Names the fresh lane proof.", "brain_findings": []}
        ],
    }


# --- Shared property predicates (TST-02/TST-03) -------------------------------------
#
# These predicates are the SINGLE definition the property tests AND their paired
# negative-control rejection tests both call — that is what makes "the negative control
# provably rejects this property" a real claim: the same boolean must return True on the
# FakeDirector pack and False on the matching known-bad pack. (Pitfall 8.)

_TOKEN_RE = _re.compile(r"[A-Za-z][A-Za-z0-9]+")
_TOKEN_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "build", "create", "product", "system", "design",
        "a", "an", "of", "to", "in", "on", "this", "that", "from", "into", "like", "your",
        "route", "not", "any", "other", "moment", "every", "must",
    }
)


def tokenize(text: str) -> set[str]:
    """Lowercased content tokens (stopwords + sub-3-char dropped) — the shared tokenizer
    the brief-vocab property asserts against."""

    return {
        m.group(0).lower()
        for m in _TOKEN_RE.finditer(text or "")
        if m.group(0).lower() not in _TOKEN_STOPWORDS and len(m.group(0)) >= 3
    }


def brief_text(pack: dict) -> str:
    brief = pack.get("brief") if isinstance(pack.get("brief"), dict) else {}
    return f"{brief.get('title', '')} {brief.get('text', '')}"


def prop_titles_not_banned(pack: dict) -> bool:
    """Property 1: NO route title is a memorized template name."""

    return all(route.get("title") not in BANNED_TEMPLATE_NAMES for route in pack.get("routes", []))


def prop_title_contains_brief_vocab(pack: dict) -> bool:
    """Property 2: EVERY route title shares at least one content token with the brief."""

    vocab = tokenize(brief_text(pack))
    routes = pack.get("routes", [])
    if not routes:
        return False
    return all(bool(tokenize(route.get("title", "")) & vocab) for route in routes)


def prop_two_routes_distinct(pack: dict) -> bool:
    """Property 3: the two routes are distinct (titles AND rationales differ)."""

    routes = pack.get("routes", [])
    if len(routes) < 2:
        return False
    titles = [r.get("title") for r in routes]
    rationales = [r.get("rationale") for r in routes]
    return len(set(titles)) == len(titles) and len(set(rationales)) == len(rationales)


def prop_rationale_cites_brief_and_brain(pack: dict) -> bool:
    """Property 5: at least one conversation rationale cites a brief token AND the pack
    carries non-empty brain findings (RAG actually reached the director — Pitfall 4)."""

    vocab = tokenize(brief_text(pack))
    has_brain = any(
        entry.get("brain_findings") for entry in pack.get("conversation", [])
    ) or any(gate.get("brain_findings") for gate in pack.get("gates", []))
    if not has_brain:
        return False
    return any(
        bool(tokenize(entry.get("rationale", "")) & vocab)
        for entry in pack.get("conversation", [])
    )


def prop_no_generic_filler(pack: dict) -> bool:
    """Property 6: the route prose does NOT collapse into "modern clean" stock filler."""

    blob = " ".join(
        " ".join(
            str(route.get(k, ""))
            for k in ("title", "headline", "subhead", "lore", "mood", "rationale")
        )
        for route in pack.get("routes", [])
    ).lower()
    return not any(phrase in blob for phrase in GENERIC_FILLER_PHRASES)


# --- Creative-prose extraction for the honesty guard (HON-01) -----------------------
#
# The honesty grep must run over USER-FACING creative prose ONLY — NOT receipts, debug
# source-refs, the deterministic RAG brain-query templates, the source plan, or the gate
# plumbing. Those carry the QA register legitimately (the brain literally queries for
# "fresh lane proof" evidence; the offline origin marker says "template preview"). So we
# extract exactly the public-prose fields ``scrub_pack`` is responsible for, which is the
# surface the renderer shows the user.

def creative_prose_strings(pack: dict) -> list[str]:
    """Every user-facing creative-prose string in the pack (receipts/debug/RAG excluded)."""

    chunks: list[str] = []

    def add(value):
        if isinstance(value, str):
            chunks.append(value)
        elif isinstance(value, list):
            for v in value:
                if isinstance(v, str):
                    chunks.append(v)

    for key in (
        "title", "summary", "category_assumption", "aesthetic_void", "london_reframe",
        "vessel_interface_expression", "recurring_loop", "unboxing_first_moment", "anti_position",
    ):
        add(pack.get(key))

    lane = pack.get("session_lane")
    if isinstance(lane, dict):
        for key in ("label", "category_assumption", "aesthetic_void", "london_reframe", "anti_position", "voice", "aesthetic"):
            add(lane.get(key))

    for route in pack.get("routes", []):
        if not isinstance(route, dict):
            continue
        for key in ("title", "headline", "subhead", "lore", "mood", "type", "type_note", "rationale"):
            add(route.get(key))
        for key in ("tags", "steal", "do_not_copy"):
            add(route.get(key))
        for section in route.get("sections", []) or []:
            if isinstance(section, dict):
                add(section.get("title"))
                add(section.get("body"))

    for entry in pack.get("conversation", []) or []:
        if isinstance(entry, dict):
            for key in ("gate", "decision", "rationale", "critique", "answer"):
                add(entry.get(key))

    for entry in pack.get("route_comparison", []) or []:
        if isinstance(entry, dict):
            for key in ("title", "thesis", "best_for", "visual_world", "type", "palette_logic", "steal", "do_not_copy", "first_build_move", "risk"):
                add(entry.get(key))

    for entry in pack.get("copy_blocks", []) or []:
        if isinstance(entry, dict):
            add(entry.get("label"))
            add(entry.get("text"))

    for entry in pack.get("next_steps", []) or []:
        if isinstance(entry, dict):
            add(entry.get("label"))
            add(entry.get("description"))

    for group in pack.get("font_options", []) or []:
        if isinstance(group, dict):
            add(group.get("route_title"))
            for option in group.get("options", []) or []:
                if isinstance(option, dict):
                    for key in ("name", "best_use", "why_london_chose_it", "why_this_route_not_other_route", "what_makes_it_wrong", "import_hint"):
                        add(option.get(key))

    return chunks


def strip_debug_drawers(html: str) -> str:
    """Remove the evidence / debug-receipt / receipts ``<details>`` drawers from rendered
    HTML so the honesty grep sees only the VISIBLE creative surface (receipts/debug
    excluded, exactly as HON-01 requires)."""

    return _re.sub(r"<details.*?</details>", "", html or "", flags=_re.DOTALL | _re.IGNORECASE)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "real_director: do NOT pin the default director to OfflineDirector — exercise the real selection logic.",
    )


@pytest.fixture(autouse=True)
def default_director_is_offline(request, monkeypatch):
    """Pin the default ``write_london_pack`` director to ``OfflineDirector`` (keyless).

    After the A5 flip the default path invokes ``ClaudeCodeDirector.direct()``, which
    raises ``LondonNoModelError`` with no model reachable (CI). The deterministic suite
    is the OfflineDirector parity oracle, so we make the default resolve to
    ``OfflineDirector`` here. ``@pytest.mark.real_director`` opts a test out so it can
    assert the real selection (default→ClaudeCodeDirector, ``--offline``→OfflineDirector,
    injected→FakeDirector).
    """

    if "real_director" in request.keywords:
        return

    from london import cli
    from london.director import OfflineDirector

    real_resolve = cli._resolve_director

    def _offline_default(*, offline, director, env):
        if director is None and not offline:
            return OfflineDirector()
        return real_resolve(offline=offline, director=director, env=env)

    monkeypatch.setattr(cli, "_resolve_director", _offline_default)
