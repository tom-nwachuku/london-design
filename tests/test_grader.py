"""Telemetry-capture tests for the in-session SDK message-loop tap (GRADE-01 / D-05).

The objective instrument: the transcript is ground truth, London's output is a claim.
These tests pin the CORRECTED Approach-A tap (RESEARCH Pitfall 1) — the one the spike
harness got wrong:

  * brain-query STRINGS arrive in ``AssistantMessage`` ``ToolUseBlock``s, and
  * the returned ``source-…`` IDs (the grader's ground truth) arrive in ``UserMessage``
    ``ToolResultBlock``s — NOT ``AssistantMessage``.

The two are correlated by ``ToolUseBlock.id == ToolResultBlock.tool_use_id``. A tap that
copied the harness verbatim (iterating only ``AssistantMessage``) would capture the query
strings but lose every source ID — a green-looking run with ``consulted_source_ids == []``
while ``brain_query_count > 0``. That is the bug, not a clean run; ``test_telemetry_does
_not_inherit_harness_bug`` asserts directly against it.

Everything here runs KEYLESS and OFFLINE: the synthetic SDK message stream is built from
the real ``claude_agent_sdk`` block classes (no live model, no network), and the
deterministic-path honesty matrix is exercised through ``FakeDirector``/``OfflineDirector``.
The full in-session capture (captured=True against a live host model) is the 5.3 /
human-UAT gate, exactly as 4.6's engine was verified.
"""

from __future__ import annotations

import copy as _copy
import json
from pathlib import Path as _Path

import pytest

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from london.director import (
    BrainQueryTrace,
    DirectionRequest,
    DirectionResult,
    FakeDirector,
    OfflineDirector,
    RunTelemetry,
    _capture_telemetry_from_messages,
)

# --- synthetic SDK message-stream builders (the corrected tap's exact shape) ----------


def _tool_result_payload(ids: list[str], count: int | None = None) -> str:
    """A brain ``london_brain_query`` result payload, JSON-encoded as the SDK delivers it.

    Mirrors ``london.brain_mcp.london_brain_query``'s return shape: ``{"query","count",
    "categories","findings":[{"id": ...}, ...]}``. The grader reads ``findings[].id``
    (the ``source-…`` IDs) and ``count`` — never the finding BODY.
    """

    findings = [{"id": sid} for sid in ids]
    return json.dumps(
        {
            "query": "tide tables ledger",
            "count": len(findings) if count is None else count,
            "categories": "all",
            "findings": findings,
        }
    )


def _synthetic_stream(*, query: str, tool_use_id: str, returned_ids: list[str], result_content):
    """Build an AssistantMessage(ToolUseBlock) + UserMessage(ToolResultBlock) + Result.

    ``result_content`` is what the ``ToolResultBlock`` carries (a JSON string, a list of
    text blocks, or a malformed value) so a single helper drives both the happy path and
    the defensive-parse case.
    """

    structured = _valid_direction_dict()
    return [
        AssistantMessage(
            content=[
                ToolUseBlock(
                    id=tool_use_id,
                    name="mcp__london-brain__london_brain_query",
                    input={"query": query},
                ),
            ],
            model="claude-test",
        ),
        UserMessage(
            content=[
                ToolResultBlock(
                    tool_use_id=tool_use_id,
                    content=result_content,
                    is_error=False,
                ),
            ],
        ),
        ResultMessage(
            subtype="success",
            duration_ms=4200,
            duration_api_ms=4000,
            is_error=False,
            num_turns=3,
            session_id="sess-test",
            structured_output=structured,
        ),
    ]


def _valid_direction_dict() -> dict:
    """A schema-valid DirectionResult dict (the FakeDirector's output, reused as the
    in-session structured_output) so the tap's DirectionResult half also round-trips."""

    request = DirectionRequest(
        brief={"title": "Tide Ledger", "text": "A maritime ledger for tide tables and harbor logs."},
        brain_findings={"research": [{"title": "Lloyd's ship registers as a typographic system"}]},
        product_tokens=["tide", "ledger", "harbor", "maritime"],
    )
    return FakeDirector().direct(request).model_dump()


def _request() -> DirectionRequest:
    return DirectionRequest(
        brief={"title": "Tide Ledger", "text": "A maritime ledger for tide tables and harbor logs."},
        product_tokens=["tide", "ledger", "harbor", "maritime"],
    )


# --- the corrected tap: source IDs come from the UserMessage branch -------------------


