"""Contract + echo tests for the director seam (A2 / ENG-01, ENG-03, TST-04).

Everything here runs KEYLESS and OFFLINE — the entire model-path test surface goes
through ``FakeDirector``, which needs neither a network nor an API key (TST-04). These
tests prove:

  * the ``DirectionResult`` contract round-trips and rejects under-fill / bad hex,
  * the Pydantic schema's route/font/conversation property names AGREE with the
    renderer-critical ``$defs`` in ``schemas/london-pack.schema.json`` (the agreement
    Task 1's import-only gate could not run),
  * ``FakeDirector`` ECHOES brief tokens (never constants — Pitfall 8 guard), and
  * two unrelated briefs yield distinct titles AND distinct palettes.

The fuller property catalogue + negative-control fixtures are A6 (plan 01-06) over
``conftest.py``; this file only proves the fake echoes and the contract validates.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from london.director import (
    ClaudeCodeDirector,
    CreativeDirector,
    DirectionRequest,
    DirectionResult,
    FakeDirector,
    FontOption,
    LondonNoModelError,
    OfflineDirector,
)
from london import persona

from conftest import BRIEFS

_SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "london-pack.schema.json"
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")


def _tokenize(text: str) -> set[str]:
    return {m.group(0).lower() for m in _TOKEN_RE.finditer(text or "")}


def _request(brief_text: str) -> DirectionRequest:
    """Mirror of test_workbench.py's ``_pack(brief)`` helper, for the director seam.

    Seeds ``product_tokens`` from the brief so the fake has explicit tokens to echo, and
    attaches one brain finding so the rationale-cites-brain story has real input.
    """

    title = brief_text.strip().splitlines()[0].lstrip("# ").strip()
    tokens = [t for t in _tokenize(brief_text) if len(t) >= 4][:6]
    return DirectionRequest(
        brief={"title": title, "text": brief_text},
        brain_findings={"research": [{"title": "Quiet material drama beats loud packaging"}]},
        product_tokens=tokens,
    )


def _direct(brief_text: str) -> DirectionResult:
    return FakeDirector().direct(_request(brief_text))


def test_fake_director_satisfies_protocol():
    # No network, no key — the entire model-path test surface runs offline (TST-04).
    assert isinstance(FakeDirector(), CreativeDirector)


def test_contract_round_trips():
    result = _direct(BRIEFS["fragrance"])
    # model_validate over the dumped dict round-trips the full contract.
    revalidated = DirectionResult.model_validate(result.model_dump())
    assert revalidated == result
    # The seam hands the dict-consuming stages a plain dict.
    dumped = result.model_dump()
    assert isinstance(dumped, dict)
    assert len(dumped["routes"]) == 2


def test_under_fill_raises_validation_error():
    # Drop a required route field — the Pydantic contract is the first under-fill gate
    # (threat T-02-01); a half-pack must be rejectable BEFORE any file is written.
    payload = _direct(BRIEFS["fragrance"]).model_dump()
    del payload["routes"][0]["rationale"]
    with pytest.raises(ValidationError):
        DirectionResult.model_validate(payload)


def test_palette_hex_is_rejected():
    payload = _direct(BRIEFS["fragrance"]).model_dump()
    payload["palette"][0]["hex"] = "not-a-hex"
    with pytest.raises(ValidationError):
        DirectionResult.model_validate(payload)


def test_schema_agrees_with_pack_defs():
    # The director-era change is PROVENANCE, not shape — DirectionResult's route/font/
    # conversation field names must match the pack's renderer-critical $defs so the two
    # contracts cannot drift (this is the agreement Task 1's import-only gate deferred).
    schema = DirectionResult.model_json_schema()
    assert isinstance(schema, dict) and "properties" in schema
    director_defs = schema["$defs"]

    pack = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    pack_defs = pack["$defs"]

    # The renderer-critical, schema-SHAPED structures map 1:1 — every DirectionResult
    # field has a home in the matching pack $def (provenance, not shape). The model's
    # extra route prose (mood/rationale/lore/steal/...) is renderer text whose schema
    # homes are split across routeComparison + the route's own sections, so visualRoute
    # (the thin, asset-bearing route slot) is checked on its shared shape fields only.
    exact_pairs = [
        ("FontOption", "fontOption"),
        ("ConversationRead", "conversationEntry"),
        ("PaletteColor", "paletteColor"),
        ("RouteComparison", "routeComparison"),
    ]
    for director_name, pack_name in exact_pairs:
        director_props = set(director_defs[director_name]["properties"])
        pack_props = set(pack_defs[pack_name]["properties"])
        missing = director_props - pack_props
        assert not missing, f"{director_name} fields {missing} absent from pack ${pack_name} $defs"

    # visualRoute is a deliberate subset (asset-bearing slot): assert the shared shape
    # fields agree in name, so the route schema cannot drift on the fields it owns.
    route_shape_fields = {"title", "headline", "subhead", "palette"}
    visual_route_props = set(pack_defs["visualRoute"]["properties"])
    director_route_props = set(director_defs["RouteResult"]["properties"])
    assert route_shape_fields <= visual_route_props
    assert route_shape_fields <= director_route_props

    # The schema-required field most likely to be under-filled is present in both.
    assert "why_this_route_not_other_route" in director_defs["FontOption"]["properties"]
    assert "why_this_route_not_other_route" in pack_defs["fontOption"]["properties"]
    assert "font_preview" in director_defs["FontOption"]["properties"]
    assert "font_preview" in pack_defs["fontOption"]["properties"]
    # The font tier enum agrees.
    assert set(pack_defs["fontOption"]["properties"]["tier"]["enum"]) == {
        "safe_local",
        "open_public",
        "premium_inspiration",
    }


def test_font_option_accepts_nested_font_preview_metadata():
    option = FontOption.model_validate(
        {
            "tier": "open_public",
            "name": "Kiddo Public",
            "headline_font": "Kiddo Local",
            "body_font": "Kiddo Sans",
            "label_font": "Kiddo Sans Label",
            "fallback_stack": "Arial, Helvetica, sans-serif",
            "best_use": "Friendly public web UI.",
            "why_london_chose_it": "It keeps the lunchbox route legible without becoming sterile.",
            "why_this_route_not_other_route": "The other route needs a quieter institutional read.",
            "what_makes_it_wrong": "Wrong if the interface needs a premium editorial voice.",
            "import_hint": "@import url('https://fonts.example/kiddo.css');",
            "font_preview": {
                "status": "actual_loaded",
                "delivery": "local_asset",
                "rendered_family": "Kiddo Local",
                "source_label": "Bundled test font",
                "license_note": "Local test asset supplied with this pack.",
                "asset_href": "assets/fonts/kiddo-local.woff2",
            },
        }
    )

    assert option.font_preview is not None
    assert option.font_preview.status == "actual_loaded"
    assert option.font_preview.delivery == "local_asset"


def test_fake_echoes():
    # The echo property: a route title shares >=1 token with the brief. A FakeDirector
    # that returned CONSTANT titles would make this fail — that is the regression guard
    # against the trivial-pass trap (Pitfall 8 / threat T-02-02). The paired assertion
    # below proves a constant title would NOT intersect the brief.
    brief = BRIEFS["fragrance"]
    result = _direct(brief)
    brief_tokens = _tokenize(brief)

    title_tokens = _tokenize(result.routes[0].title)
    assert title_tokens & brief_tokens, "route title must echo brief tokens, not be a constant"

    # rationale also cites brief tokens (carries the brief-specificity forward).
    rationale_tokens = _tokenize(result.routes[0].rationale)
    assert rationale_tokens & brief_tokens

    # Paired regression guard: a hard-coded constant title shares no token with the brief,
    # so swapping the echo for a constant WOULD break the assertion above.
    assert not (_tokenize("Generic Modern Clean Route") & brief_tokens)


def test_unrelated_briefs_diverge():
    # Two semantically unrelated briefs must yield distinct route titles AND distinct
    # palettes — so brief-specificity properties can pass on the fake and fail on a
    # generic pack. (hr vs fragrance share no product vocabulary.)
    a = _direct(BRIEFS["hr"])
    b = _direct(BRIEFS["fragrance"])

    assert a.routes[0].title != b.routes[0].title
    assert a.routes[1].title != b.routes[1].title

    hexes_a = tuple(color.hex for color in a.palette)
    hexes_b = tuple(color.hex for color in b.palette)
    assert hexes_a != hexes_b


def test_recommended_route_is_a_required_schema_field():
    # D-04: recommended_route_ref is the REAL machine field on DirectionResult both model
    # paths are constrained to emit (via DirectionResult.model_json_schema()) — MUST be in
    # both 'properties' and 'required' so the model cannot omit the pick. The verbatim
    # PROSE field `recommended_route` is present but OPTIONAL (default "", the floor).
    assert "recommended_route_ref" in DirectionResult.model_fields
    assert "recommended_route" in DirectionResult.model_fields
    schema = DirectionResult.model_json_schema()
    assert "recommended_route_ref" in schema["properties"]
    assert "recommended_route_ref" in schema.get("required", [])
    assert "recommended_route" in schema["properties"]
    assert "recommended_route" not in schema.get("required", [])


def test_recommended_route_honest_default_offline_and_fake():
    # D-04 floor: the two deterministic paths emit an HONEST machine reference
    # `recommended_route_ref` = the lead route title (routes[0].title), never None and
    # never a faked ranking; the recommendation PROSE is "" (the floor never argues a
    # case). This is the keyless guarantee the renderer resolves AS GIVEN.
    for result in (_direct(BRIEFS["fragrance"]), OfflineDirector().direct(_request(BRIEFS["fragrance"]))):
        assert result.recommended_route_ref, "recommended_route_ref must be non-empty (never None)"
        assert result.recommended_route_ref == result.routes[0].title
        assert result.recommended_route == "", "the deterministic floor never argues a case (prose '')"


def test_recommended_route_is_a_real_route_not_a_fabrication():
    # T-04-03 honesty guard: recommended_route_ref must name an ACTUAL route the director
    # produced (never a computed score or invented label) AND must track brief-specific
    # data — so it differs across unrelated briefs. A hardcoded/faked ranking would be a
    # constant string disconnected from the real route set.
    fragrance = OfflineDirector().direct(_request(BRIEFS["fragrance"]))
    hr = OfflineDirector().direct(_request(BRIEFS["hr"]))

    assert fragrance.recommended_route_ref in {r.title for r in fragrance.routes}
    assert hr.recommended_route_ref in {r.title for r in hr.routes}
    assert fragrance.recommended_route_ref != hr.recommended_route_ref


# =============================================================================
# Phase 4.5 GATE-01 — artifact_type (RED stubs; Wave 0). These CLONE the
# recommended_route schema-field + honest-default idiom above (:183-213). They
# fail today because DirectionResult has NO artifact_type field yet; Wave 2
# drives them GREEN. artifact_type is a SESSION-LEVEL constrained enum
# (website|app|product|brand|generic), NOT an 8th persona.GATE_ID.
# =============================================================================

_ARTIFACT_ENUM = {"website", "app", "product", "brand", "generic"}


def test_artifact_type_is_a_required_enum_schema_field():
    # GATE-01: artifact_type is a REAL Literal field on DirectionResult so BOTH model
    # paths are constrained to emit it via the shared model_json_schema() — clone of
    # test_recommended_route_is_a_required_schema_field. It MUST be in 'properties' AND
    # 'required', and the generated property MUST carry an enum equal (order-insensitive)
    # to the 5-value artifact set. (Pydantic emits a Literal[...] as a JSON-Schema enum.)
    assert "artifact_type" in DirectionResult.model_fields
    schema = DirectionResult.model_json_schema()
    assert "artifact_type" in schema["properties"]
    assert "artifact_type" in schema.get("required", [])
    prop = schema["properties"]["artifact_type"]
    # Pydantic may emit the enum inline ("enum") or via a $ref to a $defs enum — accept
    # either, but the membership set must equal the artifact enum exactly.
    enum_values = prop.get("enum")
    if enum_values is None and "$ref" in prop:
        ref = prop["$ref"].rsplit("/", 1)[-1]
        enum_values = schema["$defs"][ref]["enum"]
    assert enum_values is not None, "artifact_type must be a constrained enum, not a free string"
    assert set(enum_values) == _ARTIFACT_ENUM


def test_artifact_type_honest_default_is_generic_offline_and_fake():
    # GATE-01 / RESEARCH Pitfall 3: the two DETERMINISTIC paths can never honestly infer a
    # specific type, so they MUST default to "generic" (never a faked specific type). This
    # is the keyless honesty floor — clone of test_recommended_route_honest_default_*.
    for result in (_direct(BRIEFS["fragrance"]), OfflineDirector().direct(_request(BRIEFS["fragrance"]))):
        assert result.artifact_type == "generic"


# =============================================================================
# ClaudeCodeDirector — auto-detect + dual fix-it hard-error (A4 / ENG-02, D-01..D-03)
# These run KEYLESS and make NO live model call (TST-04): detection is driven entirely
# by monkeypatched imports + env, and the only assertions are which path was selected
# and that the hard-error teaches both fixes.
# =============================================================================


def _no_sdk(monkeypatch):
    """Force ``import claude_agent_sdk`` and ``import anthropic`` to fail."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name in {"claude_agent_sdk", "anthropic"} or name.startswith("claude_agent_sdk.") or name.startswith("anthropic."):
            raise ImportError(f"no module named {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_detect_in_session_when_sdk_importable_and_runtime_present(monkeypatch):
    # With a stub ``claude_agent_sdk`` importable AND a Claude Code runtime marker present,
    # detection resolves to the in-session path WITHOUT needing an API key (D-01 first
    # branch). No live call is made.
    #
    # F-4 (04.6-04 spike) / D-04.6-A #2: SDK-importable ALONE is no longer sufficient now
    # that claude-agent-sdk is a base dep — a Claude Code runtime marker (CLAUDECODE /
    # CLAUDE_CODE_ENTRYPOINT, read from the injected env) is required too. The keyless suite
    # also must not be (mis)detected as a live session, so the in-session guard reads the
    # ACTUAL process env for PYTEST_CURRENT_TEST; we clear it here to simulate a non-pytest
    # in-session runtime.
    import sys
    import types

    stub = types.ModuleType("claude_agent_sdk")
    stub.query = lambda *a, **k: None  # type: ignore[attr-defined]
    stub.ClaudeAgentOptions = object  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", stub)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    director = ClaudeCodeDirector(env={"CLAUDECODE": "1"})
    assert director.detect_mode() == "in_session"


def test_sdk_importable_without_runtime_is_not_in_session(monkeypatch):
    # F-4: a keyless box with the SDK installed but NO Claude Code runtime marker must NOT
    # falsely claim the in-session model is reachable. With no key either, detection raises
    # the honest LondonNoModelError (the no-model default holds in CI; D-01/D-03).
    import sys
    import types

    stub = types.ModuleType("claude_agent_sdk")
    stub.query = lambda *a, **k: None  # type: ignore[attr-defined]
    stub.ClaudeAgentOptions = object  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", stub)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    # env carries NO CLAUDECODE / CLAUDE_CODE_ENTRYPOINT marker.
    director = ClaudeCodeDirector(env={})
    assert director._in_session_available() is False
    with pytest.raises(LondonNoModelError):
        director.detect_mode()


def test_detect_claude_cli_print_when_explicitly_requested(monkeypatch):
    import sys
    import types

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    stub = types.ModuleType("claude_agent_sdk")
    stub.ClaudeAgentOptions = object  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", stub)

    director = ClaudeCodeDirector(env={"LONDON_CLAUDE_CLI_PRINT": "1"})

    assert director._in_session_available() is False
    assert director.detect_mode() == "claude_cli_print"


def test_director_mode_override_can_force_keyed_over_in_session(monkeypatch):
    import sys
    import types

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    sdk_stub = types.ModuleType("claude_agent_sdk")
    sdk_stub.ClaudeAgentOptions = object  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", sdk_stub)

    director = ClaudeCodeDirector(
        env={
            "CLAUDECODE": "1",
            "ANTHROPIC_API_KEY": "sk-not-real-test-value",
            "LONDON_DIRECTOR_MODE": "keyed",
        }
    )

    assert director.detect_mode() == "keyed"


def test_director_mode_override_offline_points_to_explicit_switch(monkeypatch):
    _no_sdk(monkeypatch)
    director = ClaudeCodeDirector(env={"LONDON_DIRECTOR_MODE": "offline"})

    with pytest.raises(LondonNoModelError) as excinfo:
        director.detect_mode()

    assert "--offline" in str(excinfo.value)


def test_keyless_pytest_suite_is_never_in_session():
    # The keyless suite proves the PLUMBING, never the ENGINE (04.6-VALIDATION split). Even
    # with the real SDK importable AND an ambient CLAUDECODE (which leaks into every child of
    # a Claude Code session), running UNDER pytest must NOT resolve to in-session — otherwise
    # the default path would reach a live query() mid-test. PYTEST_CURRENT_TEST is set for the
    # duration of this test, so the in-session guard returns False here.
    import os

    assert os.environ.get("PYTEST_CURRENT_TEST"), "this assertion only holds under pytest"
    director = ClaudeCodeDirector(env={"CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli"})
    assert director._in_session_available() is False


def test_in_session_director_sets_noninteractive_permission_and_print_mode(monkeypatch):
    # The in-session pack builder is non-interactive. With only the three London brain tools
    # allowed, permission prompts would deadlock before any pack files are written.
    import claude_agent_sdk

    request = _request(BRIEFS["fragrance"])
    result = OfflineDirector().direct(request)
    captured = {}

    async def fake_query(*, prompt, options):
        captured["prompt"] = prompt
        captured["permission_mode"] = options.permission_mode
        captured["extra_args"] = dict(options.extra_args)
        captured["allowed_tools"] = list(options.allowed_tools)

        class StructuredMessage:
            structured_output = result.model_dump()
            subtype = None

        yield StructuredMessage()

    monkeypatch.setattr(claude_agent_sdk, "query", fake_query)

    director = ClaudeCodeDirector(env={"CLAUDECODE": "1"})
    returned = director._direct_in_session("seed")

    assert returned == result
    assert captured["prompt"] == "seed"
    assert captured["permission_mode"] == "bypassPermissions"
    assert captured["extra_args"] == {"print": None}
    assert captured["allowed_tools"] == [
        "mcp__london-brain__london_brain_query",
        "mcp__london-brain__london_brain_inventory",
        "mcp__london-brain__london_brain_categories",
    ]


def test_in_session_sdk_command_builder_emits_print_flag():
    # The mock above proves London passes the option; this checks the installed SDK turns
    # that option into the actual CLI flag that keeps the one-shot director path
    # noninteractive.
    from claude_agent_sdk import ClaudeAgentOptions
    from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport

    options = ClaudeAgentOptions(permission_mode="bypassPermissions", extra_args={"print": None})
    transport = SubprocessCLITransport(prompt="seed", options=options)
    transport._cli_path = "claude"

    command = transport._build_command()

    assert "--permission-mode" in command
    assert command[command.index("--permission-mode") + 1] == "bypassPermissions"
    assert "--print" in command
    assert command.index("--print") < command.index("--input-format")


def test_in_session_director_times_out_with_named_transport_error(monkeypatch):
    import asyncio
    import claude_agent_sdk

    async def hanging_query(*, prompt, options):
        await asyncio.sleep(60)
        yield object()

    monkeypatch.setattr(claude_agent_sdk, "query", hanging_query)

    director = ClaudeCodeDirector(
        env={
            "CLAUDECODE": "1",
            "LONDON_DIRECTOR_TRANSPORT_TIMEOUT_SECONDS": "0.01",
        }
    )

    with pytest.raises(LondonNoModelError) as excinfo:
        director._direct_in_session("seed")

    assert "director_transport_hung" in str(excinfo.value)


def test_in_session_director_rejects_already_running_event_loop(monkeypatch):
    import asyncio
    import claude_agent_sdk

    async def fake_query(*, prompt, options):
        yield object()

    monkeypatch.setattr(claude_agent_sdk, "query", fake_query)
    director = ClaudeCodeDirector(env={"CLAUDECODE": "1"})

    async def call_inside_loop():
        with pytest.raises(LondonNoModelError) as excinfo:
            director._direct_in_session("seed")
        return str(excinfo.value)

    message = asyncio.run(call_inside_loop())

    assert "already-running event loop" in message


def test_packaged_skill_cache_refreshes_on_version_stamp_mismatch(monkeypatch, tmp_path):
    import london.directors.claude as director_module

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    skill_root = Path(director_module._resolve_skill_cwd())
    cached_skill = skill_root / ".claude" / "skills" / "london-creative-director" / "SKILL.md"
    stamp = cached_skill.parent / ".london-package-version"
    original = cached_skill.read_text(encoding="utf-8")

    cached_skill.write_text("stale skill", encoding="utf-8")
    stamp.write_text("older-version", encoding="utf-8")

    refreshed_root = Path(director_module._resolve_skill_cwd())

    assert refreshed_root == skill_root
    assert cached_skill.read_text(encoding="utf-8") == original
    assert stamp.read_text(encoding="utf-8") == director_module.__version__


def test_packaged_skill_missing_fails_loudly(monkeypatch, tmp_path):
    import london.directors.claude as director_module

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(director_module, "_PACKAGED_SKILL_DIR", tmp_path / "missing-skill")

    with pytest.raises(LondonNoModelError) as excinfo:
        director_module._resolve_skill_cwd()

    message = str(excinfo.value)
    assert "packaged creative-director skill is missing" in message
    assert "Reinstall" in message


def test_keyed_director_names_second_max_tokens_truncation(monkeypatch):
    import sys
    import types

    calls = []
    closed = []

    class FakeMessages:
        def parse(self, **kwargs):
            calls.append(kwargs["max_tokens"])
            return types.SimpleNamespace(stop_reason="max_tokens", parsed_output=None)

    class FakeAnthropic:
        def __init__(self, **kwargs):
            self.messages = FakeMessages()

        def close(self):
            closed.append(True)

    anthropic_stub = types.ModuleType("anthropic")
    anthropic_stub.Anthropic = FakeAnthropic  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "anthropic", anthropic_stub)

    director = ClaudeCodeDirector(env={"ANTHROPIC_API_KEY": "sk-not-real-test-value"})

    with pytest.raises(LondonNoModelError) as excinfo:
        director._direct_keyed("seed")

    assert calls == [8192, 16384]
    assert "director_output_truncated" in str(excinfo.value)
    assert "16384" in str(excinfo.value)
    assert closed == [True]


