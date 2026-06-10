"""Offline fake director used by tests and contract probes."""

from __future__ import annotations

import hashlib
import re
from typing import Sequence

from london.direction import (
    FONT_TIERS,
    ConversationRead,
    CopyBlock,
    DirectionRequest,
    DirectionResult,
    FontOption,
    FontRouteGroup,
    NextStep,
    PaletteColor,
    RouteComparison,
    RouteResult,
    RouteSection,
)
from london.telemetry import RunTelemetry, _honest_empty_telemetry


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")
_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "build", "create", "product", "system", "design",
        "a", "an", "of", "to", "in", "on", "this", "that", "from", "into", "like",
    }
)


def _tokenize(text: str) -> list[str]:
    """Lowercased word tokens — the shared tokenizer the echo property asserts against."""

    return [m.group(0).lower() for m in _TOKEN_RE.finditer(text or "")]


def _salient_tokens(request: DirectionRequest) -> list[str]:
    """Brief-specific tokens to echo into prose, in stable order, stopwords removed.

    Prefers explicit ``request.product_tokens`` (the engine's parse), then falls back to
    the brief title + text. This is what makes FakeDirector ECHO the brief — a fake that
    returned constants would make every downstream brief-specificity property pass
    trivially (Pitfall 8), so the salient tokens MUST come from the request.
    """

    explicit = [t.lower() for t in request.product_tokens if t]
    title = str(request.brief.get("title", ""))
    text = str(request.brief.get("text", ""))
    candidates = explicit + _tokenize(title) + _tokenize(text)

    ordered: list[str] = []
    for tok in candidates:
        if tok in _STOPWORDS or len(tok) < 3:
            continue
        if tok not in ordered:
            ordered.append(tok)
    return ordered or ["brief"]


