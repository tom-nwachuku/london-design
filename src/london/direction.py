"""Director contract models and protocol."""

from __future__ import annotations

from typing import Any, Literal, Mapping, Protocol, Sequence, runtime_checkable

from pydantic import BaseModel, Field

from london.errors import LondonError
from london.telemetry import RunTelemetry, _honest_empty_telemetry

# The hex pattern the pack schema enforces on every palette colour
# (schemas/london-pack.schema.json $defs.paletteColor.hex). DirectionResult mirrors it
# so an off-spec model palette is rejected by the contract, not silently written.
HEX_PATTERN = r"^#[0-9a-fA-F]{6}$"

# The three font tiers the pack schema enumerates
# ($defs.fontOption.tier). The model must choose from these.
FONT_TIERS = ("safe_local", "open_public", "premium_inspiration")
FONT_PREVIEW_STATUSES = ("actual_loaded", "fallback_approximation", "reference_only")
FONT_PREVIEW_DELIVERIES = ("local_asset", "system_fallback", "reference_only")


class LondonNoModelError(LondonError):
    """Raised when no creative-direction model is reachable and ``--offline`` was not chosen.

    The full dual fix-it message (run inside Claude Code / set ``ANTHROPIC_API_KEY``
    vs ``pip install london[offline]`` then ``--offline``) is authored in A4 where
    ``ClaudeCodeDirector`` does the in-session/keyed auto-detect (D-01/D-02). Defined
    here so every director implementation shares one exception type and never falls
    back to the deterministic engine (D-03).
    """


# --- DirectionResult nested models (mirror the pack schema $defs; provenance, not shape) ---


class PaletteColor(BaseModel):
    """One palette swatch — mirrors $defs.paletteColor (hex pattern enforced)."""

    role: str
    name: str
    hex: str = Field(pattern=HEX_PATTERN)


class RouteResult(BaseModel):
    """One visual route's creative text — mirrors $defs.visualRoute + the route prose
    fields the dossier renders (title/headline/subhead/palette/tags/lore/mood/type_note/
    rationale/steal/do_not_copy/sections)."""

    title: str = Field(min_length=1)
    headline: str
    subhead: str
    palette: list[PaletteColor] = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    lore: str
    mood: str
    type_note: str
    rationale: str = Field(min_length=1)
    steal: list[str] = Field(default_factory=list)
    do_not_copy: list[str] = Field(default_factory=list)
    sections: list["RouteSection"] = Field(default_factory=list)


class RouteSection(BaseModel):
    """A titled body block inside a route (the route ``sections[]`` entries)."""

    title: str
    body: str


class FontPreview(BaseModel):
    """Optional rendered-preview metadata for one Font Lab option."""

    status: Literal["actual_loaded", "fallback_approximation", "reference_only"]
    delivery: Literal["local_asset", "system_fallback", "reference_only"]
    rendered_family: str = Field(min_length=1)
    source_label: str
    license_note: str
    asset_href: str | None = None
    reference_visual: bool | None = None
    reference_preview: dict[str, Any] | None = None


class FontOption(BaseModel):
    """One font option in a route's font lab — mirrors $defs.fontOption.

    ``why_this_route_not_other_route`` is required with ``min_length=1`` exactly as the
    pack schema requires it; it is the field most likely to be under-filled and the one
    the route-distinctness story depends on.
    """

    tier: str = Field(pattern=r"^(safe_local|open_public|premium_inspiration)$")
    name: str = Field(min_length=1)
    headline_font: str = Field(min_length=1)
    body_font: str = Field(min_length=1)
    label_font: str = Field(min_length=1)
    fallback_stack: str = Field(min_length=1)
    best_use: str
    why_london_chose_it: str
    why_this_route_not_other_route: str = Field(min_length=1)
    what_makes_it_wrong: str
    import_hint: str
    font_preview: FontPreview | None = None


class FontRouteGroup(BaseModel):
    """A route's 3-tier font lab — mirrors $defs.fontRouteGroup (≥3 options)."""

    route_title: str = Field(min_length=1)
    options: list[FontOption] = Field(min_length=3)


class ConversationRead(BaseModel):
    """One London decision — the open-list (count = len) unit of the variable-N
    conversation (D-01). London authors N of these (observed 3–7, treat as unbounded);
    the cage that padded them to 7 and index-mapped them onto fixed gates is gone.

    Per D-02 only ``gate`` + ``decision`` are REQUIRED — they are the decision and its
    label. ``rationale``/``critique``/``answer`` are OPTIONAL (default ``""``): they blur
    on brief-specific gates, so the model may omit them and a gate+decision-only read is
    valid. The structural plumbing (id/order/evidence counts/badges) stays Python-computed;
    the model writes prose only."""

    gate: str = Field(min_length=1)
    decision: str = Field(min_length=1)
    rationale: str = ""
    critique: str = ""
    answer: str = ""


