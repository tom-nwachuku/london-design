"""Compatibility re-export shim for London director contracts and implementations."""

from __future__ import annotations


from london.direction import (
    FONT_PREVIEW_DELIVERIES,
    FONT_PREVIEW_STATUSES,
    FONT_TIERS,
    HEX_PATTERN,
    ConversationRead,
    CopyBlock,
    CreativeDirector,
    DirectionRequest,
    DirectionResult,
    FontOption,
    FontPreview,
    FontRouteGroup,
    LondonNoModelError,
    NextStep,
    PaletteColor,
    RouteComparison,
    RouteResult,
    RouteSection,
)
from london.directors.claude import (
    ClaudeCodeDirector,
    _ANTHROPIC_SECRET_KEYS,
    _CLAUDE_CLI_PRINT_ENV,
    _DIRECTOR_MODE_ENV,
)
from london.directors.fake import FakeDirector
from london.directors.offline import (
    OFFLINE_ORIGIN_MARKER,
    PROFILES,
    ROUTE_SYNTHESIS_PROVIDER,
    CategoryProfile,
    CreativeLane,
    OfflineDirector,
    RouteSeed,
    SessionLane,
    _offline_first_font_stack,
)
from london.telemetry import (
    BrainQueryTrace,
    RunTelemetry,
    _capture_telemetry_from_messages,
    _honest_empty_telemetry,
)

__all__ = [
    "HEX_PATTERN",
    "FONT_TIERS",
    "LondonNoModelError",
    "PaletteColor",
    "RouteSection",
    "RouteResult",
    "FontOption",
    "FontRouteGroup",
    "ConversationRead",
    "RouteComparison",
    "CopyBlock",
    "NextStep",
    "DirectionResult",
    "DirectionRequest",
    "CreativeDirector",
    "FakeDirector",
    "ClaudeCodeDirector",
    "OfflineDirector",
    "OFFLINE_ORIGIN_MARKER",
    "ROUTE_SYNTHESIS_PROVIDER",
    "RouteSeed",
    "CategoryProfile",
    "SessionLane",
    "CreativeLane",
    "PROFILES",
]
__all__ += [
    "BrainQueryTrace",
    "RunTelemetry",
    "FontPreview",
    "FONT_PREVIEW_STATUSES",
    "FONT_PREVIEW_DELIVERIES",
    "_ANTHROPIC_SECRET_KEYS",
    "_CLAUDE_CLI_PRINT_ENV",
    "_DIRECTOR_MODE_ENV",
    "_capture_telemetry_from_messages",
    "_honest_empty_telemetry",
    "_offline_first_font_stack",
]
