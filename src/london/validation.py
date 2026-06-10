"""Cross-brief chassis validation for London's variable-shape output.

The real captures in ``.scratch/spike/captures`` are evidence of London's range,
not templates to reproduce. This module adapts those captures into the current
pack/render path, then adds synthetic edge cases only where the captures do not
exercise a schema-legal axis (for example zero/12 telemetry receipts and an
8-decision conversation).
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from london import grader
from london.assets import normalize_palette, slugify
from london.director import BrainQueryTrace, RunTelemetry
from london.persona import scrub_pack
from london.render import escape as render_escape
from london.render import _public_handoff_text
from london.render import render_dossier
from london.session import ARTIFACT_RESOLUTION_KEY, DIRECTION_RESULT_KEY, run_london_session
from london.workbench import enrich_workbench_pack

CAPTURE_NAMES: tuple[str, ...] = ("website", "app", "product", "brand", "generic")
DEFAULT_CAPTURES_DIR = Path(__file__).resolve().parents[2] / ".scratch" / "spike" / "captures"


def resolve_captures_dir(captures_dir: Path | None = None) -> Path:
    """Resolve the validation captures without pretending they ship in wheels."""

    if captures_dir is None:
        if DEFAULT_CAPTURES_DIR.is_dir():
            return DEFAULT_CAPTURES_DIR
        raise FileNotFoundError(
            "London chassis validation uses repo-local Phase-4.6 captures that are excluded "
            "from built packages; run from a source checkout or pass --captures-dir."
        )
    resolved = Path(captures_dir)
    if not resolved.is_dir():
        raise FileNotFoundError(f"Capture directory does not exist: {resolved}")
    return resolved


@dataclass(frozen=True)
class ChassisScenario:
    """One validation input: either a real capture or a synthetic stress case."""

    name: str
    kind: str
    brief: str
    direction: dict[str, Any]
    telemetry_query_count: int
    telemetry_source_count: int
    note: str
    raw_capture_query_count: int | None = None


def load_capture(name: str, *, captures_dir: Path | None = None) -> dict[str, Any]:
    """Load one sanitized Phase-4.6 capture by name."""

    path = resolve_captures_dir(captures_dir) / f"{name}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    direction = data.get("direction_result")
    if not isinstance(direction, dict):
        raise ValueError(f"{path} has no direction_result object")
    brief = data.get("brief")
    if not isinstance(brief, str) or not brief.strip():
        raise ValueError(f"{path} has no brief string")
    return data


def build_scenarios(*, captures_dir: Path | None = None) -> list[ChassisScenario]:
    """Return all real captures plus synthetic range-edge stress scenarios."""

    scenarios: list[ChassisScenario] = []
    resolved_captures_dir = resolve_captures_dir(captures_dir)
    captures = {name: load_capture(name, captures_dir=resolved_captures_dir) for name in CAPTURE_NAMES}
    for name in CAPTURE_NAMES:
        capture = captures[name]
        direction = _adapt_direction(capture["direction_result"])
        raw_queries = _capture_queries(capture, include_select=True)
        queries = _capture_queries(capture)
        scenarios.append(
            ChassisScenario(
                name=f"capture-{name}",
                kind="capture",
                brief=capture["brief"],
                direction=direction,
                telemetry_query_count=len(queries),
                telemetry_source_count=0,
                raw_capture_query_count=len(raw_queries),
                note="real capture adapted with a validation-only recommended_route_ref",
            )
        )

    # Synthetic by necessity: no capture has N=8, but the live schema/renderer must
    # support it because the conversation is no longer a fixed seven-gate cage.
    n8_direction = _adapt_direction(captures["product"]["direction_result"])
    n8_direction["conversation"] = [
        {
            "gate": f"Stress decision {index}",
            "decision": f"London decision {index} is present and self-labeled.",
            "rationale": f"Reason {index} stays attached to the decision.",
            "critique": f"Risk {index} remains optional content.",
            "answer": f"Resolution {index}.",
        }
        for index in range(1, 9)
    ]
    scenarios.append(
        ChassisScenario(
            name="stress-conversation-8",
            kind="stress",
            brief=captures["product"]["brief"],
            direction=n8_direction,
            telemetry_query_count=8,
            telemetry_source_count=0,
            note="synthetic N=8 conversation beyond the observed 3..7 capture range",
        )
    )

    # Synthetic by necessity: the observed 8-swatch lane palette is not a route palette,
    # and the route palette is what the current display renders.
    palette8_direction = _adapt_direction(captures["website"]["direction_result"])
    if palette8_direction.get("palette") and palette8_direction.get("routes"):
        palette8_direction["routes"][0]["palette"] = copy.deepcopy(palette8_direction["palette"])
    scenarios.append(
        ChassisScenario(
            name="stress-route-palette-8",
            kind="stress",
            brief=captures["website"]["brief"],
            direction=palette8_direction,
            telemetry_query_count=8,
            telemetry_source_count=0,
            note="synthetic route-level 8-swatch palette from the real website lane palette",
        )
    )

    receipt0_direction = _adapt_direction(captures["brand"]["direction_result"])
    scenarios.append(
        ChassisScenario(
            name="stress-receipts-0",
            kind="stress",
            brief=captures["brand"]["brief"],
            direction=receipt0_direction,
            telemetry_query_count=0,
            telemetry_source_count=0,
            note="synthetic zero-receipt telemetry floor",
        )
    )

    receipt12_direction = _adapt_direction(captures["website"]["direction_result"])
    scenarios.append(
        ChassisScenario(
            name="stress-receipts-12",
            kind="stress",
            brief=captures["website"]["brief"],
            direction=receipt12_direction,
            telemetry_query_count=12,
            telemetry_source_count=12,
            note="synthetic twelve-receipt telemetry ceiling for the display rail",
        )
    )

    return scenarios


def run_chassis_validation(
    *,
    captures_dir: Path | None = None,
    write_html_dir: Path | None = None,
) -> dict[str, Any]:
    """Render every validation scenario and return a JSON-serializable report."""

    results: list[dict[str, Any]] = []
    for scenario in build_scenarios(captures_dir=captures_dir):
        pack = build_pack_for_scenario(scenario)
        html = render_dossier(pack)
        checks = validate_rendered_html(pack, html, scenario)
        if write_html_dir is not None:
            write_html_dir.mkdir(parents=True, exist_ok=True)
            (write_html_dir / f"{scenario.name}.html").write_text(html, encoding="utf-8")
        results.append(
            {
                "name": scenario.name,
                "kind": scenario.kind,
                "note": scenario.note,
                "conversation_count": len(_as_mappings(pack.get("conversation"))),
                "recommendation_length": len(str(pack.get("recommended_route") or "")),
                "route_palette_counts": [
                    len(normalize_palette(route.get("palette")))
                    for route in _as_mappings(pack.get("routes"))
                ],
                "brain_query_receipts": scenario.telemetry_query_count,
                "consulted_source_receipts": scenario.telemetry_source_count,
                "raw_capture_query_count": scenario.raw_capture_query_count,
                "html_bytes": len(html.encode("utf-8")),
                "checks": checks,
                "ok": all(check["ok"] for check in checks),
            }
        )

    return {
        "ok": all(result["ok"] for result in results),
        "capture_count": len([result for result in results if result["kind"] == "capture"]),
        "scenario_count": len(results),
        "ranges": {
            "conversation_counts": sorted({result["conversation_count"] for result in results}),
            "recommendation_lengths": sorted({result["recommendation_length"] for result in results}),
            "route_palette_counts": sorted(
                {
                    count
                    for result in results
                    for count in result["route_palette_counts"]
                }
            ),
            "brain_query_receipts": sorted({result["brain_query_receipts"] for result in results}),
            "consulted_source_receipts": sorted({result["consulted_source_receipts"] for result in results}),
        },
        "scenarios": results,
    }


def build_pack_for_scenario(scenario: ChassisScenario) -> dict[str, Any]:
    """Adapt one scenario into a complete pack and run the normal workbench layer."""

    pack = run_london_session(
        scenario.brief,
        artifact_type=str(scenario.direction.get("artifact_type") or "generic"),
    )
    direction = copy.deepcopy(scenario.direction)
    brief_record = pack["brief"]

    pack["routes"] = _routes_from_direction(direction, brief_record)
    pack["recommended_route_ref"] = direction["recommended_route_ref"]
    pack["recommended_route"] = str(direction.get("recommended_route") or "")
    pack["artifact_type"] = str(direction.get("artifact_type") or "generic")
    pack["category_assumption"] = str(direction.get("category_assumption") or "")
    pack["aesthetic_void"] = str(direction.get("aesthetic_void") or "")
    pack["london_reframe"] = str(direction.get("london_reframe") or "")
    pack["vessel_interface_expression"] = str(direction.get("vessel_expression") or "")
    pack["recurring_loop"] = str(direction.get("recurring_loop") or "")
    pack["unboxing_first_moment"] = str(direction.get("unboxing") or "")
    pack["anti_position"] = str(direction.get("anti_position") or "")
    pack["research"]["audience"] = str(direction.get("audience") or pack["research"].get("audience") or "")
    pack["research"]["category_tension"] = str(direction.get("aesthetic_void") or "")
    pack["creative_direction"]["positioning"] = str(direction.get("london_reframe") or "")
    pack["creative_direction"]["voice"] = str(direction.get("voice") or "")
    pack["creative_direction"]["concept_routes"] = [route["title"] for route in pack["routes"]]
    pack["typography_color"]["type_system"] = str(direction.get("type_system") or "")
    pack["typography_color"]["color_system"] = str(direction.get("color_system") or "")
    pack[DIRECTION_RESULT_KEY] = direction
    enrich_workbench_pack(pack)
    pack["grader"] = grader.grade(direction, _telemetry_for_scenario(scenario))
    pack.pop(ARTIFACT_RESOLUTION_KEY, None)
    scrub_pack(pack)
    return pack


def validate_rendered_html(
    pack: Mapping[str, Any],
    html: str,
    scenario: ChassisScenario,
) -> list[dict[str, Any]]:
    """Return named checks proving the rendered chassis did not pad or clip."""

    checks: list[dict[str, Any]] = []
    conversation = _as_mappings(pack.get("conversation"))
    recommendation = str(pack.get("recommended_route") or "")
    routes = _as_mappings(pack.get("routes"))
    expected_route_swatches = sum(len(normalize_palette(route.get("palette"))) for route in routes)

    conversation_section = _section_html(html, "conversation")
    decision_cards = conversation_section.count('class="decision-card"')
    checks.append(
        _check(
            "conversation-count",
            decision_cards == len(conversation),
            expected=len(conversation),
            actual=decision_cards,
        )
    )
    for entry in conversation:
        decision = str(entry.get("decision") or "")
        if decision:
            rendered_decision = render_escape(_public_handoff_text(decision))
            checks.append(
                _check(
                    "conversation-decision-present",
                    rendered_decision in conversation_section,
                    expected=decision[:80],
                    actual="present" if rendered_decision in conversation_section else "missing",
                )
            )

    recommendation_panel = _class_section_html(html, "recommendation-panel")
    if recommendation:
        rendered_recommendation = render_escape(recommendation)
        checks.append(
            _check(
                "recommendation-verbatim",
                rendered_recommendation in recommendation_panel,
                expected=len(recommendation),
                actual="present" if rendered_recommendation in recommendation_panel else "missing",
            )
        )
        checks.append(
            _check(
                "recommendation-not-ellipsized",
                "…" not in recommendation_panel and "&hellip;" not in recommendation_panel,
                expected="no ellipsis",
                actual="ellipsis" if ("…" in recommendation_panel or "&hellip;" in recommendation_panel) else "none",
            )
        )
    else:
        checks.append(
            _check(
                "recommendation-honest-empty",
                "recommendation-prose" not in recommendation_panel,
                expected="no prose region",
                actual="prose region present" if "recommendation-prose" in recommendation_panel else "absent",
            )
        )

    routes_section = _section_html(html, "routes")
    route_swatches = routes_section.count('class="swatch"')
    checks.append(
        _check(
            "route-swatch-count",
            route_swatches == expected_route_swatches,
            expected=expected_route_swatches,
            actual=route_swatches,
        )
    )
    checks.append(
        _check(
            "swatch-css-auto-fit",
            "repeat(auto-fit" in html and "repeat(5, minmax" not in html,
            expected="auto-fit swatch strip",
            actual="auto-fit" if "repeat(auto-fit" in html else "fixed",
        )
    )

    grader_section = _section_html(html, "grader")
    query_column = _grader_column_html(grader_section, "London library checks")
    query_items = query_column.count('class="grader-trace-item"')
    checks.append(
        _check(
            "brain-query-receipts-count",
            query_items == scenario.telemetry_query_count,
            expected=scenario.telemetry_query_count,
            actual=query_items,
        )
    )
    if scenario.telemetry_query_count == 0:
        checks.append(
            _check(
                "zero-receipts-honest-empty",
                "No London library lookups available here." in query_column,
                expected="empty receipt message",
                actual="present" if "No London library lookups available here." in query_column else "missing",
            )
        )
    if scenario.telemetry_source_count:
        sensor_text = f"{scenario.telemetry_source_count} of {scenario.telemetry_source_count} London library entries checked"
        checks.append(
            _check(
                "consulted-source-count",
                sensor_text in grader_section,
                expected=sensor_text,
                actual="present" if sensor_text in grader_section else "missing",
            )
        )

    core_html = conversation_section + recommendation_panel
    checks.append(
        _check(
            "no-padding-or-clipping-markers",
            all(marker not in core_html for marker in ("phantom gate", "undefined", "null", "&hellip;", "…")),
            expected="no placeholder/clipping markers",
            actual=(
                "clean"
                if all(marker not in core_html for marker in ("phantom gate", "undefined", "null", "&hellip;", "…"))
                else "marker present"
            ),
        )
    )
    return checks


def _adapt_direction(direction: Mapping[str, Any]) -> dict[str, Any]:
    adapted = copy.deepcopy(dict(direction))
    routes = _as_mappings(adapted.get("routes"))
    if "recommended_route_ref" not in adapted or not adapted.get("recommended_route_ref"):
        adapted["recommended_route_ref"] = str((routes[0] if routes else {}).get("title") or "Route 1")
    return adapted


def _routes_from_direction(direction: Mapping[str, Any], brief_record: Mapping[str, Any]) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    for index, route in enumerate(_as_mappings(direction.get("routes")), start=1):
        title = str(route.get("title") or f"Route {index}")
        route_id = f"{slugify(str(brief_record.get('title') or 'brief')) or 'route'}-{slugify(title) or f'route-{index}'}"
        routes.append(
            {
                "id": route_id,
                "title": title,
                "headline": str(route.get("headline") or title),
                "subhead": str(route.get("subhead") or ""),
                "palette": [dict(color) for color in _as_mappings(route.get("palette"))],
                "assets": [],
                "tags": [str(tag) for tag in route.get("tags") or []],
                "lore": str(route.get("lore") or ""),
                "mood": str(route.get("mood") or ""),
                "type": str(route.get("type_note") or route.get("type") or ""),
                "rationale": str(route.get("rationale") or ""),
                "steal": [str(item) for item in route.get("steal") or []],
                "do_not_copy": [str(item) for item in route.get("do_not_copy") or []],
                "sections": [
                    {
                        "title": str(section.get("title") or f"Section {section_index}"),
                        "body": str(section.get("body") or ""),
                        "eyebrow": f"{brief_record.get('title', 'Brief')} / Route {index:02d}",
                    }
                    for section_index, section in enumerate(_as_mappings(route.get("sections")), start=1)
                ],
                "source_inspiration": [],
                "build_implications": [
                    "Render from London's current output shape.",
                    "Do not pad, clip, or re-rank the route.",
                ],
                "approval_state": "validation-rendered",
            }
        )
    return routes


def _telemetry_for_scenario(scenario: ChassisScenario) -> RunTelemetry:
    source_ids = [f"source-{index:012x}" for index in range(1, scenario.telemetry_source_count + 1)]
    traces: list[BrainQueryTrace] = []
    for index in range(1, scenario.telemetry_query_count + 1):
        sid = source_ids[index - 1] if index - 1 < len(source_ids) else None
        traces.append(
            BrainQueryTrace(
                query=f"{scenario.name} validation query {index}",
                tool_use_id=f"{slugify(scenario.name) or 'scenario'}-{index}",
                returned_source_ids=[sid] if sid else [],
                result_count=1 if sid else 0,
            )
        )
    return RunTelemetry(
        engine_mode="validation",
        brain_query_count=len(traces),
        brain_queries=traces,
        consulted_source_ids=source_ids,
        brain_total_entries=max(len(source_ids), scenario.telemetry_query_count),
        tool_call_count=scenario.telemetry_query_count,
        captured=True,
    )


def _capture_queries(capture: Mapping[str, Any], *, include_select: bool = False) -> list[str]:
    queries: list[str] = []
    for query in capture.get("brain_queries") or []:
        if not isinstance(query, str) or not query.strip():
            continue
        if not include_select and query.startswith("select:"):
            continue
        queries.append(query)
    return queries


def _section_html(html: str, section_id: str) -> str:
    match = re.search(
        rf'<section[^>]*id="{re.escape(section_id)}"[^>]*>.*?(?=<section[^>]*id=|\Z)',
        html,
        flags=re.S,
    )
    return match.group(0) if match else ""


def _class_section_html(html: str, class_name: str) -> str:
    match = re.search(
        rf'<section[^>]*class="{re.escape(class_name)}"[^>]*>.*?</section>',
        html,
        flags=re.S,
    )
    return match.group(0) if match else ""


def _grader_column_html(grader_section: str, heading: str) -> str:
    match = re.search(
        rf'<div class="grader-column[^"]*">\s*<p class="grader-column-head">{re.escape(heading)}</p>.*?</ul>\s*</div>',
        grader_section,
        flags=re.S,
    )
    return match.group(0) if match else ""


def _as_mappings(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _check(name: str, ok: bool, *, expected: Any, actual: Any) -> dict[str, Any]:
    return {
        "name": name,
        "ok": bool(ok),
        "expected": expected,
        "actual": actual,
    }