def test_claude_cli_print_transport_parses_structured_output(monkeypatch):
    import london.directors.claude as director_module

    request = _request(BRIEFS["fragrance"])
    result = OfflineDirector().direct(request)
    captured = {}
    stdout = "\n".join(
        [
            json.dumps({"type": "system", "subtype": "init"}),
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "StructuredOutput",
                                "input": result.model_dump(),
                            }
                        ]
                    },
                }
            ),
            json.dumps({"type": "result", "subtype": "success", "is_error": False, "duration_ms": 123}),
        ]
    )

    class FakeProcess:
        returncode = 0
        pid = 12345

        def __init__(self, command, **kwargs):
            captured["command"] = list(command)
            captured["kwargs"] = dict(kwargs)

        def communicate(self, timeout=None):
            captured["timeout"] = timeout
            return stdout, ""

    monkeypatch.setattr(director_module.subprocess, "Popen", FakeProcess)

    director = ClaudeCodeDirector(env={"LONDON_CLAUDE_CLI_PRINT": "1"})
    returned = director._direct_claude_cli_print("seed")

    assert returned == result
    assert captured["command"][:3] == ["claude", "-p", "seed"]
    assert "--output-format" in captured["command"]
    assert captured["command"][captured["command"].index("--output-format") + 1] == "stream-json"
    assert "--verbose" in captured["command"]
    assert "--json-schema" in captured["command"]
    assert "--effort" in captured["command"]
    assert captured["command"][captured["command"].index("--effort") + 1] == "low"
    assert "--no-session-persistence" in captured["command"]
    assert "--input-format" not in captured["command"]
    allowed = captured["command"][captured["command"].index("--allowedTools") + 1]
    assert "Skill(london-creative-director)" in allowed
    assert captured["timeout"] > 0
    assert "GEMINI_API_KEY" not in captured["kwargs"]["env"]