def test_telemetry_captures_source_ids():
    """The tap reads the returned source IDs from the UserMessage/ToolResultBlock branch.

    Proves the corrected Approach A: query string from AssistantMessage(ToolUseBlock),
    returned ``source-…`` IDs from UserMessage(ToolResultBlock), correlated by
    tool_use_id. If the tap only iterated AssistantMessage (the harness bug) the source
    IDs would be lost.
    """

    messages = _synthetic_stream(
        query="tide tables ledger",
        tool_use_id="tu_1",
        returned_ids=["source-aaaaaaaaaaaa", "source-bbbbbbbbbbbb"],
        result_content=_tool_result_payload(["source-aaaaaaaaaaaa", "source-bbbbbbbbbbbb"], count=3),
    )

    telemetry = _capture_telemetry_from_messages(messages, engine_mode="in_session")

    assert isinstance(telemetry, RunTelemetry)
    assert telemetry.captured is True
    assert telemetry.engine_mode == "in_session"
    assert telemetry.brain_query_count == 1
    # The whole point: the returned IDs are present (read from the UserMessage branch).
    assert telemetry.consulted_source_ids == ["source-aaaaaaaaaaaa", "source-bbbbbbbbbbbb"]
    # And the per-query trace carries the query string + its returned IDs + the count.
    assert len(telemetry.brain_queries) == 1
    trace = telemetry.brain_queries[0]
    assert isinstance(trace, BrainQueryTrace)
    assert trace.query == "tide tables ledger"
    assert trace.tool_use_id == "tu_1"
    assert trace.returned_source_ids == ["source-aaaaaaaaaaaa", "source-bbbbbbbbbbbb"]
    assert trace.result_count == 3


def test_telemetry_captures_source_ids_from_text_block_list_form():
    """ToolResultBlock.content may be a list of {"text": <json>} blocks — also captured."""

    payload = _tool_result_payload(["source-cccccccccccc"])
    messages = _synthetic_stream(
        query="harbor logs",
        tool_use_id="tu_2",
        returned_ids=["source-cccccccccccc"],
        result_content=[{"type": "text", "text": payload}],
    )

    telemetry = _capture_telemetry_from_messages(messages, engine_mode="in_session")

    assert telemetry.consulted_source_ids == ["source-cccccccccccc"]
    assert telemetry.brain_queries[0].returned_source_ids == ["source-cccccccccccc"]


def test_telemetry_does_not_inherit_harness_bug():
    """A run with brain_query_count>0 NEVER yields consulted_source_ids==[] when the
    brain returned results — the exact spike-harness latent bug, asserted against."""

    messages = _synthetic_stream(
        query="ledger grids",
        tool_use_id="tu_3",
        returned_ids=["source-dddddddddddd"],
        result_content=_tool_result_payload(["source-dddddddddddd"]),
    )

    telemetry = _capture_telemetry_from_messages(messages, engine_mode="in_session")

    # The bug condition: queries were made and results returned, but the IDs were lost.
    assert not (telemetry.brain_query_count > 0 and telemetry.consulted_source_ids == [])
    assert telemetry.brain_query_count == 1
    assert telemetry.consulted_source_ids == ["source-dddddddddddd"]


def test_malformed_tool_result_yields_empty_source_ids_no_crash():
    """A malformed/partial ToolResultBlock.content yields an empty source-ID list, never a
    crash (V5 input validation; T-05-06 DoS mitigation). The query is still recorded."""

    # Not valid JSON — defensive json.loads must swallow this.
    messages = _synthetic_stream(
        query="broken payload",
        tool_use_id="tu_4",
        returned_ids=[],
        result_content="{not: valid json at all",
    )

    telemetry = _capture_telemetry_from_messages(messages, engine_mode="in_session")

    assert telemetry.brain_query_count == 1
    assert telemetry.consulted_source_ids == []
    assert telemetry.brain_queries[0].query == "broken payload"
    assert telemetry.brain_queries[0].returned_source_ids == []


def test_malformed_tool_result_count_falls_back_no_crash():
    """A malformed ToolResultBlock ``count`` is untrusted input, never a telemetry crash."""

    messages = _synthetic_stream(
        query="untrusted count",
        tool_use_id="tu_5",
        returned_ids=["source-eeeeeeeeeeee", "source-ffffffffffff"],
        result_content=_tool_result_payload(
            ["source-eeeeeeeeeeee", "source-ffffffffffff"],
            count="lots",
        ),
    )

    telemetry = _capture_telemetry_from_messages(messages, engine_mode="in_session")

    assert telemetry.brain_query_count == 1
    assert telemetry.consulted_source_ids == ["source-eeeeeeeeeeee", "source-ffffffffffff"]
    assert telemetry.brain_queries[0].result_count == 2


def test_uncaptured_paths_are_honest():
    """FakeDirector and OfflineDirector emit honest captured=False telemetry — never a
    faked transcript, never a fabricated score (D-11 / T-05-08)."""

    request = _request()

    for director, expected_mode in (
        (FakeDirector(), "fake"),
        (OfflineDirector(), "offline"),
    ):
        direction, telemetry = director.direct_with_telemetry(request)

        assert isinstance(direction, DirectionResult)
        assert isinstance(telemetry, RunTelemetry)
        assert telemetry.captured is False, "deterministic paths must not fake a capture"
        assert telemetry.engine_mode == expected_mode
        # Honest empty: no fabricated queries, no fabricated source IDs.
        assert telemetry.brain_query_count == 0
        assert telemetry.brain_queries == []
        assert telemetry.consulted_source_ids == []


