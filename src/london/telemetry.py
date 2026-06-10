"""Director telemetry side-channel models and transcript capture helpers."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

# --- RunTelemetry side-channel (D-05 / GRADE-01) — STRUCTURALLY SEPARATE from
#     DirectionResult. London does NOT grade his own homework: the objective record of
#     what the engine actually did (real brain queries + the source IDs the brain
#     returned) is a DIFFERENT object from London's creative claims. These models are the
#     fixed contract Plans 02 (the telemetry tap) and 03 (the grader) build against; they
#     are NEVER added as a field on DirectionResult (fusing them would let the claims and
#     the objective record mix — threat T-05-03). Every list is `default_factory=list`
#     (open, 0..N) — no overfit to any observed run's shape.


class BrainQueryTrace(BaseModel):
    """One real ``london_brain_query`` tool call captured from the in-session transcript.

    The query string is public-safe (it passes the single ``scrub_pack`` chokepoint);
    ``returned_source_ids`` are the ``source-…`` finding IDs the brain RETURNED (ground
    truth for the grader's claim-integrity check), correlated to the call by
    ``tool_use_id``. Raw finding BODIES are never carried here (Information Disclosure
    boundary — only IDs + counts cross into a public receipt).
    """

    query: str
    tool_use_id: str
    returned_source_ids: list[str] = Field(default_factory=list)
    result_count: int = 0
    # D-03: an OPTIONAL internal 7-phase telemetry label, attached only if London signals
    # which method-phase a query belonged to. NEVER shapes/caps/pads the user-visible
    # conversation — a grader detail, kept internal by default.
    phase_label: str | None = None


class RunTelemetry(BaseModel):
    """The objective record of one director run — the side-channel the grader audits.

    ``captured`` is the honesty flag: only the in-session (tapped) path can observe the
    MCP transcript, so the keyed/offline/fake paths emit ``captured=False`` (an HONEST
    "transcript unavailable on this engine mode", NOT a fabricated dead-engine of zeros).
    A real 0-call run on the in-session path is ``captured=True, brain_query_count=0`` —
    distinct from an unavailable transcript.
    """

    engine_mode: str
    brain_query_count: int = 0
    brain_queries: list[BrainQueryTrace] = Field(default_factory=list)
    consulted_source_ids: list[str] = Field(default_factory=list)
    brain_total_entries: int = 0
    tool_call_count: int = 0
    duration_ms: int | None = None
    captured: bool = True


# --- The corrected in-session telemetry tap (D-05 / GRADE-01, RESEARCH Pitfall 1) ---
#
# These two module-level helpers ARE Approach A, isolated from the live ``query()`` loop
# so they are unit-testable against a SYNTHETIC SDK message stream (no live model, no
# key). The crucial correction over the spike harness: brain-query STRINGS arrive in
# ``AssistantMessage`` ``ToolUseBlock``s, but the returned ``source-…`` IDs (the grader's
# ground truth) arrive in ``UserMessage`` ``ToolResultBlock``s — NOT ``AssistantMessage``.
# A tap that only iterated ``AssistantMessage`` (the harness bug) captures the query
# strings but loses every source ID. We iterate BOTH and correlate by
# ``ToolUseBlock.id == ToolResultBlock.tool_use_id``.


_BRAIN_QUERY_TOOL_SUFFIX = "london_brain_query"


def _parse_tool_result(content: Any) -> dict:
    """Defensively parse a ``ToolResultBlock.content`` into the brain payload dict.

    ``content`` is ``str | list[dict]`` (the SDK shape). The string form is the JSON
    payload; the list form is a list of ``{"text": <json>}`` content blocks (or objects
    with a ``.text`` attribute). A malformed/partial payload returns ``{}`` — NEVER raises
    (T-05-06 DoS mitigation; mirrors the proven harness pattern at
    capture_harness.py:104-108). This is the trust boundary where the untrusted tool
    transcript crosses into structured telemetry, so every parse is wrapped.
    """

    def _loads(text: Any) -> dict:
        try:
            parsed = json.loads(text)
        except Exception:  # noqa: BLE001 - any parse failure is an honest empty payload
            return {}
        return parsed if isinstance(parsed, dict) else {}

    if isinstance(content, str):
        return _loads(content)
    if isinstance(content, list):
        # The brain payload is delivered as a single text block; if there are several,
        # the first one that parses into a dict with ``findings``/``count`` wins. Reading
        # ONLY the structured fields below means raw finding BODIES never leave here.
        for block in content:
            text = block.get("text") if isinstance(block, dict) else getattr(block, "text", None)
            if not text:
                continue
            payload = _loads(text)
            if payload:
                return payload
    return {}


def _safe_result_count(value: Any, *, fallback: int) -> int:
    """Coerce an untrusted brain-result count without letting telemetry throw."""

    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _capture_telemetry_from_messages(messages: Any, *, engine_mode: str, duration_ms: int | None = None) -> RunTelemetry:
    """Build a ``RunTelemetry`` from an iterable of SDK messages (the corrected tap).

    Iterates ``AssistantMessage`` for ``ToolUseBlock`` (query string + tool_use_id) AND
    ``UserMessage`` for ``ToolResultBlock`` (returned ``source-…`` IDs + count), correlating
    by ``tool_use_id``. ``captured=True`` — this is the in-session path that has a real
    transcript. Raw finding bodies are NEVER read (only ``findings[].id`` + ``count`` cross
    the boundary — T-05-05 Information Disclosure mitigation).
    """

    # Local imports keep ``claude_agent_sdk`` a guarded dependency of the in-session path,
    # not a hard module-import (the offline/fake paths must work with the SDK absent).
    from claude_agent_sdk import AssistantMessage, ToolResultBlock, ToolUseBlock, UserMessage

    # tool_use_id -> {query, source_ids, count} — insertion order preserves call order.
    queries: dict[str, dict] = {}
    tool_call_count = 0

    for msg in messages:
        if isinstance(msg, AssistantMessage):
            for block in msg.content or []:
                if isinstance(block, ToolUseBlock):
                    tool_call_count += 1
                    if block.name.endswith(_BRAIN_QUERY_TOOL_SUFFIX):
                        queries[block.id] = {
                            "query": (block.input or {}).get("query", ""),
                            "source_ids": [],
                            "count": 0,
                        }
        elif isinstance(msg, UserMessage):
            content = msg.content
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, ToolResultBlock) and block.tool_use_id in queries:
                        payload = _parse_tool_result(block.content)
                        findings = payload.get("findings", []) if isinstance(payload, dict) else []
                        # Capture the CITED form: London cites the `source-{12hex}` provenance
                        # ref (RESEARCH Q4 / library.py:793), which the brain returns as
                        # `findings[].source_ref` — NOT the 24-hex internal entry `id`
                        # (library.py:782). The grader's claim-integrity regex matches `source-…`,
                        # so `consulted_source_ids` MUST carry that same form or every legit
                        # citation would spuriously fire CLAIM_UNVERIFIED (the two ID namespaces
                        # never intersect). Prefer `source_ref`; fall back to `id` when a result
                        # carries no `source_ref` (so an `id`-only payload still yields a usable,
                        # if non-canonical, consulted set). Public-safe — never a finding BODY.
                        source_ids = [
                            f.get("source_ref") or f.get("id")
                            for f in findings
                            if isinstance(f, dict) and (f.get("source_ref") or f.get("id"))
                        ]
                        rec = queries[block.tool_use_id]
                        rec["source_ids"] = source_ids
                        rec["count"] = payload.get("count", len(findings)) if isinstance(payload, dict) else 0

    brain_queries = [
        BrainQueryTrace(
            query=rec["query"],
            tool_use_id=tool_use_id,
            returned_source_ids=list(rec["source_ids"]),
            result_count=_safe_result_count(rec.get("count"), fallback=len(rec["source_ids"])),
        )
        for tool_use_id, rec in queries.items()
    ]

    # The consulted set is the ORDER-PRESERVING union of every returned ID across queries
    # (ground truth for the grader's claim-integrity check). Deduped but stable.
    consulted: list[str] = []
    seen: set[str] = set()
    for trace in brain_queries:
        for sid in trace.returned_source_ids:
            if sid not in seen:
                seen.add(sid)
                consulted.append(sid)

    return RunTelemetry(
        engine_mode=engine_mode,
        brain_query_count=len(brain_queries),
        brain_queries=brain_queries,
        consulted_source_ids=consulted,
        brain_total_entries=_live_brain_total_entries(),
        tool_call_count=tool_call_count,
        duration_ms=duration_ms,
        captured=True,
    )


def _live_brain_total_entries() -> int:
    """The SOURCES-MATRIX denominator, read LIVE from the swappable brain inventory.

    NEVER hardcode the count (3439 today): the brain is swappable via ``LONDON_BRAIN_PATH``
    (BRAIN-01), so a hardcoded denominator would desync the gauge the moment a different
    brain is mounted. A read failure returns 0 (an honest "unknown denominator"), never a
    crash — the tap must not fail a real run over a telemetry nicety.
    """

    try:
        from london.brain_loader import resolve_brain_path
        from london.library import inventory_from_sqlite

        return int(inventory_from_sqlite(resolve_brain_path()).total_entries)
    except Exception:  # noqa: BLE001 - the denominator is best-effort, never load-bearing
        return 0


def _honest_empty_telemetry(engine_mode: str) -> RunTelemetry:
    """The honest ``captured=False`` telemetry the non-tapped paths emit (D-11 / T-05-08).

    The keyed/offline/fake paths have no MCP tool transcript, so they emit an HONEST
    "transcript unavailable on this engine mode" — empty queries, ``captured=False`` — NOT
    a fabricated dead-engine of zeros and NEVER a faked score.
    """

    return RunTelemetry(engine_mode=engine_mode, captured=False)

__all__ = [
    "BrainQueryTrace",
    "RunTelemetry",
    "_capture_telemetry_from_messages",
    "_honest_empty_telemetry",
    "_parse_tool_result",
]