def test_claude_cli_print_transport_allows_explicit_effort_override(monkeypatch):
    import london.directors.claude as director_module

    request = _request(BRIEFS["fragrance"])
    result = OfflineDirector().direct(request)
    captured = {}
    stdout = "\n".join(
        [
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "StructuredOutput",
                                "input": result.model_dump(),
                            }
                        ]
                    },
                }
            ),
            json.dumps({"type": "result", "subtype": "success", "is_error": False}),
        ]
    )

    class FakeProcess:
        returncode = 0
        pid = 12345

        def __init__(self, command, **kwargs):
            captured["command"] = list(command)

        def communicate(self, timeout=None):
            return stdout, ""

    monkeypatch.setattr(director_module.subprocess, "Popen", FakeProcess)

    director = ClaudeCodeDirector(env={"LONDON_CLAUDE_CLI_PRINT": "1", "LONDON_CLAUDE_CLI_EFFORT": "medium"})
    returned = director._direct_claude_cli_print("seed")

    assert returned == result
    assert captured["command"][captured["command"].index("--effort") + 1] == "medium"


def test_claude_cli_print_transport_rejects_is_error_even_with_structured_output(monkeypatch):
    import london.directors.claude as director_module

    request = _request(BRIEFS["fragrance"])
    result = OfflineDirector().direct(request)
    stdout = "\n".join(
        [
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "StructuredOutput",
                                "input": result.model_dump(),
                            }
                        ]
                    },
                }
            ),
            json.dumps({"type": "result", "subtype": "success", "is_error": True}),
        ]
    )

    class FakeProcess:
        returncode = 0
        pid = 12345

        def __init__(self, command, **kwargs):
            pass

        def communicate(self, timeout=None):
            return stdout, ""

    monkeypatch.setattr(director_module.subprocess, "Popen", FakeProcess)

    director = ClaudeCodeDirector(env={"LONDON_CLAUDE_CLI_PRINT": "1", "GEMINI_API_KEY": "gemini-secret"})

    with pytest.raises(LondonNoModelError) as excinfo:
        director._direct_claude_cli_print("seed")

    assert "is_error" in str(excinfo.value)