def test_telemetry_is_structurally_separate():
    """RunTelemetry is NOT an attribute of the returned DirectionResult (D-05): London
    does not grade his own homework. The two are returned as a structurally-separate
    tuple, never a fused model."""

    direction, telemetry = FakeDirector().direct_with_telemetry(_request())

    assert isinstance(direction, DirectionResult)
    assert isinstance(telemetry, RunTelemetry)
    # The instrument is a different object — never folded onto London's claims.
    assert direction is not telemetry
    assert not hasattr(direction, "telemetry")
    assert "telemetry" not in direction.model_dump()
    assert "run_telemetry" not in direction.model_dump()
    # And RunTelemetry never carries a DirectionResult (no reverse fusion either).
    assert "direction" not in telemetry.model_dump()


# =====================================================================================
# Plan 05-03 — the engine grader (GRADE-02 / HON-BF-01).  RED until grader.py exists.
# =====================================================================================
#
# The grader is the keystone honesty instrument: London does NOT grade his own homework.
# `RunTelemetry` (Plan 02) is the OBJECTIVE transcript = ground truth; the `DirectionResult`
# is a CLAIM. `grade(direction, telemetry) -> grader-block` produces objective inspectors,
# a show-verified-only claim-integrity audit (D-06), a transparent weighted composite (D-08),
# and a two-layer copy DATA shape (D-09). The whole point is that the grader can show a BAD
# run HONESTLY — a near-dead composite + a lit CLAIM_UNVERIFIED — so each test below pins one
# face of that honesty.
#
# Fixtures are capture-backed (the 5 real `direction_result` blocks = range evidence, all
# expected to score HIGH and CLAIM_OK) PLUS synthetic NEGATIVE controls that drive each
# inspector below its pass line. The captures are EVIDENCE OF RANGE, never templates: every
# expectation is derived from the fixture's own shape, never hard-coded to 5/6/7.
#
# CRITICAL id-form note (the Plan 02 → Plan 03 coordination): a real brain `findings[].id` is
# a 24-hex entry id, while London CITES the `source-{12hex}` form (`source_ref`). The grader's
# claim-integrity MUST compare like-for-like — `consulted_source_ids` carries the SAME
# `source-…` form London cites (the Plan 02 tap captures `source_ref` additively). These tests
# assert against the `source-…` form on both sides; a grader that audited two different ID
# namespaces would spuriously fire CLAIM_UNVERIFIED on every legit run.

_CAPTURES_DIR_GRADER = _Path(__file__).parents[1] / ".scratch" / "spike" / "captures"
_CAPTURE_NAMES_GRADER = ("website", "product", "brand", "app", "generic")


def _load_capture_direction_with_ref(name: str) -> dict:
    """Load a real capture's `direction_result`, supplying the honest `recommended_route_ref`.

    The 5 captures predate the D-04 split, so they carry `recommended_route` but no
    `recommended_route_ref`. We backfill the honest floor (`routes[0].title`) exactly as the
    deterministic directors do, so the fixture matches the widened contract WITHOUT inventing
    any creative value. Everything else (routes, palettes, conversation, cardinalities) is the
    REAL captured shape — range evidence, untouched.
    """

    if not _CAPTURES_DIR_GRADER.exists():
        pytest.skip("capture range-evidence (.scratch/spike/captures) is not shipped in public distributions")
    data = json.loads((_CAPTURES_DIR_GRADER / f"{name}.json").read_text(encoding="utf-8"))
    direction = data["direction_result"]
    direction.setdefault("recommended_route_ref", direction["routes"][0]["title"])
    return direction


@pytest.fixture
def grader_capture_directions() -> dict[str, dict]:
    """All 5 real captures' `direction_result` blocks, ref-backfilled (range evidence)."""

    return {name: _load_capture_direction_with_ref(name) for name in _CAPTURE_NAMES_GRADER}


def _captured_telemetry(*, query_count: int, source_ids: list[str] | None = None) -> RunTelemetry:
    """A `captured=True` in-session telemetry with N brain queries and a consulted-source set.

    `source_ids` is the order-preserving union of returned `source-…` IDs (the ground-truth
    consulted set). brain_total_entries is a realistic live denominator.
    """

    sids = source_ids or []
    traces = [
        BrainQueryTrace(
            query=f"adaptive brain query {i + 1}",
            tool_use_id=f"tu_{i + 1}",
            returned_source_ids=list(sids) if i == 0 else [],
            result_count=len(sids) if i == 0 else 0,
        )
        for i in range(query_count)
    ]
    return RunTelemetry(
        engine_mode="in_session",
        brain_query_count=query_count,
        brain_queries=traces,
        consulted_source_ids=list(sids),
        brain_total_entries=3439,
        tool_call_count=query_count + 4,
        duration_ms=4200,
        captured=True,
    )