class RouteComparison(BaseModel):
    """One route's comparison row — mirrors $defs.routeComparison prose fields."""

    title: str = Field(min_length=1)
    thesis: str
    best_for: str
    visual_world: str
    type: str
    palette_logic: str
    steal: str
    do_not_copy: str
    first_build_move: str
    risk: str


class CopyBlock(BaseModel):
    """A reusable copy block — mirrors $defs.copyBlock prose (id/scope are Python plumbing)."""

    kind: str = Field(min_length=1)
    label: str = Field(min_length=1)
    text: str = Field(min_length=1)


class NextStep(BaseModel):
    """A suggested next action — mirrors $defs.nextStep prose."""

    label: str = Field(min_length=1)
    description: str = Field(min_length=1)
    action_type: str = Field(min_length=1)


class DirectionResult(BaseModel):
    """Every creative-text field both stages and the renderer consume — the executable
    spec the director produces in ONE structured call (D-07).

    Lane-level fields come from stage 1 (``_synthesize_session_lane``); route-level,
    conversation, font-lab, route-comparison, copy and next-step fields come from
    stage 2 (``enrich_workbench_pack``). Counts (``*_count``), ``source_ref`` IDs,
    dedupe, ``digest`` and receipts are NOT here — Python computes those facts; the
    model only writes prose (RESEARCH §DirectionResult Contract).

    :meth:`model_json_schema` round-trips to a Draft 2020-12-compatible schema whose
    route/font/conversation property names agree with the matching $defs in
    ``schemas/london-pack.schema.json``; :meth:`model_dump` yields the pack-shaped dict
    the dict-consuming stages expect.
    """

    # Lane-level (stage 1)
    category_assumption: str
    aesthetic_void: str
    london_reframe: str
    vessel_expression: str
    recurring_loop: str
    unboxing: str
    anti_position: str
    product_noun: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    jobs: list[str] = Field(min_length=1)
    rituals: list[str] = Field(min_length=1)
    surfaces: list[str] = Field(min_length=1)
    tensions: list[str] = Field(min_length=1)
    tone: list[str] = Field(min_length=1)
    avoid: list[str] = Field(default_factory=list)
    output_moments: list[str] = Field(min_length=1)
    source_terms: str = Field(min_length=1)
    label: str = Field(min_length=1)
    voice: str
    type_system: str
    color_system: str
    palette: list[PaletteColor] = Field(min_length=1)

    # Route-level (stage 1) — exactly two routes
    routes: list[RouteResult] = Field(min_length=2)

    # Recommended route (D-04) — SPLIT into a machine reference + verbatim prose.
    #
    # `recommended_route_ref` is the GENUINE lead route the model picks, expressed as a
    # MACHINE-RESOLVABLE reference (it equals an actual route's title so the renderer can
    # resolve the accent + "Recommended" badge deterministically — NEVER by fuzzy-matching
    # the prose to a title, which is the render.py:257 silent-failure bug). A REAL required
    # field BOTH model paths emit via constrained decoding off model_json_schema(); the
    # deterministic paths (FakeDirector / OfflineDirector) set the HONEST floor =
    # routes[0].title (never a faked ranking).
    recommended_route_ref: str = Field(min_length=1)

    # `recommended_route` is now the verbatim free-length recommendation PROSE — London's
    # argument for the pick, rendered byte-for-byte (observed 11–704 chars; no max_length,
    # so a 1000-char argument survives unsummarized — D-11 forbids a summarizer). No
    # min_length: the deterministic FLOOR is "" (the offline/Fake paths never argue a case,
    # D-04). The renderer surfaces this AS GIVEN — no renderer derivation, no truncation.
    recommended_route: str = ""

    # Artifact type (Gate-0 / GATE-01) — the session-level KIND of thing being designed,
    # cloning the recommended_route discipline: a REAL Literal field so BOTH model paths
    # are constrained to emit it via model_json_schema() (Pydantic renders a Literal as a
    # JSON-Schema enum; the hand-written schema enum at london-pack.schema.json MUST match).
    # The host model MAY honestly declare a specific type from the brief; the DETERMINISTIC
    # paths (FakeDirector / OfflineDirector) emit "generic" — never a faked specific type
    # (GATE-02 / RESEARCH Pitfall 3). The CLI flag / brief field OVERRIDE this at
    # pack-assembly time (resolution order: flag > brief > model > generic). NOT a GATE_ID.
    # No Python default (exactly like recommended_route): a required Literal so the model
    # path is constrained to EMIT one of the 5 values, and the schema marks it required.
    # The honest "generic" floor lives at the deterministic directors + the CLI chokepoint,
    # never as a silent Pydantic default that would let the model omit the field.
    artifact_type: Literal["website", "app", "product", "brand", "generic"]

    # Conversation reads (stage 2) — one per gate
    conversation: list[ConversationRead] = Field(min_length=1)

    # Font logic (stage 2) — one group per route, ≥3 options each
    font_options: list[FontRouteGroup] = Field(min_length=1)

    # Route comparison / copy / next steps (stage 2)
    route_comparison: list[RouteComparison] = Field(min_length=1)
    copy_blocks: list[CopyBlock] = Field(min_length=1)
    next_steps: list[NextStep] = Field(min_length=1)