def test_detect_keyed_when_key_present_and_anthropic_importable(monkeypatch):
    # No in-session SDK, but ANTHROPIC_API_KEY set + a stub ``anthropic`` importable →
    # the keyed path (D-01 second branch).
    import types

    _no_sdk(monkeypatch)
    anthropic_stub = types.ModuleType("anthropic")
    anthropic_stub.Anthropic = object  # type: ignore[attr-defined]

    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "claude_agent_sdk":
            raise ImportError("no in-session sdk")
        if name == "anthropic":
            return anthropic_stub
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    director = ClaudeCodeDirector(env={"ANTHROPIC_API_KEY": "sk-not-real-test-value"})
    assert director.detect_mode() == "keyed"


def test_hard_error_when_no_model_reachable(monkeypatch):
    # Neither in-session SDK nor key → LondonNoModelError whose message teaches BOTH
    # fixes (Claude Code / ANTHROPIC_API_KEY AND --offline). Never falls back to offline.
    _no_sdk(monkeypatch)
    director = ClaudeCodeDirector(env={})

    with pytest.raises(LondonNoModelError) as excinfo:
        director.direct(_request(BRIEFS["fragrance"]))

    message = str(excinfo.value)
    # Fix (a): how to make a model reachable.
    assert "ANTHROPIC_API_KEY" in message or "Claude Code" in message
    # Fix (b): the offline escape hatch.
    assert "--offline" in message