def _confabulated_direction(base: dict) -> dict:
    """Clone a real capture and embed a `source-deadbeef0000` NOT in any transcript.

    The synthetic confabulated source is a 12-hex `source-…` token (the form London cites),
    planted in a prose field. The grader must drop it from grounded AND light CLAIM_UNVERIFIED
    — without raising. The base capture itself is CLEAN (all 5 carry no machine citations), so
    this is a SYNTHETIC over-claim, never derived from a real capture.
    """

    direction = _copy.deepcopy(base)
    direction["london_reframe"] = (
        direction.get("london_reframe", "")
        + " As source-deadbeef0000 from the brain attests, this lane is uncontested."
    )
    return direction


def _near_palette_direction(base: dict) -> dict:
    """Clone a real capture and force its two routes onto a perceptually-NEAR palette.

    The two palettes share NO exact hex (each B colour is a tiny nudge off its A twin) yet are
    perceptually almost identical — the exact "one idea in two outfits" case (avg-nearest ΔE ≈ 6,
    far below the threshold AND far below any real capture's ≥38.8). Exact-hex distinctness would
    never fire here (Pitfall 6: zero exact-hex overlap); the perceptual ΔE referee MUST.
    """

    direction = _copy.deepcopy(base)
    near_a = ["#b8332b", "#ebe3d2", "#2c2a28", "#9a8f7d", "#c9b89a"]
    near_b = ["#bb352d", "#e9e1d0", "#2e2c2a", "#988d7b", "#c7b698"]
    for route, hexes in zip(direction["routes"], (near_a, near_b)):
        route["palette"] = [
            {"role": f"role{i}", "name": f"Near {i}", "hex": h} for i, h in enumerate(hexes)
        ]
    # Give the two routes near-identical, heavily-overlapping titles too (title-token Jaccard
    # high) so BOTH distinctness sub-checks fail — not just the palette.
    direction["routes"][0]["title"] = "The Heirloom Register Almanac"
    direction["routes"][1]["title"] = "The Heirloom Register Annual"
    direction.setdefault("recommended_route_ref", direction["routes"][0]["title"])
    direction["recommended_route_ref"] = direction["routes"][0]["title"]
    return direction


def _two_route_palette_direction(palette_a: list[dict], palette_b: list[dict]) -> dict:
    return {
        "routes": [
            {
                "title": "Route Alpha",
                "palette": palette_a,
            },
            {
                "title": "Route Beta",
                "palette": palette_b,
            },
        ],
        "conversation": [{"gate": "one", "decision": "A concrete read."}],
        "copy_blocks": [{"text": "A real copy block."}],
        "next_steps": ["Make the route visible."],
        "route_comparison": [{"summary": "Alpha and Beta diverge."}],
        "font_options": [
            {"options": [{}, {}, {}]},
            {"options": [{}, {}, {}]},
        ],
    }


def _empty_palette_direction() -> dict:
    return _two_route_palette_direction([], [])


def _malformed_palette_direction() -> dict:
    palette = [{"role": "base", "name": "White", "hex": "#fff"}]
    return _two_route_palette_direction(palette, palette)


def _single_route_direction() -> dict:
    direction = _empty_palette_direction()
    direction["routes"] = direction["routes"][:1]
    direction["font_options"] = direction["font_options"][:1]
    return direction


def _incomplete_manifest_direction(base: dict) -> dict:
    """Clone a real capture and starve one route's font lab to 2 tiers (incomplete manifest)."""

    direction = _copy.deepcopy(base)
    # font_options is one group per route; trim the FIRST group to 2 options (< the required 3).
    if direction.get("font_options"):
        direction["font_options"][0]["options"] = direction["font_options"][0]["options"][:2]
    return direction


def _local_font_biased_direction(base: dict) -> dict:
    """Clone a capture and make every route present the same local font as the whole lab.

    This preserves the manifest's "3 font options per route" shape, so the new Type Selection
    Referee is the check that must catch the bias. Local proof is allowed; making it the entire
    taste pool is not.
    """

    direction = _copy.deepcopy(base)
    for group in direction.get("font_options") or []:
        route_title = group.get("route_title") or "route"
        group["options"] = [
            {
                "tier": "safe_local",
                "name": "Proof Sans local fallback",
                "headline_font": "Proof Sans",
                "body_font": "Proof Sans",
                "label_font": "Proof Sans",
                "fallback_stack": "Proof Sans, system-ui, sans-serif",
                "best_use": "Convenient local proof",
                "why_london_chose_it": "It is the local font already available in the operator pack.",
                "why_this_route_not_other_route": f"It is reused for {route_title} because it is locally installed.",
                "what_makes_it_wrong": "It collapses type exploration into availability.",
                "import_hint": "",
                "font_preview": {
                    "status": "actual_loaded",
                    "delivery": "local_asset",
                    "rendered_family": "Proof Sans",
                    "source_label": "Local operator shelf",
                    "license_note": "Approved local test asset.",
                    "asset_href": "assets/fonts/proof-sans.woff2",
                },
            }
            for _ in range(3)
        ]
    return direction