# RouteResult forward-references RouteSection; rebuild now that it is defined.
RouteResult.model_rebuild()


# --- DirectionRequest: the deterministic facts the engine feeds the director ---


class DirectionRequest(BaseModel):
    """The deterministic FACTS the engine computes and feeds the director — the model's
    INPUT, never creative text.

    Mirrors the ``image_generation.ImageGenerationRequest`` field discipline (one frozen
    request object), but as a Pydantic model carrying:

    * ``brief``           — the coerced brief record (title/text/digest/tokens).
    * ``brain_findings``  — per-gate London-Brain RAG findings (gate_id -> [findings]).
    * ``source_plan``     — the deterministic source plan the engine built.
    * ``product_tokens``  — the brief's salient nouns/terms (the echo seed for the fake).

    The brief is user-controlled text crossing a trust boundary here (threat T-02-03);
    A4's ``ClaudeCodeDirector`` delimits/spotlights it before it seeds the model prompt.
    No provider key ever enters this object (V2 control).
    """

    model_config = {"frozen": True}

    brief: Mapping[str, Any]
    brain_findings: Mapping[str, Sequence[Mapping[str, Any]]] = Field(default_factory=dict)
    source_plan: Mapping[str, Any] = Field(default_factory=dict)
    product_tokens: Sequence[str] = Field(default_factory=tuple)
    # GATE-02: the resolved artifact type (flag/brief) the in-session model may HONOR when it
    # writes DirectionResult.artifact_type. Defaults to "generic" so a keyless/no-signal run
    # carries the honest floor; the model is never forced to fake a specific type.
    artifact_type: str = "generic"
    # Phase 6.1: optional real click from the London, Show Me companion. This is
    # deterministic user feedback for a later model pass, never a fabricated result.
    visual_selection: Mapping[str, Any] = Field(default_factory=dict)


# --- The director Protocol (one structured call, D-07) ---


@runtime_checkable
class CreativeDirector(Protocol):
    """The director seam — one structured call returns the whole DirectionResult.

    ``FakeDirector`` (this module), ``OfflineDirector`` (A3) and ``ClaudeCodeDirector``
    (A4) all satisfy this Protocol; the engine never inspects the concrete director type
    (strategy is chosen at the CLI/skill boundary).

    ``direct_with_telemetry`` is the ADDITIVE GRADE-01 seam (D-05): it returns the SAME
    ``DirectionResult`` plus a structurally-separate :class:`RunTelemetry` side-channel
    (London does not grade his own homework). It is additive on purpose — ``direct()``'s
    signature and return type are UNCHANGED, so no existing caller or test mock breaks.
    Only ``ClaudeCodeDirector``'s in-session path produces a REAL ``captured=True``
    transcript; every other path emits honest ``captured=False`` telemetry. A Protocol
    method's default body does NOT propagate to implementers under ``runtime_checkable``
    ``isinstance`` (it only checks method NAMES exist), so each concrete director carries
    a thin ``direct_with_telemetry`` of its own that delegates to the shared helpers.
    """

    def direct(self, request: DirectionRequest) -> DirectionResult: ...

    def direct_with_telemetry(
        self, request: DirectionRequest
    ) -> tuple[DirectionResult, RunTelemetry]:
        """Default seam: run ``direct()`` and return honest ``captured=False`` telemetry.

        Concrete directors override this (the deterministic paths with a one-line honest
        delegate; ``ClaudeCodeDirector`` with the real in-session tap).
        """

        return self.direct(request), _honest_empty_telemetry("offline")

__all__ = [
    "HEX_PATTERN",
    "FONT_TIERS",
    "FONT_PREVIEW_STATUSES",
    "FONT_PREVIEW_DELIVERIES",
    "LondonNoModelError",
    "PaletteColor",
    "RouteResult",
    "RouteSection",
    "FontPreview",
    "FontOption",
    "FontRouteGroup",
    "ConversationRead",
    "RouteComparison",
    "CopyBlock",
    "NextStep",
    "DirectionResult",
    "DirectionRequest",
    "CreativeDirector",
]