def test_detect_mode_hard_errors_with_dual_fixit(monkeypatch):
    _no_sdk(monkeypatch)
    director = ClaudeCodeDirector(env={})
    with pytest.raises(LondonNoModelError) as excinfo:
        director.detect_mode()
    message = str(excinfo.value)
    assert ("ANTHROPIC_API_KEY" in message) or ("Claude Code" in message)
    assert "--offline" in message


def test_claude_code_director_never_references_offline_director():
    # D-03 hard rule, proven structurally: the ClaudeCodeDirector class body never names
    # OfflineDirector. (Plan verification also greps src/london/director.py.)
    import inspect

    source = inspect.getsource(ClaudeCodeDirector)
    assert "OfflineDirector" not in source


def test_claude_code_director_satisfies_protocol():
    assert isinstance(ClaudeCodeDirector(env={}), CreativeDirector)


def test_anthropic_key_redacted_from_error_surface():
    # A leaked key value in any director error string must be scrubbed before it could
    # surface (threat T-04-02). The director exposes the same redaction the keyed path
    # would apply to provider errors.
    secret = "sk-test-zzz-redaction-probe"
    director = ClaudeCodeDirector(env={"ANTHROPIC_API_KEY": secret})
    scrubbed = director._scrub_secret(f"boom from provider using key {secret}")
    assert secret not in scrubbed
    assert "[redacted]" in scrubbed