def _font_option(
    tier: str,
    family: str,
    *,
    route_title: str,
    fallback_stack: str | None = None,
    preview: dict | None = None,
) -> dict:
    return {
        "tier": tier,
        "name": family,
        "headline_font": family,
        "body_font": family,
        "label_font": family,
        "fallback_stack": fallback_stack or f'"{family}", system-ui, sans-serif',
        "best_use": f"{family} supports the {route_title} route with a specific type voice.",
        "why_london_chose_it": (
            f"{family} gives {route_title} a sourceable typographic stance rather than a default local convenience."
        ),
        "why_this_route_not_other_route": (
            f"{route_title} needs {family}'s rhythm; the other routes ask for a different type behavior."
        ),
        "what_makes_it_wrong": "Wrong if it becomes the whole shelf instead of one deliberate route choice.",
        "import_hint": "",
        **({"font_preview": preview} if preview else {}),
    }


def _replace_font_lab(base: dict, per_route_options: list[list[dict]]) -> dict:
    direction = _copy.deepcopy(base)
    groups = direction.get("font_options") or []
    for group, options in zip(groups, per_route_options, strict=False):
        group["options"] = options
    return direction


def _route_titles(base: dict) -> list[str]:
    return [
        group.get("route_title") or f"Route {index + 1}"
        for index, group in enumerate(base.get("font_options") or [])
    ]


# --- claim integrity (D-06): show-verified-only + a visible flag, never a hard-fail --------


def test_confabulated_source_flags(grader_capture_directions):
    """A cited source NOT in the transcript is dropped from grounded AND lights
    CLAIM_UNVERIFIED — and `grade(...)` does NOT raise (the run never hard-fails)."""

    from london import grader

    base = grader_capture_directions["website"]
    direction = _confabulated_direction(base)
    # The transcript consulted real `source-…` refs — but NOT the confabulated one.
    telemetry = _captured_telemetry(
        query_count=9, source_ids=["source-24014dd14bfb", "source-b6406629cb4c"]
    )

    block = grader.grade(direction, telemetry)  # must NOT raise

    audit = block["audit"] if isinstance(block.get("audit"), dict) else _find_audit(block)
    assert "source-deadbeef0000" in audit["claim_unverified"]
    assert "source-deadbeef0000" not in audit["grounded_source_ids"]
    assert audit["verdict"] == "CLAIM_UNVERIFIED"


def test_clean_captures_are_claim_ok(grader_capture_directions):
    """All 5 real captures cite NO machine source IDs → the cited set is empty → CLAIM_OK
    vacuously (RESEARCH A3). The show-verified-only policy degrades safely to "nothing
    claimed, nothing to flag" — it never invents an over-claim on a clean run."""

    from london import grader

    for name, direction in grader_capture_directions.items():
        telemetry = _captured_telemetry(query_count=9, source_ids=["source-24014dd14bfb"])
        block = grader.grade(direction, telemetry)
        audit = _find_audit(block)
        assert audit["verdict"] == "CLAIM_OK", f"{name} should be CLAIM_OK (no machine citations)"
        assert audit["claim_unverified"] == []


def _find_audit(block: dict) -> dict:
    """The grader block's claim-integrity audit (grounded_source_ids/claim_unverified/verdict)."""

    audit = block.get("audit")
    assert isinstance(audit, dict), "grader block must carry a claim-integrity `audit` mapping"
    return audit


# --- distinctness (Q2): perceptual ΔE, NOT exact-hex --------------------------------------


def test_distinctness_metric(grader_capture_directions):
    """The near-palette synthetic FAILS distinctness; all 5 real captures PASS it."""

    from london import grader

    telemetry = _captured_telemetry(query_count=9)

    # All 5 real captures: routes are perceptually far apart → distinctness passes (sub-score 1).
    for name, direction in grader_capture_directions.items():
        block = grader.grade(direction, telemetry)
        sub = block["composite"]["sub_scores"]["distinctness"]
        assert sub >= 0.99, f"{name}: real-capture routes must read as distinct (got {sub})"

    # The near-palette synthetic: perceptually-close palettes + overlapping titles → fails.
    near = _near_palette_direction(grader_capture_directions["brand"])
    near_block = grader.grade(near, telemetry)
    near_sub = near_block["composite"]["sub_scores"]["distinctness"]
    assert near_sub < 1.0, "near-palette routes must FAIL distinctness (one idea, two outfits)"


def test_distinctness_not_exact_hex(grader_capture_directions):
    """A route pair with ZERO exact-hex overlap but perceptually-near colors STILL fails
    distinctness — proving the referee is perceptual (redmean ΔE), not an exact-match that
    would never fire (Pitfall 6: all 5 captures have zero exact-hex overlap)."""

    from london import grader

    near = _near_palette_direction(grader_capture_directions["website"])
    # Assert the precondition the test depends on: the two palettes share NO exact hex.
    hexes_a = {c["hex"].lower() for c in near["routes"][0]["palette"]}
    hexes_b = {c["hex"].lower() for c in near["routes"][1]["palette"]}
    assert hexes_a.isdisjoint(hexes_b), "fixture must have zero exact-hex overlap"

    block = grader.grade(near, _captured_telemetry(query_count=9))
    assert block["composite"]["sub_scores"]["distinctness"] < 1.0