def _brief_hash(tokens: Sequence[str]) -> int:
    """Stable integer derived from the brief tokens — seeds divergent fake palettes so
    two unrelated briefs yield distinct titles AND distinct palettes (the distinctness
    property fails on a generic pack but passes on the echoing fake)."""

    digest = hashlib.sha256("|".join(tokens).encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _hex_from(seed: int, offset: int) -> str:
    """Deterministic 6-hex colour from a seed + offset (always matches HEX_PATTERN)."""

    value = (seed * 2654435761 + offset * 40503) & 0xFFFFFF
    return f"#{value:06x}"


def _fake_palette(seed: int, base_offset: int) -> list[PaletteColor]:
    roles = ("primary", "secondary", "accent")
    return [
        PaletteColor(role=role, name=f"{role.title()} {seed % 97}", hex=_hex_from(seed, base_offset + i))
        for i, role in enumerate(roles)
    ]


def _first_finding_title(request: DirectionRequest) -> str:
    """The first per-gate brain-finding title, so the fake's rationale cites real RAG
    input (the rationale-cites-brief-and-brain property in A6 depends on this)."""

    for findings in request.brain_findings.values():
        for finding in findings:
            title = str(finding.get("title") or finding.get("insight_title") or "").strip()
            if title:
                return title
    return ""


def _fake_route(noun: str, tokens: Sequence[str], finding: str, seed: int, index: int) -> RouteResult:
    """Build one schema-valid route whose title + rationale INTERPOLATE brief tokens."""

    ritual = tokens[(index + 1) % len(tokens)] if len(tokens) > 1 else noun
    surface = tokens[(index + 2) % len(tokens)] if len(tokens) > 2 else ritual
    title = f"{noun.title()} {ritual.title()} Route {index + 1}"
    cite = f' — anchored on the brain note "{finding}"' if finding else ""
    rationale = (
        f"Route {index + 1} commits to {noun} as a {ritual} system; it reads the brief's "
        f"{surface} moment as the proof surface{cite}."
    )
    return RouteResult(
        title=title,
        headline=f"{noun.title()} that earns the {ritual}",
        subhead=f"Built around the {surface} the brief keeps returning to.",
        palette=_fake_palette(seed, base_offset=index * 17),
        tags=[noun, ritual, surface],
        lore=f"The {noun} began as a {ritual} object, not a {surface} afterthought.",
        mood=f"{ritual.title()}, deliberate, {noun}-first.",
        type_note=f"Type carries the {ritual} before any imagery arrives.",
        rationale=rationale,
        steal=[f"the {ritual} rhythm", f"the {surface} restraint"],
        do_not_copy=[f"generic {noun} gloss"],
        sections=[
            RouteSection(title=f"{ritual.title()} screen", body=f"Lead with the {ritual}, not the logo."),
            RouteSection(title=f"{surface.title()} proof", body=f"Show the {surface} doing real work."),
        ],
    )


def _fake_conversation(noun: str, tokens: Sequence[str], finding: str) -> list[ConversationRead]:
    from london.persona import GATE_IDS, GATE_NAMES

    cite = f' (brain: "{finding}")' if finding else ""
    proof = tokens[0] if tokens else noun
    return [
        ConversationRead(
            gate=GATE_NAMES.get(gate_id, gate_id),
            decision=f"Treat {noun} as a {proof} system at the {GATE_NAMES.get(gate_id, gate_id)} gate.",
            rationale=f"The brief's {proof} signal drives this gate's call{cite}.",
            critique=f"Reject anything that flattens {noun} into generic {proof} decoration.",
            answer=f"London commits to the {proof}-first read of {noun}.",
        )
        for gate_id in GATE_IDS
    ]


def _fake_font_group(route: RouteResult, other: RouteResult, noun: str) -> FontRouteGroup:
    tiers = FONT_TIERS
    options = [
        FontOption(
            tier=tier,
            name=f"{route.title} {tier.replace('_', ' ').title()}",
            headline_font=f"{noun.title()} Display {i}",
            body_font=f"{noun.title()} Text {i}",
            label_font=f"{noun.title()} Mono {i}",
            fallback_stack="system-ui, sans-serif",
            best_use=f"Best for the {tier.replace('_', ' ')} read of {route.title}.",
            why_london_chose_it=f"It carries {route.title}'s point of view without decoration.",
            why_this_route_not_other_route=(
                f"{route.title} needs this voice; {other.title} reads too differently to share it."
            ),
            what_makes_it_wrong=f"Wrong if it drifts toward generic {noun} gloss.",
            import_hint=f"Pair the {tier.replace('_', ' ')} tier with {route.title}.",
        )
        for i, tier in enumerate(tiers)
    ]
    return FontRouteGroup(route_title=route.title, options=options)


def _fake_comparison(route: RouteResult, noun: str) -> RouteComparison:
    return RouteComparison(
        title=route.title,
        thesis=f"{route.title} treats {noun} as the whole idea, not the wrapper.",
        best_for=f"Teams who want {noun} to feel inevitable.",
        visual_world=route.mood,
        type=route.type_note,
        palette_logic=f"Palette built from the brief's own {noun} signal.",
        steal=route.steal[0] if route.steal else f"the {noun} restraint",
        do_not_copy=route.do_not_copy[0] if route.do_not_copy else f"generic {noun} gloss",
        first_build_move=route.sections[0].body if route.sections else f"Build the {noun} screen first.",
        risk=f"Risk: {route.title} over-commits before the {noun} proof lands.",
    )


class FakeDirector:
    """The executable spec (ENG-03): returns a fully schema-valid DirectionResult whose
    prose fields ECHO the request's brief tokens — never constants.

    Requires no network and no API key. ``isinstance(FakeDirector(), CreativeDirector)``
    holds. A FakeDirector that returned constants would make every downstream
    brief-specificity property pass trivially (Pitfall 8 / threat T-02-02) — so the
    titles/rationale interpolate ``request`` tokens and the palettes are seeded from a
    brief-token hash, which is exactly what lets the echo + distinctness properties FAIL
    on a generic pack while passing on the fake.
    """

    def direct(self, request: DirectionRequest) -> DirectionResult:
        tokens = _salient_tokens(request)
        noun = tokens[0]
        finding = _first_finding_title(request)
        seed = _brief_hash(tokens)
        ritual = tokens[1] if len(tokens) > 1 else noun
        surface = tokens[2] if len(tokens) > 2 else ritual

        routes = [
            _fake_route(noun, tokens, finding, seed, 0),
            _fake_route(noun, tokens, finding, seed + 911, 1),
        ]
        cite = f' The brain note "{finding}" backs it.' if finding else ""

        return DirectionResult(
            category_assumption=f"The category assumes {noun} is a {surface} commodity.",
            aesthetic_void=f"No one treats {noun} as a {ritual} ritual yet.",
            london_reframe=f"Reframe {noun} as a {ritual}-first system, not {surface} decoration.{cite}",
            vessel_expression=f"The {noun} vessel should express the {ritual} the moment it is held.",
            recurring_loop=f"The {ritual} repeats every time the {noun} is used.",
            unboxing=f"First moment: the {noun} reveals its {ritual}, not its {surface}.",
            anti_position=f"This is not another {surface}-led {noun}.",
            product_noun=noun,
            audience=f"People who care about the {ritual} of {noun}.",
            jobs=[f"make {noun} feel like a {ritual}", f"prove the {surface}"],
            rituals=[ritual, f"daily {ritual}"],
            surfaces=[surface, f"{noun} label"],
            tensions=[f"{ritual} vs convenience", f"{surface} vs restraint"],
            tone=[ritual, "deliberate", "product-first"],
            avoid=[f"generic {noun} gloss", "stock minimalism"],
            output_moments=[f"the {ritual} reveal", f"the {surface} close-up"],
            source_terms=", ".join(tokens[:6]),
            label=f"{noun.title()} {ritual.title()} Direction",
            voice=f"Opinionated, {ritual}-first, {noun}-specific.",
            type_system=f"Type that carries the {ritual} of {noun}.",
            color_system=f"Color drawn from the brief's {noun} world, not a trend deck.",
            palette=_fake_palette(seed, base_offset=3),
            routes=routes,
            # Honest deterministic floor (D-04): the machine reference = the lead route,
            # never a faked ranking; the recommendation PROSE = "" (the floor never argues
            # a case — only the host model writes a verbatim argument).
            recommended_route_ref=routes[0].title or "Route 01",
            recommended_route="",
            # Honest deterministic default (GATE-02 / RESEARCH Pitfall 3): the deterministic
            # paths cannot truthfully infer a specific type, so they default to "generic" —
            # never a faked specific type. Only the host model / flag / brief may assert one.
            artifact_type="generic",
            conversation=_fake_conversation(noun, tokens, finding),
            font_options=[
                _fake_font_group(routes[0], routes[1], noun),
                _fake_font_group(routes[1], routes[0], noun),
            ],
            route_comparison=[_fake_comparison(routes[0], noun), _fake_comparison(routes[1], noun)],
            copy_blocks=[
                CopyBlock(
                    kind="summary",
                    label=f"{noun.title()} summary",
                    text=f"{noun.title()} as a {ritual} system — the {surface} is the proof.",
                ),
                CopyBlock(
                    kind="critique",
                    label="London's critique",
                    text=f"If it reads like a generic {noun}, it failed the {ritual} test.",
                ),
            ],
            next_steps=[
                NextStep(
                    label=f"Build the {ritual} screen",
                    description=f"Prototype the {ritual}-first {noun} screen from {routes[0].title}.",
                    action_type="prototype",
                ),
                NextStep(
                    label=f"Pressure-test the {surface}",
                    description=f"Check the {surface} proof against the brief's {noun} claim.",
                    action_type="review",
                ),
            ],
        )

    def direct_with_telemetry(
        self, request: DirectionRequest
    ) -> tuple[DirectionResult, RunTelemetry]:
        # The fake path has no MCP transcript — emit HONEST captured=False telemetry
        # (engine_mode="fake"), never a faked capture (D-11 / T-05-08).
        return self.direct(request), _honest_empty_telemetry("fake")

__all__ = ["FakeDirector"]