def test_anthropic_key_redacted_before_error_surface_truncation():
    secret = "sk-test-boundary-redaction-probe"
    director = ClaudeCodeDirector(env={"ANTHROPIC_API_KEY": secret})

    scrubbed = director._scrub_secret(("x" * 990) + secret + " after")

    assert "[redacted]" in scrubbed
    assert secret not in scrubbed
    leaked_windows = {secret[index : index + 8] for index in range(0, len(secret) - 7)}
    assert not any(window in scrubbed for window in leaked_windows)


# =============================================================================
# The single sanitization chokepoint (HON-01 / D-08) — persona.sanitize_public_text
# =============================================================================

_BANNED_QA_PHRASES = (
    "fresh lane",
    "borrowed route",
    "prior profile",
    "recycled profile",
    "reusable template",
    "fixture",
)


def test_sanitize_removes_all_banned_qa_phrases():
    dirty = (
        "This brief needs a fresh lane, not a borrowed route, and not any prior profile "
        "or recycled profile, never a reusable template, and no fixture."
    )
    clean = persona.sanitize_public_text(dirty)
    lowered = clean.lower()
    for phrase in _BANNED_QA_PHRASES:
        assert phrase not in lowered, f"banned QA phrase survived sanitization: {phrase!r}"


def test_sanitize_is_idempotent_and_safe_on_empty():
    assert persona.sanitize_public_text("") == ""
    once = persona.sanitize_public_text("a fresh lane and a borrowed route")
    twice = persona.sanitize_public_text(once)
    assert once == twice