def test_empty_palette_distinctness_strict_json_null():
    """Empty palettes are unmeasurable n/a, never Infinity or an auto-pass."""

    from london import grader

    block = grader.grade(_empty_palette_direction(), _captured_telemetry(query_count=9))
    distinctness = _inspector(block, "distinctness")

    assert distinctness["verdict"] == "UNMEASURABLE"
    assert distinctness["score"] == "n/a"
    assert distinctness["min_palette_de"] is None
    json.loads(json.dumps(block, allow_nan=False))


def test_malformed_palette_distinctness_is_unmeasurable_not_distinct():
    """Malformed shorthand colours are n/a, not a fabricated DISTINCT verdict."""

    from london import grader

    block = grader.grade(_malformed_palette_direction(), _captured_telemetry(query_count=9))
    distinctness = _inspector(block, "distinctness")

    assert distinctness["verdict"] == "UNMEASURABLE"
    assert distinctness["score"] == "n/a"
    assert distinctness["min_palette_de"] is None


def test_single_route_distinctness_is_not_applicable():
    """A 0-pair route set should not receive a fake distinctness pass."""

    from london import grader

    block = grader.grade(_single_route_direction(), _captured_telemetry(query_count=9))
    distinctness = _inspector(block, "distinctness")

    assert distinctness["verdict"] == "NOT_APPLICABLE"
    assert distinctness["score"] == "n/a"
    assert "Only one route" in distinctness["detail"]


# --- composite (Q3): a dead/confabulated run scores visibly LOW; a clean run scores HIGH ---


def test_composite_low_for_dead_run(grader_capture_directions):
    """A 1-brain-call + confabulated-source + near-palette + incomplete-manifest run scores
    visibly LOW (< ~35, the worked ~27 example); a clean capture scores HIGH (> 90)."""

    from london import grader

    # Clean run: a real capture with a healthy ~9-query transcript → composite > 90.
    clean = grader_capture_directions["website"]
    clean_block = grader.grade(clean, _captured_telemetry(query_count=9, source_ids=["source-24014dd14bfb"]))
    assert clean_block["composite"]["score"] > 90, "a clean run must score high"

    # Dead/bad run: stack every failing signal — 1 brain call, a confabulated source, a near
    # palette, AND an incomplete font manifest — on a captured=True (dead-engine) transcript.
    bad = _incomplete_manifest_direction(
        _near_palette_direction(_confabulated_direction(grader_capture_directions["website"]))
    )
    bad_telemetry = _captured_telemetry(query_count=1, source_ids=["source-aaaaaaaaaaaa"])
    bad_block = grader.grade(bad, bad_telemetry)
    assert bad_block["composite"]["score"] < 35, "a dead/confabulated run must score visibly LOW"
    # And the bad run is honestly flagged.
    assert _find_audit(bad_block)["verdict"] == "CLAIM_UNVERIFIED"


def test_dead_engine_zero_calls_scores_low(grader_capture_directions):
    """A captured=True run with brain_query_count=0 (a real dead engine) scores its grounding
    at 0 and is visibly low — DISTINCT from a captured=False unavailable transcript."""

    from london import grader

    direction = grader_capture_directions["product"]
    dead = _captured_telemetry(query_count=0, source_ids=[])
    block = grader.grade(direction, dead)
    assert block["composite"]["sub_scores"]["grounding"] == 0.0
    # grounding is 30% of the composite, so a 0-call run is meaningfully penalized.
    assert block["composite"]["score"] < 75


# --- captured=False renders n/a, NOT 0 (Pitfall 2) ----------------------------------------


def test_uncaptured_renders_na(grader_capture_directions):
    """`captured=False` (keyed/offline/fake) renders grounding "n/a", NOT 0 — an honest
    "telemetry unavailable", DISTINCT from a captured-but-zero dead engine."""

    from london import grader

    direction = grader_capture_directions["app"]
    uncaptured = RunTelemetry(engine_mode="offline", captured=False)
    block = grader.grade(direction, uncaptured)

    grounding = block["composite"]["sub_scores"]["grounding"]
    assert grounding == "n/a", "captured=False grounding must be 'n/a', never 0"
    # The composite itself is honest about the unavailable transcript (not a fabricated score).
    assert block["composite"].get("telemetry_available") is False
    # The grounding inspector verdict says the transcript is unavailable, not "dead".
    grounding_inspector = _inspector(block, "grounding")
    assert grounding_inspector["score"] == "n/a"


def test_uncaptured_source_auditor_does_not_fabricate_unverified_claim(grader_capture_directions):
    """Without captured telemetry the source auditor says unavailable, not CLAIM_UNVERIFIED."""

    from london import grader

    direction = _confabulated_direction(grader_capture_directions["app"])
    block = grader.grade(direction, RunTelemetry(engine_mode="offline", captured=False))
    source_auditor = _inspector(block, "source")
    rendered = json.dumps(block, sort_keys=True)

    assert source_auditor["verdict"] == "TELEMETRY_UNAVAILABLE"
    assert source_auditor["score"] == "n/a"
    assert "CLAIM_UNVERIFIED" not in rendered


def _inspector(block: dict, key: str) -> dict:
    """Find an inspector verdict by its lowercase key/name fragment."""

    inspectors = block.get("inspectors")
    assert isinstance(inspectors, list) and inspectors, "grader block must carry inspectors"
    for ins in inspectors:
        name = (ins.get("key") or ins.get("name") or "").lower()
        if key in name:
            return ins
    raise AssertionError(f"no inspector matching {key!r} in {[i.get('name') for i in inspectors]}")


def test_named_inspectors_include_type_selection_referee(grader_capture_directions):
    """The roster includes the objective inspectors plus the Type Selection Referee.

    The list is open (render count=len), so this pins presence rather than a fixed 4-slot UI.
    """

    from london import grader

    block = grader.grade(grader_capture_directions["brand"], _captured_telemetry(query_count=9))
    inspectors = block["inspectors"]
    assert len(inspectors) >= 5
    names = " ".join((i.get("name") or "").lower() for i in inspectors)
    for token in ("source", "grounding", "distinct", "manifest", "type"):
        assert token in names, f"missing inspector for {token!r}"
    # Each inspector carries a name, an objective dimension description, a score, and a verdict
    # — the colophon (5.1 Surface 4) reads exactly these keys.
    for ins in inspectors:
        assert ins.get("name")
        assert ins.get("dimension")
        assert "score" in ins
        assert ins.get("verdict")


def test_type_selection_referee_flags_local_font_bias(grader_capture_directions):
    """A route set can satisfy font cardinality and still fail type range.

    This catches the Phase-8/visual-fidelity risk: London may use an actual-loaded local font,
    but if every route option collapses to that local font, the grader lights the backup guard.
    """

    from london import grader

    direction = _local_font_biased_direction(grader_capture_directions["product"])
    block = grader.grade(direction, _captured_telemetry(query_count=9))
    inspector = _inspector(block, "type_selection")

    assert inspector["verdict"] == "LOCAL_FONT_BIAS"
    assert inspector["score"] < 0.75
    assert block["composite"]["sub_scores"]["type_selection"] == inspector["score"]
    assert any("local font lanes dominate" in item for item in inspector["missing_range"])


def test_type_selection_referee_allows_bundled_font_plus_open_reference_range(grader_capture_directions):
    """One bundled actual-loaded font is proof, not bias, when the rest of the range remains open."""

    from london import grader

    base = grader_capture_directions["product"]
    options_by_route: list[list[dict]] = []
    for index, route_title in enumerate(_route_titles(base)):
        preview = None
        if index == 0:
            preview = {
                "status": "actual_loaded",
                "delivery": "local_asset",
                "rendered_family": "Familjen Grotesk",
                "source_label": "Fontshare (SIL Open Font License 1.1)",
                "license_note": "Bundled London Type Shelf asset; SHA-256: 5589983a201d1b0b77b55f8c299a4753cff515e86536c4761446a4dd6705a80b.",
                "asset_href": "assets/fonts/familjen-grotesk-500.woff2",
                "source_kind": "bundled_open",
                "shelf_id": "familjen-grotesk",
                "asset_sha256": "5589983a201d1b0b77b55f8c299a4753cff515e86536c4761446a4dd6705a80b",
            }
        options_by_route.append(
            [
                _font_option("safe_local", "System UI", route_title=route_title, fallback_stack="system-ui, sans-serif"),
                _font_option("open_public", "Familjen Grotesk" if index == 0 else "Sora", route_title=route_title, preview=preview),
                _font_option("premium_inspiration", "Maison Neue", route_title=route_title),
            ]
        )
    direction = _replace_font_lab(base, options_by_route)
    block = grader.grade(direction, _captured_telemetry(query_count=9))
    inspector = _inspector(block, "type_selection")

    assert inspector["verdict"] != "LOCAL_FONT_BIAS"
    assert inspector["actual_loaded_unverified"] == 0
    assert not any("actual_loaded font preview lacks" in item for item in inspector["missing_range"])


def test_type_selection_referee_ignores_generic_fallback_stack_tails(grader_capture_directions):
    """Generic CSS tails should not count as dominance when a real first family is present."""

    from london import grader

    base = grader_capture_directions["brand"]
    options_by_route = [
        [
            _font_option("safe_local", "Space Grotesk", route_title=route_title),
            _font_option("open_public", "Fraunces", route_title=route_title),
            _font_option("premium_inspiration", "GT America", route_title=route_title),
        ]
        for route_title in _route_titles(base)
    ]
    direction = _replace_font_lab(base, options_by_route)
    block = grader.grade(direction, _captured_telemetry(query_count=9))
    inspector = _inspector(block, "type_selection")

    assert inspector["generic_default_hits"] == 0
    assert not any("generic/system default" in item for item in inspector["missing_range"])