def test_scrub_pack_cleans_public_prose_but_not_receipts():
    pack = {
        "title": "Fresh Lane Product",
        "category_assumption": "It reads like a borrowed route from another project.",
        "routes": [
            {"title": "Prior Profile Route", "rationale": "Built on a recycled profile and a reusable template."},
        ],
        # Receipts/debug must be UNTOUCHED — mode/template/preview words live here.
        "receipts": [{"status": "offline-template-preview", "note": "fixture fallback used"}],
        "provider_selection": {"selected_provider": "manual-prompt"},
    }
    persona.scrub_pack(pack)

    public_blob = " ".join(
        [pack["title"], pack["category_assumption"], pack["routes"][0]["title"], pack["routes"][0]["rationale"]]
    ).lower()
    for phrase in _BANNED_QA_PHRASES:
        assert phrase not in public_blob, f"{phrase!r} survived in public prose"

    # Receipts are deliberately NOT scrubbed.
    assert pack["receipts"][0]["status"] == "offline-template-preview"
    assert "fixture" in pack["receipts"][0]["note"]


def test_prompt_seed_is_sanitized_before_model(monkeypatch):
    # The prompt-seed builder must run sanitize_public_text so the model never learns
    # the QA register. We seed a brief carrying the QA vocabulary and assert the built
    # seed prompt is clean (BEFORE any model is invoked).
    _no_sdk(monkeypatch)
    director = ClaudeCodeDirector(env={})
    request = DirectionRequest(
        brief={"title": "Fresh Lane App", "text": "Avoid a borrowed route and any prior profile or fixture."},
        brain_findings={"research": [{"title": "A recycled profile is not a reusable template"}]},
        product_tokens=["fresh", "lane", "app"],
    )
    seed = director.build_seed_prompt(request)
    lowered = seed.lower()
    for phrase in _BANNED_QA_PHRASES:
        assert phrase not in lowered, f"QA phrase {phrase!r} leaked into the model prompt seed"


def test_show_me_selection_flows_into_model_prompt_without_paths_or_secrets(monkeypatch):
    from london.companion import selection_context

    _no_sdk(monkeypatch)
    director = ClaudeCodeDirector(env={})
    request = DirectionRequest(
        brief={"title": "Product System", "text": "Build the next model pass from the selected visual option."},
        product_tokens=["product", "system"],
        visual_selection=selection_context(
            {
                "selected_option_id": "option-2-shared-signal",
                "selected_route_ref": "route-b",
                "selected_route_title": "Shared Signal",
                "selected_artifact_type": "product",
                "reasoning_input": "Use /tmp/pack and sk-secret-token but continue from Shared Signal.",
            }
        ),
    )
    seed = director.build_seed_prompt(request)

    assert "LONDON_SHOW_ME_SELECTION" in seed
    assert "option-2-shared-signal" in seed
    assert "route-b" in seed
    assert "Shared Signal" in seed
    assert "/tmp/pack" not in seed
    assert "sk-secret-token" not in seed