def test_type_selection_referee_allows_repeated_brand_system_with_rationale(grader_capture_directions):
    """A repeated brand-system family can be thin, but it is not automatically local bias."""

    from london import grader

    base = grader_capture_directions["app"]
    options_by_route = [
        [
            _font_option("safe_local", "Signal Sans", route_title=route_title),
            _font_option("open_public", "Signal Sans", route_title=route_title),
            _font_option("premium_inspiration", "Signal Sans", route_title=route_title),
        ]
        for route_title in _route_titles(base)
    ]
    direction = _replace_font_lab(base, options_by_route)
    block = grader.grade(direction, _captured_telemetry(query_count=9))
    inspector = _inspector(block, "type_selection")

    assert inspector["verdict"] != "LOCAL_FONT_BIAS"
    assert inspector["score"] >= 0.75


def test_type_selection_referee_flags_unproved_actual_loaded_claim(grader_capture_directions):
    """An actual_loaded label without shelf/user-local source + license + asset proof is not proof."""

    from london import grader

    base = grader_capture_directions["website"]
    route_title = _route_titles(base)[0]
    direction = _replace_font_lab(
        base,
        [
            [
                _font_option(
                    "open_public",
                    "Mystery Sans",
                    route_title=route_title,
                    preview={
                        "status": "actual_loaded",
                        "delivery": "local_asset",
                        "rendered_family": "Mystery Sans",
                        "asset_href": "assets/fonts/mystery-sans.woff2",
                    },
                ),
                _font_option("safe_local", "Space Grotesk", route_title=route_title),
                _font_option("premium_inspiration", "Suisse", route_title=route_title),
            ]
        ],
    )
    block = grader.grade(direction, _captured_telemetry(query_count=9))
    inspector = _inspector(block, "type_selection")

    assert inspector["actual_loaded_unverified"] == 1
    assert any("actual_loaded font preview lacks" in item for item in inspector["missing_range"])


# --- receipts scrubbed: query strings + source-… IDs + counts ONLY (no bodies, no paths) ---


def test_grader_receipts_scrubbed(grader_capture_directions):
    """The grader block carries ONLY query strings + `source-…` IDs + counts — never a raw
    `findings[].body`, never a `/Users/`-style local path, never a secret (HON-BF-01)."""

    from london import grader

    telemetry = _captured_telemetry(query_count=9, source_ids=["source-24014dd14bfb", "source-b6406629cb4c"])
    block = grader.grade(grader_capture_directions["website"], telemetry)

    blob = json.dumps(block)
    # No raw brain body markers / local paths / secrets in the grader block.
    assert "body" not in {k for k in _all_keys(block)}, "grader block must not carry a `body` key"
    assert "/Users/" not in blob
    assert "/private/" not in blob
    assert "/tmp/" not in blob
    assert "sk-" not in blob
    assert "ANTHROPIC" not in blob
    # It SHOULD carry the public-safe receipts: query strings + source-… IDs + counts.
    assert "source-24014dd14bfb" in blob
    assert "adaptive brain query 1" in blob


def _all_keys(obj) -> set:
    """Every mapping key reachable in a nested structure (for the no-`body`-key assertion)."""

    keys: set = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            keys.add(k)
            keys |= _all_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            keys |= _all_keys(v)
    return keys


# --- two-layer copy (D-09): a HEADLINE layer + a collapsible DETAIL layer, as DATA ---------


def test_two_layer_copy_shape(grader_capture_directions):
    """The grader block exposes a HEADLINE layer (humanized one-line verdicts + the hero
    number) AND a collapsible DETAIL layer (raw telemetry: query trace + source IDs + sub-score
    math), as DISTINCT data keys — progressive disclosure expressed as a DATA shape, not CSS."""

    from london import grader

    telemetry = _captured_telemetry(query_count=9, source_ids=["source-24014dd14bfb"])
    block = grader.grade(grader_capture_directions["product"], telemetry)

    assert isinstance(block.get("headline"), dict), "missing humanized HEADLINE layer"
    assert isinstance(block.get("detail"), dict), "missing collapsible DETAIL layer"
    headline, detail = block["headline"], block["detail"]

    # Headline: a friendly hero number + one-line per-inspector verdicts (understandable copy).
    assert "score" in headline or "summary" in headline
    assert headline.get("inspectors") or headline.get("verdicts")

    # Detail: the raw, developer-grade audit — the query trace + the consulted source IDs + the
    # sub-score math. These are the closer-to-real-output fields collapsed by default in 5.1.
    detail_blob = json.dumps(detail)
    assert "source-24014dd14bfb" in detail_blob, "detail layer must carry the raw source IDs"
    assert "adaptive brain query 1" in detail_blob, "detail layer must carry the query trace"
    # The two layers are DISTINCT keys (not the same object) — progressive disclosure as data.
    assert headline is not detail
