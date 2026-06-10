import json
import sys
import hashlib
import io
import urllib.error
from pathlib import Path

import jsonschema
import pytest

from london.cli import _route_ids_for_image_generation, main, write_london_pack
from london.director import FakeDirector
from london.config import set_config_value
from london.image_generation import (
    ProviderUnavailable,
    _get_bytes,
    _poll_bfl,
    _redacted_local_url,
    build_image_prompt,
    generate_route_concept,
    normalize_image_provider,
)
from london.setup_checks import collect_setup_status


def _paid_spend(limit: float = 5.0, routes: int = 1) -> dict[str, float | bool | int]:
    return {"allow_paid": True, "spend_limit_usd": limit, "routes_to_generate": routes}


def _brief(tmp_path: Path, text: str | None = None) -> Path:
    path = tmp_path / "brief.md"
    path.write_text(
        text
        or """# Public Horoscope App

Design a public facing horoscope app for daily astrology readings, birth-chart onboarding,
compatibility moments, push notifications, and shareable cards.
""",
        encoding="utf-8",
    )
    return path


def _clear_live_image_keys(monkeypatch) -> None:
    for key in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "BFL_API_KEY",
        "OPENAI_API_KEY",
        "LONDON_GEMINI_API_VERSION",
        "LONDON_GEMINI_IMAGE_MODEL",
        "LONDON_GEMINI_IMAGE_ASPECT_RATIO",
        "LONDON_GEMINI_IMAGE_SIZE",
        "LONDON_GEMINI_RESPONSE_MODALITIES",
        "LONDON_BFL_MODEL_PATH",
        "LONDON_BFL_IMAGE_WIDTH",
        "LONDON_BFL_IMAGE_HEIGHT",
        "LONDON_OPENAI_IMAGE_MODEL",
        "LONDON_OPENAI_IMAGE_SIZE",
        "LONDON_OPENAI_IMAGE_QUALITY",
        "LONDON_OPENAI_IMAGE_OUTPUT_FORMAT",
        "LONDON_OPENAI_IMAGE_OUTPUT_COMPRESSION",
        "LONDON_OPENAI_IMAGE_BACKGROUND",
        "LONDON_OPENAI_IMAGE_MODERATION",
        "LONDON_DRAW_THINGS_COMMAND",
        "LONDON_DRAW_THINGS_CLI",
        "LONDON_EXTERNAL_IMAGE_COMMAND",
        "LONDON_LOCAL_IMAGE_COMMAND",
    ):
        monkeypatch.delenv(key, raising=False)


class _Headers:
    def __init__(self, content_type: str = "image/png") -> None:
        self._content_type = content_type

    def get_content_type(self):
        return self._content_type


class _BytesResponse:
    def __init__(self, payload: bytes, content_type: str = "image/png") -> None:
        self.payload = payload
        self.headers = _Headers(content_type)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, size=-1):
        if size is None or size < 0:
            return self.payload
        return self.payload[:size]


def test_redacted_local_url_removes_userinfo_from_receipts():
    redacted = _redacted_local_url("http://u:hunter2@host:8188/api")

    assert redacted == "http://host:8188"
    assert "hunter2" not in redacted
    assert "u@" not in redacted


def test_http_seam_refuses_oversized_image_response(monkeypatch):
    def fake_open(request, timeout):
        return _BytesResponse(b"x" * 6)

    monkeypatch.setattr("london.image_generation.urllib.request.urlopen", fake_open)

    with pytest.raises(ProviderUnavailable) as excinfo:
        _get_bytes("https://example.com/image.png", timeout=1, env={}, max_bytes=5)

    assert str(excinfo.value) == "fallback_response_too_large"
    assert excinfo.value.error_class == "bad_request"


def test_bfl_credentialed_polling_rejects_http_or_cross_host(monkeypatch):
    def fail_open(*_args, **_kwargs):
        raise AssertionError("credentialed polling validation must run before network open")

    monkeypatch.setattr("london.image_generation.urllib.request.urlopen", fail_open)

    with pytest.raises(ProviderUnavailable) as http_exc:
        _poll_bfl(
            "http://api.bfl.ai/v1/get_result?id=req-1",
            "bfl-secret-value",
            {"LONDON_BFL_MAX_POLLS": "1", "LONDON_BFL_POLL_SECONDS": "0"},
            submit_url="https://api.bfl.ai/v1/flux-2-pro-preview",
        )
    assert http_exc.value.error_class == "auth"
    assert "https" in (http_exc.value.failure or "")

    with pytest.raises(ProviderUnavailable) as host_exc:
        _poll_bfl(
            "https://evil.example/v1/get_result?id=req-1",
            "bfl-secret-value",
            {"LONDON_BFL_MAX_POLLS": "1", "LONDON_BFL_POLL_SECONDS": "0"},
            submit_url="https://api.bfl.ai/v1/flux-2-pro-preview",
        )
    assert host_exc.value.error_class == "auth"
    assert "submit host" in (host_exc.value.failure or "")


def test_gemini_500_with_enum_looking_body_does_not_retry(monkeypatch):
    calls: list[str] = []

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        body = (
            b"invalid value at 'generation_config.response_format.image.aspect_ratio' "
            b"looks like an enum issue but came from a server failure"
        )
        raise urllib.error.HTTPError(
            request.full_url,
            500,
            "Server Error",
            {},
            io.BytesIO(body),
        )

    monkeypatch.setattr("london.image_generation.urllib.request.urlopen", fake_urlopen)
    pack = {"title": "Pet weather app", "brief": {"text": "Design a weather app for pet owners."}}
    route = {"id": "safe-walk-window", "title": "Safe Walk Window", "headline": "weather app"}

    result = generate_route_concept(
        pack,
        route,
        route_index=1,
        provider="gemini",
        requested_provider="gemini",
        spend_policy=_paid_spend(),
        env={
            "GEMINI_API_KEY": "gemini-secret-value",
            "LONDON_GEMINI_IMAGE_MODEL": "gemini-3-pro-image-preview",
            "LONDON_GEMINI_REQUEST_CONFIG_MODE": "configured",
        },
    )

    assert len(calls) == 1
    assert result.receipt["status"] == "fallback_provider_error"
    assert result.receipt["error_class"] == "network"
    assert len(result.receipt["attempted_request_configs"]) == 1


def _mark_pack_real_director(pack_dir: Path, provider: str = "claude_cli_print") -> None:
    pack_path = pack_dir / "london-pack.json"
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    for receipt in pack.get("receipts", []):
        if isinstance(receipt, dict) and receipt.get("kind") == "director":
            receipt["provider"] = provider
            receipt["deterministic"] = False
    pack_path.write_text(json.dumps(pack, indent=2, sort_keys=True), encoding="utf-8")
    (pack_dir / "receipts.json").write_text(json.dumps(pack["receipts"], indent=2, sort_keys=True), encoding="utf-8")


def test_keyless_image_generation_adds_honest_visual_direction_boards_and_receipts(tmp_path, monkeypatch):
    _clear_live_image_keys(monkeypatch)
    out = tmp_path / "pack"

    pack = write_london_pack(_brief(tmp_path), out)

    first_asset = pack["routes"][0]["assets"][0]
    image_receipts = [receipt for receipt in pack["receipts"] if receipt["kind"] == "image-generation"]
    first_tile = pack["moodboard_tiles"][0]["tiles"][0]

    assert first_asset["kind"] == "visual-direction-board"
    assert first_asset["provider"] == "manual-prompt"
    assert first_asset["requested_provider"] == "auto"
    assert first_asset["resolved_provider"] == "manual-prompt"
    assert first_asset["generation_status"] == "manual_prompt_ready"
    assert first_asset["deterministic"] is True
    assert first_asset["live_artifact"] is False
    assert first_asset["src"].endswith(".svg")
    assert (out / first_asset["src"]).exists()
    assert "not generated concept art" in first_asset["alt"].lower()
    assert first_asset["prompt"]
    assert all(asset["kind"] == "visual-direction-board" for route in pack["routes"] for asset in route["assets"])
    assert all(asset.get("src", "").endswith(".svg") for route in pack["routes"] for asset in route["assets"])
    assert image_receipts
    assert all(receipt["deterministic"] is True for receipt in image_receipts)
    assert all(receipt["secrets_printed"] is False for receipt in image_receipts)
    assert "London brain findings to translate" in image_receipts[0]["prompt"]
    assert "Source principles to respect" in image_receipts[0]["prompt"]
    assert first_tile["kind"] == "visual-direction-board"
    assert first_tile["prompt"]
    assert "not generated concept art" in first_tile["honesty_note"].lower()


def test_requested_gemini_without_key_falls_back_without_fake_live_claims(tmp_path, monkeypatch):
    _clear_live_image_keys(monkeypatch)
    out = tmp_path / "pack"

    pack = write_london_pack(_brief(tmp_path), out, image_provider="gemini")

    first_asset = pack["routes"][0]["assets"][0]
    image_receipts = [receipt for receipt in pack["receipts"] if receipt["kind"] == "image-generation"]
    first_tile = pack["moodboard_tiles"][0]["tiles"][0]
    rendered = json.dumps(pack)

    assert first_asset["kind"] == "visual-direction-board"
    assert first_asset["provider"] == "manual-prompt"
    assert first_asset["requested_provider"] == "gemini"
    assert first_asset["generation_status"] == "fallback_missing_key"
    assert pack["provider_selection"]["selected_provider"] == "gemini"
    assert pack["provider_selection"]["fallback_chain"][0]["ready"] is False
    assert "missing_key" in pack["provider_selection"]["fallback_chain"][0]["reason"]
    assert image_receipts[0]["requested_provider"] == "gemini"
    assert image_receipts[0]["provider"] == "manual-prompt"
    assert image_receipts[0]["status"] == "fallback_missing_key"
    assert image_receipts[0]["fallback_chain"][0]["ready"] is False
    assert image_receipts[0]["deterministic"] is True
    assert pack["evidence_summary"]["live_artifacts"] == []
    assert "gemini image generation was requested" in first_asset["caption"].lower()
    assert first_tile["kind"] == "visual-direction-board"
    assert "not generated concept art" in first_tile["honesty_note"].lower()
    assert "generated_live" not in rendered
    assert "local-system-sketch" not in rendered


def test_openai_generation_uses_direct_http_without_sdk_dependency(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            return json.dumps({"data": [{"b64_json": "ZmFrZS1pbWFnZQ=="}]}).encode("utf-8")

    def fake_urlopen(request, timeout):
        assert request.full_url == "https://api.openai.com/v1/images/generations"
        assert request.get_header("Authorization") == "Bearer openai-secret-value"
        body = json.loads(request.data.decode("utf-8"))
        assert body["model"] == "gpt-image-2"
        assert body["size"] == "1024x1024"
        assert body["quality"] == "medium"
        assert body["output_format"] == "webp"
        assert body["output_compression"] == 70
        assert body["moderation"] == "low"
        assert timeout == 120
        return FakeResponse()

    monkeypatch.setattr("london.image_generation.urllib.request.urlopen", fake_urlopen)
    pack = {
        "title": "Pet weather app",
        "brief": {"text": "Design a weather app for pet owners."},
        "brain_findings": [{"title": "Use clear state labels", "finding": "Make state obvious."}],
        "source_plan": {"sources": [{"name": "Weather reference"}]},
    }
    route = {
        "id": "safe-walk-window",
        "title": "Safe Walk Window",
        "headline": "Show the safest walk window first.",
        "rationale": "Pet owners need a quick go/no-go read.",
        "palette": [{"role": "signal", "name": "Leash Green", "hex": "#2f9b65"}],
    }

    result = generate_route_concept(
        pack,
        route,
        route_index=1,
        provider="openai",
        requested_provider="auto",
        fallback_chain=[{"provider": "openai", "ready": True, "allowed": True}],
        selection_reason="test selection",
        spend_policy=_paid_spend(),
        env={
            "OPENAI_API_KEY": "openai-secret-value",
            "LONDON_OPENAI_IMAGE_SIZE": "1024x1024",
            "LONDON_OPENAI_IMAGE_QUALITY": "medium",
            "LONDON_OPENAI_IMAGE_OUTPUT_FORMAT": "webp",
            "LONDON_OPENAI_IMAGE_OUTPUT_COMPRESSION": "70",
            "LONDON_OPENAI_IMAGE_MODERATION": "low",
        },
    )
    rendered = json.dumps({"asset": result.asset, "receipt": result.receipt})

    assert result.asset["provider"] == "openai"
    assert result.asset["live_artifact"] is True
    assert result.asset["src"].startswith("data:image/webp;base64,")
    assert result.receipt["status"] == "generated_live"
    assert result.receipt["resolved_provider"] == "openai"
    assert result.receipt["request_config"] == {
        "endpoint": "/v1/images/generations",
        "size": "1024x1024",
        "quality": "medium",
        "output_format": "webp",
        "output_compression": 70,
        "moderation": "low",
    }
    assert "fallback_missing_dependency" not in rendered
    assert "openai-secret-value" not in rendered


def test_openai_generation_defaults_to_high_quality_gpt_image_2(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            return json.dumps({"data": [{"b64_json": "ZmFrZS1pbWFnZQ=="}]}).encode("utf-8")

    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8"))
        assert body["model"] == "gpt-image-2"
        assert body["size"] == "3840x2160"
        assert body["quality"] == "high"
        assert timeout == 120
        return FakeResponse()

    monkeypatch.setattr("london.image_generation.urllib.request.urlopen", fake_urlopen)
    pack = {"title": "Pet weather app", "brief": {"text": "Design a weather app for pet owners."}}
    route = {"id": "safe-walk-window", "title": "Safe Walk Window", "headline": "weather app"}

    result = generate_route_concept(
        pack,
        route,
        route_index=1,
        provider="openai",
        requested_provider="openai",
        spend_policy=_paid_spend(),
        env={"OPENAI_API_KEY": "openai-secret-value"},
    )

    assert result.receipt["request_config"] == {
        "endpoint": "/v1/images/generations",
        "size": "3840x2160",
        "quality": "high",
        "output_format": "png",
    }


def test_gemini_generation_uses_pro_image_preview_config_by_default(monkeypatch):
    def fake_urlopen(request, timeout):
        assert request.full_url == "https://generativelanguage.googleapis.com/v1beta/models/gemini-3-pro-image-preview:generateContent"
        body = json.loads(request.data.decode("utf-8"))
        assert body == {
            "contents": [{"parts": [{"text": build_image_prompt(pack, route, artifact_type="generic")}]}],
            "generationConfig": {
                "responseFormat": {
                    "image": {
                        "aspectRatio": "16:9",
                        "imageSize": "4K",
                    }
                }
            },
        }
        assert timeout == 120
        return _fake_gemini_response()

    monkeypatch.setattr("london.image_generation.urllib.request.urlopen", fake_urlopen)
    pack = {"title": "Pet weather app", "brief": {"text": "Design a weather app for pet owners."}}
    route = {"id": "safe-walk-window", "title": "Safe Walk Window", "headline": "weather app"}

    result = generate_route_concept(
        pack,
        route,
        route_index=1,
        provider="gemini",
        requested_provider="gemini",
        spend_policy=_paid_spend(),
        env={"GEMINI_API_KEY": "gemini-secret-value"},
    )
    rendered = json.dumps({"asset": result.asset, "receipt": result.receipt})

    assert result.asset["provider"] == "gemini"
    assert result.receipt["request_config"] == {
        "api_version": "v1beta",
        "endpoint": "/v1beta/models/gemini-3-pro-image-preview:generateContent",
        "payload_mode": "generation_config",
        "response_format": {
            "image": {
                "aspectRatio": "16:9",
                "imageSize": "4K",
            }
        },
    }
    assert result.receipt["attempted_request_configs"] == [result.receipt["request_config"]]
    assert "gemini-secret-value" not in rendered


def test_gemini_generation_supports_explicit_response_modalities(monkeypatch):
    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8"))
        assert body["generationConfig"]["responseModalities"] == ["TEXT", "IMAGE"]
        assert body["generationConfig"]["responseFormat"] == {
            "image": {
                "aspectRatio": "4:5",
                "imageSize": "2K",
            }
        }
        assert timeout == 120
        return _fake_gemini_response()

    monkeypatch.setattr("london.image_generation.urllib.request.urlopen", fake_urlopen)
    pack = {"title": "Pet weather app", "brief": {"text": "Design a weather app for pet owners."}}
    route = {"id": "safe-walk-window", "title": "Safe Walk Window", "headline": "weather app"}

    result = generate_route_concept(
        pack,
        route,
        route_index=1,
        provider="gemini",
        requested_provider="gemini",
        spend_policy=_paid_spend(),
        env={
            "GEMINI_API_KEY": "gemini-secret-value",
            "LONDON_GEMINI_IMAGE_MODEL": "gemini-3.1-flash-image",
            "LONDON_GEMINI_REQUEST_CONFIG_MODE": "configured",
            "LONDON_GEMINI_RESPONSE_MODALITIES": "TEXT,IMAGE",
            "LONDON_GEMINI_IMAGE_ASPECT_RATIO": "4:5",
            "LONDON_GEMINI_IMAGE_SIZE": "2K",
        },
    )

    assert result.asset["provider"] == "gemini"
    assert result.receipt["request_config"] == {
        "api_version": "v1",
        "endpoint": "/v1/models/gemini-3.1-flash-image:generateContent",
        "payload_mode": "generation_config",
        "response_format": {
            "image": {
                "aspectRatio": "4:5",
                "imageSize": "2K",
            }
        },
        "response_modalities": ["TEXT", "IMAGE"],
    }
    assert result.receipt["attempted_request_configs"] == [result.receipt["request_config"]]


def test_gemini_generation_retries_minimal_payload_on_config_shape_400(monkeypatch):
    class ErrorBody:
        def read(self):
            return json.dumps(
                {
                    "error": {
                        "code": 400,
                        "message": (
                            "Invalid JSON payload received. Unknown name "
                            "\"responseModalities\" at 'generation_config': Cannot find field. "
                            "Invalid JSON payload received. Unknown name "
                            "\"responseFormat\" at 'generation_config': Cannot find field."
                        ),
                    }
                }
            ).encode("utf-8")

        def close(self):
            return None

    calls: list[dict] = []

    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8"))
        calls.append(body)
        if len(calls) == 1:
            assert "generationConfig" in body
            raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", {}, ErrorBody())
        assert "generationConfig" not in body
        return _fake_gemini_response()

    monkeypatch.setattr("london.image_generation.urllib.request.urlopen", fake_urlopen)
    pack = {"title": "Pet weather app", "brief": {"text": "Design a weather app for pet owners."}}
    route = {"id": "safe-walk-window", "title": "Safe Walk Window", "headline": "weather app"}

    result = generate_route_concept(
        pack,
        route,
        route_index=1,
        provider="gemini",
        requested_provider="gemini",
        spend_policy=_paid_spend(),
        env={
            "GEMINI_API_KEY": "gemini-secret-value",
            "LONDON_GEMINI_REQUEST_CONFIG_MODE": "configured",
        },
    )
    rendered = json.dumps({"asset": result.asset, "receipt": result.receipt})

    assert len(calls) == 2
    assert result.receipt["status"] == "generated_live"
    assert result.receipt["request_config"]["payload_mode"] == "minimal"
    assert [item["payload_mode"] for item in result.receipt["attempted_request_configs"]] == [
        "generation_config",
        "minimal",
    ]
    assert "gemini-secret-value" not in rendered


def test_gemini_2_image_model_defaults_to_configured_ladder(monkeypatch):
    calls: list[dict] = []

    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8"))
        calls.append(body)
        assert "generationConfig" in body
        return _fake_gemini_response()

    monkeypatch.setattr("london.image_generation.urllib.request.urlopen", fake_urlopen)
    pack = {"title": "Pet weather app", "brief": {"text": "Design a weather app for pet owners."}}
    route = {"id": "safe-walk-window", "title": "Safe Walk Window", "headline": "weather app"}

    result = generate_route_concept(
        pack,
        route,
        route_index=1,
        provider="gemini",
        requested_provider="gemini",
        spend_policy=_paid_spend(),
        env={
            "GEMINI_API_KEY": "gemini-secret-value",
            "LONDON_GEMINI_IMAGE_MODEL": "gemini-2.5-flash-image",
        },
    )

    assert len(calls) == 1
    assert result.receipt["request_config"]["payload_mode"] == "generation_config"


def test_gemini_generation_retries_enum_image_config_when_rest_rejects_literal_values(monkeypatch):
    class ErrorBody:
        def read(self):
            return json.dumps(
                {
                    "error": {
                        "code": 400,
                        "message": (
                            "Invalid value at 'generation_config.response_format.image.aspect_ratio' "
                            '(type.googleapis.com/google.ai.generativelanguage.v1beta.ImageResponseFormat.AspectRatio), "16:9"\\n'
                            "Invalid value at 'generation_config.response_format.image.image_size' "
                            '(type.googleapis.com/google.ai.generativelanguage.v1beta.ImageResponseFormat.ImageSize), "4K"'
                        ),
                        "status": "INVALID_ARGUMENT",
                    }
                }
            ).encode("utf-8")

        def close(self):
            return None

    calls: list[dict] = []

    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8"))
        calls.append(body)
        if len(calls) == 1:
            raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", {}, ErrorBody())
        assert body["generationConfig"]["responseFormat"] == {
            "image": {
                "aspectRatio": "ASPECT_RATIO_SIXTEEN_BY_NINE",
                "imageSize": "IMAGE_SIZE_FOUR_K",
            }
        }
        assert timeout == 120
        return _fake_gemini_response()

    monkeypatch.setattr("london.image_generation.urllib.request.urlopen", fake_urlopen)
    pack = {"title": "Pet weather app", "brief": {"text": "Design a weather app for pet owners."}}
    route = {"id": "safe-walk-window", "title": "Safe Walk Window", "headline": "weather app"}

    result = generate_route_concept(
        pack,
        route,
        route_index=1,
        provider="gemini",
        requested_provider="gemini",
        spend_policy=_paid_spend(),
        env={"GEMINI_API_KEY": "gemini-secret-value"},
    )

    assert len(calls) == 2
    assert calls[0]["generationConfig"]["responseFormat"] == {
        "image": {"aspectRatio": "16:9", "imageSize": "4K"}
    }
    assert result.asset["provider"] == "gemini"
    assert result.receipt["request_config"] == {
        "api_version": "v1beta",
        "endpoint": "/v1beta/models/gemini-3-pro-image-preview:generateContent",
        "payload_mode": "generation_config_enum_retry",
        "response_format": {
            "image": {
                "aspectRatio": "ASPECT_RATIO_SIXTEEN_BY_NINE",
                "imageSize": "IMAGE_SIZE_FOUR_K",
            }
        },
    }
    assert result.receipt["attempted_request_configs"][0]["response_format"] == {
        "image": {"aspectRatio": "16:9", "imageSize": "4K"}
    }
    assert result.receipt["attempted_request_configs"][1] == result.receipt["request_config"]


def test_bfl_generation_requires_paid_policy_before_network(monkeypatch):
    def fail_urlopen(*_args, **_kwargs):
        raise AssertionError("BFL network call should be paid-gated before urlopen")

    monkeypatch.setattr("london.image_generation.urllib.request.urlopen", fail_urlopen)
    pack = {"title": "Pet weather app", "brief": {"text": "Design a weather app for pet owners."}}
    route = {"id": "safe-walk-window", "title": "Safe Walk Window", "headline": "weather app"}

    result = generate_route_concept(
        pack,
        route,
        route_index=1,
        provider="bfl",
        requested_provider="bfl",
        fallback_chain=[{"provider": "bfl", "ready": True, "allowed": False}],
        selection_reason="explicit provider selection",
        spend_policy={"allow_paid": False, "spend_limit_usd": 0.0},
        env={"BFL_API_KEY": "present"},
    )
    rendered = json.dumps({"asset": result.asset, "receipt": result.receipt})

    assert result.asset["provider"] == "manual-prompt"
    assert result.asset["requested_provider"] == "bfl"
    assert result.receipt["status"] == "fallback_paid_provider_blocked"
    assert result.receipt["provider"] == "manual-prompt"
    assert "generated_live" not in rendered
    assert "present" not in rendered


def test_metered_provider_refuses_when_estimate_exceeds_spend_limit_before_network(monkeypatch):
    def fail_urlopen(*_args, **_kwargs):
        raise AssertionError("OpenAI call should be spend-gated before urlopen")

    monkeypatch.setattr("london.image_generation.urllib.request.urlopen", fail_urlopen)
    pack = {"title": "Pet weather app", "brief": {"text": "Design a weather app for pet owners."}}
    route = {"id": "safe-walk-window", "title": "Safe Walk Window", "headline": "weather app"}

    result = generate_route_concept(
        pack,
        route,
        route_index=1,
        provider="openai",
        requested_provider="openai",
        fallback_chain=[{"provider": "openai", "ready": True, "allowed": False}],
        selection_reason="explicit provider selection",
        spend_policy=_paid_spend(limit=0.05, routes=7),
        env={"OPENAI_API_KEY": "present"},
    )

    assert result.asset["provider"] == "manual-prompt"
    assert result.receipt["status"] == "fallback_spend_limit_exceeded"
    assert result.receipt["estimated_cost_usd"] > 0.05
    assert "exceeds spend_limit_usd" in result.receipt["failure"]
    assert result.receipt["request_config"]["routes_to_generate"] == 7


def test_bfl_generation_uses_current_preview_endpoint_and_receipts_polling(monkeypatch):
    calls: list[str] = []

    class Headers:
        def get_content_type(self):
            return "image/png"

    class FakeResponse:
        headers = Headers()

        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            if isinstance(self.payload, bytes):
                return self.payload
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        url = getattr(request, "full_url", str(request))
        calls.append(url)
        if url == "https://api.bfl.ai/v1/flux-2-pro-preview":
            body = json.loads(request.data.decode("utf-8"))
            assert body["width"] == 1536
            assert body["height"] == 1024
            assert timeout == 60
            return FakeResponse({"id": "req-1", "polling_url": "https://api.bfl.ai/v1/get_result?id=req-1"})
        if url == "https://api.bfl.ai/v1/get_result?id=req-1":
            return FakeResponse({"status": "Ready", "result": {"sample": "https://delivery.us.bfl.ai/sample.png"}})
        if url == "https://delivery.us.bfl.ai/sample.png":
            return FakeResponse(b"fake-bfl-image")
        raise AssertionError(f"unexpected BFL URL: {url}")

    monkeypatch.setattr("london.image_generation.urllib.request.urlopen", fake_urlopen)
    pack = {"title": "Pet weather app", "brief": {"text": "Design a weather app for pet owners."}}
    route = {"id": "safe-walk-window", "title": "Safe Walk Window", "headline": "weather app"}

    result = generate_route_concept(
        pack,
        route,
        route_index=1,
        provider="bfl",
        requested_provider="bfl",
        spend_policy=_paid_spend(),
        env={"BFL_API_KEY": "bfl-secret-value"},
    )
    rendered = json.dumps({"asset": result.asset, "receipt": result.receipt})

    assert calls == [
        "https://api.bfl.ai/v1/flux-2-pro-preview",
        "https://api.bfl.ai/v1/get_result?id=req-1",
        "https://delivery.us.bfl.ai/sample.png",
    ]
    assert result.asset["provider"] == "bfl"
    assert result.receipt["model"] == "v1/flux-2-pro-preview"
    assert result.receipt["estimated_cost_usd"] == 0.1
    assert result.receipt["request_config"] == {
        "endpoint": "/v1/flux-2-pro-preview",
        "width": 1536,
        "height": 1024,
        "polling_url_used": True,
        "signed_result_url_stored": False,
    }
    assert "bfl-secret-value" not in rendered
    assert "delivery.us.bfl.ai" not in rendered


def test_automatic1111_generation_uses_txt2img_endpoint(monkeypatch):
    class FakeResponse:
        headers = {"content-type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            return json.dumps(
                {
                    "images": ["ZmFrZS1hMTExMS1pbWFnZQ=="],
                    "info": json.dumps({"sd_model_checkpoint": "london-local-checkpoint"}),
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        assert request.full_url == "http://127.0.0.1:7860/sdapi/v1/txt2img"
        body = json.loads(request.data.decode("utf-8"))
        assert "weather app" in body["prompt"]
        assert timeout == 180
        return FakeResponse()

    monkeypatch.setattr("london.image_generation.urllib.request.urlopen", fake_urlopen)
    pack = {"title": "Pet weather app", "brief": {"text": "Design a weather app for pet owners."}}
    route = {"id": "safe-walk-window", "title": "Safe Walk Window", "headline": "weather app"}

    result = generate_route_concept(pack, route, route_index=1, provider="automatic1111", requested_provider="auto")

    assert result.asset["kind"] == "generated-concept-image"
    assert result.asset["provider"] == "automatic1111"
    assert result.receipt["status"] == "generated_live"
    assert result.receipt["model"] == "london-local-checkpoint"
    assert result.receipt["request_config"]["endpoint"] == "/sdapi/v1/txt2img"
    assert result.receipt["attempted_request_configs"] == [result.receipt["request_config"]]


def test_invalid_local_provider_numeric_env_names_bad_variable():
    pack = {"title": "Pet weather app", "brief": {"text": "Design a weather app for pet owners."}}
    route = {"id": "safe-walk-window", "title": "Safe Walk Window", "headline": "weather app"}

    result = generate_route_concept(
        pack,
        route,
        route_index=1,
        provider="automatic1111",
        requested_provider="automatic1111",
        env={"LONDON_AUTOMATIC1111_STEPS": "abc"},
    )

    assert result.receipt["status"] == "fallback_invalid_env_value"
    assert "LONDON_AUTOMATIC1111_STEPS" in result.receipt["failure"]


def test_comfyui_generation_loads_json_safely_and_polls_history(tmp_path, monkeypatch):
    workflow = tmp_path / "workflow.json"
    workflow.write_text('{"1": {"inputs": {"text": "{{prompt}}"}}}', encoding="utf-8")
    calls: list[str] = []

    class Headers:
        def get_content_type(self):
            return "image/png"

    class FakeResponse:
        def __init__(self, payload, *, binary: bool = False):
            self.payload = payload
            self.binary = binary
            self.headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            if self.binary:
                return self.payload
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        calls.append(url)
        if url == "http://127.0.0.1:8188/prompt":
            body = json.loads(request.data.decode("utf-8"))
            text = body["prompt"]["1"]["inputs"]["text"]
            assert "{{prompt}}" not in text
            assert "\n" in text
            assert "weather app" in text
            return FakeResponse({"prompt_id": "abc123"})
        if url == "http://127.0.0.1:8188/history/abc123":
            return FakeResponse(
                {
                    "abc123": {
                        "outputs": {
                            "9": {
                                "images": [
                                    {"filename": "route.png", "subfolder": "london", "type": "output"}
                                ]
                            }
                        }
                    }
                }
            )
        if url.startswith("http://127.0.0.1:8188/view?"):
            assert "filename=route.png" in url
            return FakeResponse(b"fake-comfy-image", binary=True)
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr("london.image_generation.urllib.request.urlopen", fake_urlopen)
    pack = {"title": "Pet weather app", "brief": {"text": "Design a weather app for pet owners."}}
    route = {"id": "safe-walk-window", "title": "Safe Walk Window", "headline": "weather app"}

    result = generate_route_concept(
        pack,
        route,
        route_index=1,
        provider="comfyui",
        requested_provider="auto",
        env={"LONDON_COMFYUI_WORKFLOW": str(workflow), "LONDON_COMFYUI_POLL_SECONDS": "0"},
    )

    assert result.asset["kind"] == "generated-concept-image"
    assert result.asset["provider"] == "comfyui"
    assert result.receipt["status"] == "generated_live"
    assert calls == [
        "http://127.0.0.1:8188/prompt",
        "http://127.0.0.1:8188/history/abc123",
        "http://127.0.0.1:8188/view?filename=route.png&subfolder=london&type=output",
    ]


def _generate_mocked_comfyui(tmp_path: Path, monkeypatch, env: dict[str, str] | None = None):
    workflow = tmp_path / "private-workflows" / "ideogram-4-london-workflow.json"
    workflow.parent.mkdir()
    workflow.write_text('{"1": {"inputs": {"text": "{{prompt}}"}}}', encoding="utf-8")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            return json.dumps({"image": "ZmFrZS1jb21meXVpLWltYWdl"}).encode("utf-8")

    def fake_urlopen(request, timeout):
        assert request.full_url == "http://127.0.0.1:8188/prompt"
        body = json.loads(request.data.decode("utf-8"))
        assert "{{prompt}}" not in body["prompt"]["1"]["inputs"]["text"]
        assert timeout == 120
        return FakeResponse()

    monkeypatch.setattr("london.image_generation.urllib.request.urlopen", fake_urlopen)
    pack = {"title": "Pet weather app", "brief": {"text": "Design a weather app for pet owners."}}
    route = {"id": "safe-walk-window", "title": "Safe Walk Window", "headline": "weather app"}
    merged_env = {
        "LONDON_COMFYUI_WORKFLOW": str(workflow),
        "LONDON_COMFYUI_POLL_SECONDS": "0",
    }
    merged_env.update(env or {})
    result = generate_route_concept(
        pack,
        route,
        route_index=1,
        provider="comfyui",
        requested_provider="auto",
        env=merged_env,
    )
    return result, workflow


def test_comfyui_receipt_records_workflow_hash_and_model_profile(tmp_path, monkeypatch):
    result, workflow = _generate_mocked_comfyui(
        tmp_path,
        monkeypatch,
        {
            "LONDON_COMFYUI_MODEL_PROFILE": "ideogram-4",
            "LONDON_COMFYUI_MODEL_FAMILY": "ideogram-4",
            "LONDON_COMFYUI_LICENSE_POSTURE": "non-commercial-public-weights",
            "LONDON_COMFYUI_COMMERCIAL_USE": "not-permitted-without-commercial-license",
        },
    )
    request_config = result.receipt["request_config"]

    assert result.asset["provider"] == "comfyui"
    assert result.receipt["provider"] == "comfyui"
    assert result.receipt["model"] == "ideogram-4"
    assert result.receipt["status"] == "generated_live"
    assert request_config["model_profile"] == "ideogram-4"
    assert request_config["model_family"] == "ideogram-4"
    assert request_config["license_posture"] == "non-commercial-public-weights"
    assert request_config["commercial_use"] == "not-permitted-without-commercial-license"
    assert request_config["workflow_sha256"] == hashlib.sha256(workflow.read_bytes()).hexdigest()
    assert request_config["workflow_name"] == workflow.name
    assert request_config["base_url"] == "http://127.0.0.1:8188"


def test_comfyui_receipt_does_not_include_workflow_absolute_path(tmp_path, monkeypatch):
    checkpoint = tmp_path / "private-models" / "ideogram.safetensors"
    result, workflow = _generate_mocked_comfyui(
        tmp_path,
        monkeypatch,
        {
            "LONDON_COMFYUI_MODEL_PROFILE": "ideogram-4",
            "LONDON_COMFYUI_CHECKPOINTS": str(checkpoint),
        },
    )
    rendered = json.dumps(result.receipt, sort_keys=True)

    assert workflow.name in rendered
    assert hashlib.sha256(workflow.read_bytes()).hexdigest() in rendered
    assert str(workflow.parent) not in rendered
    assert str(workflow) not in rendered
    assert str(checkpoint) not in rendered


def test_comfyui_ideogram_receipt_labels_noncommercial_profile(tmp_path, monkeypatch):
    result, _workflow = _generate_mocked_comfyui(
        tmp_path,
        monkeypatch,
        {
            "LONDON_COMFYUI_MODEL_PROFILE": "ideogram-4",
            "LONDON_COMFYUI_MODEL_FAMILY": "ideogram-4",
            "LONDON_COMFYUI_LICENSE_POSTURE": "non-commercial-public-weights",
            "LONDON_COMFYUI_COMMERCIAL_USE": "not-permitted-without-commercial-license",
        },
    )
    request_config = result.receipt["request_config"]
    rendered = json.dumps(result.receipt, sort_keys=True).lower()

    assert request_config["model_profile"] == "ideogram-4"
    assert request_config["license_posture"] == "non-commercial-public-weights"
    assert request_config["commercial_use"] == "not-permitted-without-commercial-license"
    assert "free commercial fallback" not in rendered
    assert request_config["commercial_use"] != "permitted"


def test_comfyui_receipt_defaults_custom_workflow_when_profile_missing(tmp_path, monkeypatch):
    result, workflow = _generate_mocked_comfyui(tmp_path, monkeypatch)
    request_config = result.receipt["request_config"]

    assert result.receipt["model"] == "configured-workflow"
    assert request_config["model_profile"] == "custom-workflow"
    assert request_config["model_family"] == "configured-workflow"
    assert request_config["license_posture"] == "user-supplied-workflow"
    assert request_config["commercial_use"] == "unknown"
    assert request_config["workflow_sha256"] == hashlib.sha256(workflow.read_bytes()).hexdigest()


def test_replicate_generation_polls_pending_prediction(monkeypatch):
    calls: list[str] = []

    class Headers:
        def get_content_type(self):
            return "image/png"

    class FakeResponse:
        def __init__(self, payload, *, binary: bool = False):
            self.payload = payload
            self.binary = binary
            self.headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            if self.binary:
                return self.payload
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        calls.append(url)
        if url.endswith("/predictions"):
            return FakeResponse(
                {
                    "status": "starting",
                    "urls": {"get": "https://api.replicate.com/v1/predictions/abc"},
                    "output": None,
                }
            )
        if url == "https://api.replicate.com/v1/predictions/abc":
            assert request.get_header("Authorization") == "Bearer replicate-secret-value"
            return FakeResponse({"status": "succeeded", "output": ["https://assets.example/route.png"]})
        if url == "https://assets.example/route.png":
            return FakeResponse(b"fake-replicate-image", binary=True)
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr("london.image_generation.urllib.request.urlopen", fake_urlopen)
    pack = {"title": "Pet weather app", "brief": {"text": "Design a weather app for pet owners."}}
    route = {"id": "safe-walk-window", "title": "Safe Walk Window", "headline": "weather app"}

    result = generate_route_concept(
        pack,
        route,
        route_index=1,
        provider="replicate",
        requested_provider="auto",
        spend_policy=_paid_spend(),
        env={"REPLICATE_API_TOKEN": "replicate-secret-value", "LONDON_REPLICATE_POLL_SECONDS": "0"},
    )

    assert result.asset["kind"] == "generated-concept-image"
    assert result.asset["provider"] == "replicate"
    assert result.receipt["status"] == "generated_live"
    assert "replicate-secret-value" not in json.dumps({"asset": result.asset, "receipt": result.receipt})
    assert calls == [
        "https://api.replicate.com/v1/models/black-forest-labs/flux-schnell/predictions",
        "https://api.replicate.com/v1/predictions/abc",
        "https://assets.example/route.png",
    ]


def test_unconfigured_local_providers_export_visual_boards_instead_of_unknown_ready_lanes():
    pack = {"title": "Prompt", "brief": {"text": "A lunchbox ritual kit."}}
    route = {"id": "lunchbox", "title": "Lunchbox Ritual Kit", "headline": "sticker lunchbox"}

    draw = generate_route_concept(pack, route, route_index=1, provider="draw-things", requested_provider="draw-things")
    assert draw.asset["kind"] == "visual-direction-board"
    assert draw.receipt["status"] == "fallback_missing_draw_things_command"
    with pytest.raises(ValueError):
        generate_route_concept(pack, route, route_index=1, provider="invokeai", requested_provider="invokeai")


def test_pollinations_direct_provider_requires_explicit_env_opt_in(monkeypatch):
    pack = {"title": "Prompt", "brief": {"text": "A lunchbox ritual kit."}}
    route = {"id": "lunchbox", "title": "Lunchbox Ritual Kit", "headline": "sticker lunchbox"}

    disabled = generate_route_concept(pack, route, route_index=1, provider="pollinations", requested_provider="pollinations", env={})

    assert disabled.asset["kind"] == "visual-direction-board"
    assert disabled.receipt["status"] == "fallback_experimental_network_disabled"


def test_pollinations_generates_only_with_explicit_experimental_policy(monkeypatch):
    class Headers:
        def get_content_type(self):
            return "image/png"

    class FakeResponse:
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            return b"fake-pollinations-image"

    def fake_urlopen(url, timeout):
        assert "image.pollinations.ai/prompt/" in str(url)
        assert timeout == 120
        return FakeResponse()

    monkeypatch.setattr("london.image_generation.urllib.request.urlopen", fake_urlopen)
    pack = {"title": "Prompt", "brief": {"text": "A lunchbox ritual kit."}}
    route = {"id": "lunchbox", "title": "Lunchbox Ritual Kit", "headline": "sticker lunchbox"}

    result = generate_route_concept(
        pack,
        route,
        route_index=1,
        provider="pollinations",
        requested_provider="pollinations",
        spend_policy={"allow_experimental_free_network": True},
        env={},
    )

    assert result.asset["kind"] == "generated-concept-image"
    assert result.asset["provider"] == "pollinations"
    assert result.receipt["status"] == "generated_live"


def test_perchance_is_manual_prompt_export_only():
    pack = {"title": "Prompt", "brief": {"text": "A lunchbox ritual kit."}}
    route = {"id": "lunchbox", "title": "Lunchbox Ritual Kit", "headline": "sticker lunchbox"}

    result = generate_route_concept(pack, route, route_index=1, provider="perchance", requested_provider="perchance")

    assert result.asset["kind"] == "visual-direction-board"
    assert result.asset["provider"] == "manual-prompt"
    assert result.receipt["provider"] == "manual-prompt"
    assert result.receipt["status"] == "manual_prompt_ready"


def test_generated_image_pack_validates_against_schema(tmp_path, monkeypatch):
    _clear_live_image_keys(monkeypatch)
    out = tmp_path / "pack"

    write_london_pack(_brief(tmp_path), out)

    schema = json.loads((Path(__file__).parents[1] / "schemas" / "london-pack.schema.json").read_text(encoding="utf-8"))
    rendered_pack = json.loads((out / "london-pack.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(rendered_pack)


def test_image_prompt_uses_current_route_brain_and_source_principles(tmp_path):
    pack = write_london_pack(_brief(tmp_path), tmp_path / "pack")
    route = pack["routes"][0]

    prompt = build_image_prompt(pack, route)

    assert route["title"] in prompt
    assert route["headline"] in prompt
    assert pack["brain_findings"][0]["title"] in prompt
    assert pack["source_plan"]["sources"][0]["name"] in prompt
    assert "make it pretty" not in prompt.lower()
    assert "current brief only" in prompt.lower()


def test_image_provider_aliases_are_normalized():
    assert normalize_image_provider("local_deterministic") == "fixture"
    assert normalize_image_provider("local") == "manual-prompt"
    assert normalize_image_provider("perchance") == "manual-prompt"
    assert normalize_image_provider("local-command") == "external-cmd"
    assert normalize_image_provider("external-command") == "external-cmd"
    assert normalize_image_provider("bfl_flux") == "bfl"
    assert normalize_image_provider("flux") == "bfl"


def _captured_session_options(tmp_path, monkeypatch, args: list[str]) -> dict[str, object]:
    captured: dict[str, object] = {}

    def fake_write_london_pack(brief, out, **kwargs):
        captured["brief"] = brief
        captured["out"] = out
        captured.update(kwargs)
        return {}

    monkeypatch.setattr("london.cli.write_london_pack", fake_write_london_pack)
    main([str(_brief(tmp_path)), "--out", str(tmp_path / "pack"), *args])
    return captured


def test_auto_image_provider_keyless_records_selection_receipt(tmp_path, monkeypatch):
    _clear_live_image_keys(monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    out = tmp_path / "pack"

    pack = write_london_pack(_brief(tmp_path), out, image_provider="auto")
    image_receipts = [receipt for receipt in pack["receipts"] if receipt["kind"] == "image-generation"]
    first_asset = pack["routes"][0]["assets"][0]

    assert pack["provider_selection"]["selected_provider"] == "manual-prompt"
    assert first_asset["requested_provider"] == "auto"
    assert first_asset["resolved_provider"] == "manual-prompt"
    assert image_receipts[0]["requested_provider"] == "auto"
    assert image_receipts[0]["resolved_provider"] == "manual-prompt"
    assert image_receipts[0]["fallback_chain"]
    assert image_receipts[0]["spend_policy"]["allow_paid"] is False


def test_auto_image_provider_honors_none_and_fixture_config_modes(tmp_path, monkeypatch):
    _clear_live_image_keys(monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-none"))
    set_config_value("image.primary", "none")

    none_pack = write_london_pack(_brief(tmp_path), tmp_path / "pack-none", image_provider="auto")
    none_asset = none_pack["routes"][0]["assets"][0]

    assert none_pack["provider_selection"]["selected_provider"] == "none"
    assert none_asset["kind"] == "visual-direction-board"
    assert none_asset["generation_status"] == "images_disabled"
    assert none_asset["src"].endswith(".svg")
    assert (tmp_path / "pack-none" / none_asset["src"]).exists()

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-fixture"))
    set_config_value("image.primary", "fixture")

    fixture_pack = write_london_pack(_brief(tmp_path), tmp_path / "pack-fixture", image_provider="auto")
    fixture_asset = fixture_pack["routes"][0]["assets"][0]

    assert fixture_pack["provider_selection"]["selected_provider"] == "fixture"
    assert fixture_asset["kind"] == "fixture-system-sketch"
    assert fixture_asset["src"].endswith(".svg")


def test_explicit_pollinations_uses_config_experimental_opt_in(tmp_path, monkeypatch):
    _clear_live_image_keys(monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    set_config_value("image.allow_experimental_free_network", "true")
    monkeypatch.setattr("london.setup_checks._http_available", lambda _url: False)

    class Headers:
        def get_content_type(self):
            return "image/png"

    class FakeResponse:
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            return b"fake-pollinations-image"

    def fake_urlopen(url, timeout):
        assert "image.pollinations.ai/prompt/" in str(url)
        assert timeout == 120
        return FakeResponse()

    monkeypatch.setattr("london.image_generation.urllib.request.urlopen", fake_urlopen)

    pack = write_london_pack(_brief(tmp_path), tmp_path / "pack", image_provider="pollinations")
    asset = pack["routes"][0]["assets"][0]
    receipt = next(receipt for receipt in pack["receipts"] if receipt.get("kind") == "image-generation")

    assert asset["kind"] == "generated-concept-image"
    assert asset["provider"] == "pollinations"
    assert receipt["status"] == "generated_live"
    assert receipt["spend_policy"]["allow_experimental_free_network"] is True
    assert receipt["request_config"]["endpoint"] == "/prompt"
    assert receipt["attempted_request_configs"] == [receipt["request_config"]]


def test_cli_image_provider_equals_form_is_honored(tmp_path, monkeypatch):
    _clear_live_image_keys(monkeypatch)

    captured = _captured_session_options(tmp_path, monkeypatch, ["--image-provider=gemini"])

    assert captured["image_provider"] == "gemini"
    assert captured["max_generated_routes"] is None


def test_cli_images_modes_are_honored(tmp_path, monkeypatch):
    _clear_live_image_keys(monkeypatch)

    assert _captured_session_options(tmp_path, monkeypatch, ["--images", "auto"])["image_provider"] == "auto"
    assert _captured_session_options(tmp_path, monkeypatch, ["--images=none"])["image_provider"] == "none"
    assert _captured_session_options(tmp_path, monkeypatch, ["--images", "fixture"])["image_provider"] == "fixture"


def test_cli_image_try_writes_visual_board_payload(tmp_path, monkeypatch, capsys):
    _clear_live_image_keys(monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    out = tmp_path / "try"

    main(["image", "try", "kids lunchbox ritual kit", "--provider", "auto-local", "--out", str(out)])
    capsys.readouterr()
    payload = json.loads((out / "image-try.json").read_text(encoding="utf-8"))

    assert payload["asset"]["kind"] == "visual-direction-board"
    assert payload["asset"]["provider"] == "manual-prompt"
    assert payload["asset"]["src"].endswith(".svg")
    assert (out / payload["asset"]["src"]).exists()
    assert payload["provider_selection"]["requested_provider"] == "auto-local"
    assert (out / "prompt.txt").read_text(encoding="utf-8")


def test_cli_image_try_explicit_bfl_requires_paid_policy(tmp_path, monkeypatch, capsys):
    _clear_live_image_keys(monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("BFL_API_KEY", "present")
    monkeypatch.setattr("london.setup_checks._http_available", lambda _url: False)

    def fail_urlopen(*_args, **_kwargs):
        raise AssertionError("BFL image try should not call network without paid config")

    monkeypatch.setattr("london.image_generation.urllib.request.urlopen", fail_urlopen)
    out = tmp_path / "try-bfl"

    main(["image", "try", "kids lunchbox ritual kit", "--provider", "bfl", "--out", str(out)])
    capsys.readouterr()
    payload = json.loads((out / "image-try.json").read_text(encoding="utf-8"))
    rendered = json.dumps(payload)

    assert payload["provider_selection"]["selected_provider"] == "bfl"
    assert payload["provider_selection"]["allow_paid"] is False
    assert payload["provider_selection"]["spend_limit_usd"] == 0.0
    assert payload["provider_selection"]["fallback_chain"][0]["allowed"] is False
    assert payload["asset"]["provider"] == "manual-prompt"
    assert payload["receipt"]["status"] == "fallback_paid_provider_blocked"
    assert "generated_live" not in rendered
    assert "present" not in rendered


def test_cli_image_try_explicit_bfl_accepts_command_spend_policy(tmp_path, monkeypatch, capsys):
    _clear_live_image_keys(monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("BFL_API_KEY", "present")
    monkeypatch.setattr("london.setup_checks._http_available", lambda _url: False)
    calls: list[str] = []

    class Headers:
        def get_content_type(self):
            return "image/png"

    class FakeResponse:
        headers = Headers()

        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            if isinstance(self.payload, bytes):
                return self.payload
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        url = getattr(request, "full_url", str(request))
        calls.append(url)
        if url == "https://api.bfl.ai/v1/flux-2-pro-preview":
            body = json.loads(request.data.decode("utf-8"))
            assert body["width"] == 1536
            assert body["height"] == 1024
            assert timeout == 60
            return FakeResponse({"polling_url": "https://api.bfl.ai/v1/get_result?id=req-1"})
        if url == "https://api.bfl.ai/v1/get_result?id=req-1":
            return FakeResponse({"status": "Ready", "result": {"sample": "https://delivery.us.bfl.ai/sample.png"}})
        if url == "https://delivery.us.bfl.ai/sample.png":
            return FakeResponse(b"fake-bfl-image")
        raise AssertionError(f"unexpected BFL URL: {url}")

    monkeypatch.setattr("london.image_generation.urllib.request.urlopen", fake_urlopen)
    out = tmp_path / "try-bfl-paid"

    main(
        [
            "image",
            "try",
            "kids lunchbox ritual kit",
            "--provider",
            "bfl",
            "--out",
            str(out),
            "--allow-paid",
            "--spend-limit-usd",
            "1.00",
        ]
    )
    capsys.readouterr()
    payload = json.loads((out / "image-try.json").read_text(encoding="utf-8"))
    rendered = json.dumps(payload)

    assert calls == [
        "https://api.bfl.ai/v1/flux-2-pro-preview",
        "https://api.bfl.ai/v1/get_result?id=req-1",
        "https://delivery.us.bfl.ai/sample.png",
    ]
    assert payload["provider_selection"]["selected_provider"] == "bfl"
    assert payload["provider_selection"]["allow_paid"] is True
    assert payload["provider_selection"]["spend_limit_usd"] == 1.0
    assert payload["asset"]["kind"] == "generated-concept-image"
    assert payload["asset"]["provider"] == "bfl"
    assert payload["asset"]["src"].endswith(".png")
    assert (out / payload["asset"]["src"]).exists()
    assert payload["receipt"]["status"] == "generated_live"
    assert payload["receipt"]["request_config"]["signed_result_url_stored"] is False
    assert "delivery.us.bfl.ai" not in rendered
    assert "present" not in rendered


def test_cli_image_try_auto_local_selects_external_cmd_when_ready(tmp_path, monkeypatch, capsys):
    _clear_live_image_keys(monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    script = tmp_path / "write_image.py"
    script.write_text(
        """import argparse
import base64
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--prompt-file")
parser.add_argument("--output")
args = parser.parse_args()
assert Path(args.prompt_file).read_text(encoding="utf-8").strip()
Path(args.output).write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="))
""",
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "LONDON_EXTERNAL_IMAGE_COMMAND",
        f"{sys.executable} {script} --prompt-file {{prompt_file}} --output {{output}}",
    )
    out = tmp_path / "try"

    main(["image", "try", "kids lunchbox ritual kit", "--provider", "auto-local", "--out", str(out)])
    capsys.readouterr()
    payload = json.loads((out / "image-try.json").read_text(encoding="utf-8"))

    assert payload["provider_selection"]["selected_provider"] == "external-cmd"
    assert payload["asset"]["kind"] == "generated-concept-image"
    assert payload["asset"]["provider"] == "external-cmd"
    assert payload["asset"]["src"].endswith(".png")
    assert (out / payload["asset"]["src"]).exists()


def test_cli_image_try_auto_local_prefers_ready_draw_things_over_external_cmd(tmp_path, monkeypatch, capsys):
    _clear_live_image_keys(monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    script = tmp_path / "write_image.py"
    script.write_text(
        """import argparse
import base64
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--cli")
parser.add_argument("--prompt-file")
parser.add_argument("--output")
args = parser.parse_args()
assert args.cli.endswith("draw-things-cli")
assert Path(args.prompt_file).read_text(encoding="utf-8").strip()
Path(args.output).write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="))
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("LONDON_DRAW_THINGS_CLI", str(tmp_path / "draw-things-cli"))
    monkeypatch.setenv(
        "LONDON_DRAW_THINGS_COMMAND",
        f"{sys.executable} {script} --cli {{cli}} --prompt-file {{prompt_file}} --output {{output}}",
    )
    monkeypatch.setenv(
        "LONDON_EXTERNAL_IMAGE_COMMAND",
        f"{sys.executable} {script} --cli ignored --prompt-file {{prompt_file}} --output {{output}}",
    )
    out = tmp_path / "try"

    main(["image", "try", "kids lunchbox ritual kit", "--provider", "auto-local", "--out", str(out)])
    capsys.readouterr()
    payload = json.loads((out / "image-try.json").read_text(encoding="utf-8"))
    rendered = json.dumps(payload)

    assert payload["provider_selection"]["selected_provider"] == "draw-things"
    assert payload["asset"]["kind"] == "generated-concept-image"
    assert payload["asset"]["provider"] == "draw-things"
    assert payload["receipt"]["provider"] == "draw-things"
    assert payload["asset"]["src"].endswith(".png")
    assert str(tmp_path) not in rendered
    assert "/private/" not in rendered


def test_image_materialize_pack_refuses_fake_director_pack(tmp_path, monkeypatch):
    _clear_live_image_keys(monkeypatch)
    source = tmp_path / "source"
    out = tmp_path / "out"
    env_file = tmp_path / "gemini.env"
    env_file.write_text("GEMINI_API_KEY=fake-gemini-key\n", encoding="utf-8")
    write_london_pack(_brief(tmp_path), source, director=FakeDirector(), image_provider="none")

    with pytest.raises(SystemExit) as exc:
        main(
            [
                "image",
                "materialize-pack",
                str(source),
                "--out",
                str(out),
                "--image-provider",
                "gemini",
                "--env-file",
                str(env_file),
            ]
        )

    assert exc.value.code == 2
    assert not out.exists()


def test_image_materialize_pack_generates_recommended_route_with_bound_receipt(tmp_path, monkeypatch):
    _clear_live_image_keys(monkeypatch)
    monkeypatch.setattr("london.setup_checks._http_available", lambda _url: False)
    calls: list[str] = []

    def fake_urlopen(request, timeout):
        calls.append(getattr(request, "full_url", str(request)))
        return _fake_gemini_response()

    monkeypatch.setattr("london.image_generation.urllib.request.urlopen", fake_urlopen)
    source = tmp_path / "source"
    out = tmp_path / "out"
    env_file = tmp_path / "gemini.env"
    env_file.write_text("GEMINI_API_KEY=fake-gemini-key\n", encoding="utf-8")
    write_london_pack(_brief(tmp_path), source, director=FakeDirector(), image_provider="none")
    _mark_pack_real_director(source)

    main(
        [
            "image",
            "materialize-pack",
            str(source),
            "--out",
            str(out),
            "--image-provider",
            "gemini",
            "--env-file",
            str(env_file),
            "--allow-paid",
            "--spend-limit-usd",
            "1.00",
            "--json",
        ]
    )
    pack = json.loads((out / "london-pack.json").read_text(encoding="utf-8"))
    receipts = json.loads((out / "receipts.json").read_text(encoding="utf-8"))
    image_receipts = [receipt for receipt in receipts if receipt.get("kind") == "image-generation"]
    recommended = pack["routes"][0]
    recommended_asset = recommended["assets"][0]
    recommended_receipt = next(receipt for receipt in image_receipts if receipt["route_id"] == recommended["id"])
    asset_path = out / recommended_asset["src"]

    assert calls and all("generativelanguage.googleapis.com" in url for url in calls)
    assert recommended_asset["kind"] == "generated-concept-image"
    assert recommended_asset["receipt_id"] == recommended_receipt["receipt_id"]
    assert recommended_receipt["status"] == "generated_live"
    assert recommended_receipt["provider"] == "gemini"
    assert recommended_receipt["asset_src"] == recommended_asset["src"]
    assert recommended_receipt["asset_sha256"] == hashlib.sha256(asset_path.read_bytes()).hexdigest()
    assert recommended_receipt["request_config"]["endpoint"] == (
        "/v1beta/models/gemini-3-pro-image-preview:generateContent"
    )
    assert all(
        receipt["status"] == "manual_prompt_ready"
        for receipt in image_receipts
        if receipt["route_id"] != recommended["id"]
    )
    assert "fake-gemini-key" not in json.dumps(pack)


def test_max_generated_routes_implies_generation_and_limits_receipts(tmp_path, monkeypatch):
    _clear_live_image_keys(monkeypatch)
    out = tmp_path / "pack"

    pack = write_london_pack(_brief(tmp_path), out, max_generated_routes=1)
    image_receipts = [receipt for receipt in pack["receipts"] if receipt["kind"] == "image-generation"]

    assert len(image_receipts) == len(pack["routes"])
    assert image_receipts[0]["requested_provider"] == "auto"
    assert image_receipts[0]["resolved_provider"] == "manual-prompt"
    assert image_receipts[0]["status"] == "manual_prompt_ready"


def test_max_generated_routes_prioritizes_recommended_route_and_manual_boards_rest(tmp_path, monkeypatch):
    routes = [
        {"id": "route-a", "title": "Route A"},
        {"id": "route-b", "title": "Route B"},
        {"id": "route-c", "title": "Route C"},
    ]

    assert _route_ids_for_image_generation(
        {"recommended_route_ref": "Route B"},
        routes,
        generate_images=True,
        max_generated_routes=1,
    ) == {"route-b"}
    assert _route_ids_for_image_generation(
        {"recommended_route_ref": "Route B"},
        routes,
        generate_images=True,
        max_generated_routes=2,
    ) == {"route-a", "route-b"}

    _clear_live_image_keys(monkeypatch)
    out = tmp_path / "pack"
    pack = write_london_pack(_brief(tmp_path), out, image_provider="gemini", max_generated_routes=1)
    image_receipts = [receipt for receipt in pack["receipts"] if receipt["kind"] == "image-generation"]

    assert len(image_receipts) == len(pack["routes"])
    assert [receipt["status"] for receipt in image_receipts] == ["fallback_missing_key", "manual_prompt_ready"]
    assert image_receipts[1]["requested_provider"] == "manual-prompt"
    assert "images_disabled" not in json.dumps(image_receipts)


def test_fixture_images_are_the_only_path_to_system_sketches(tmp_path, monkeypatch):
    _clear_live_image_keys(monkeypatch)
    out = tmp_path / "pack"

    pack = write_london_pack(_brief(tmp_path), out, image_provider="fixture")
    first_asset = pack["routes"][0]["assets"][0]
    rendered = json.dumps(pack)

    assert first_asset["kind"] == "fixture-system-sketch"
    assert first_asset["src"].endswith(".svg")
    assert (out / first_asset["src"]).exists()
    assert "local-system-sketch" not in rendered


def test_comfyui_detected_without_workflow_vs_ready_with_workflow(tmp_path, monkeypatch):
    monkeypatch.setattr("london.setup_checks._http_available", lambda _url: True)
    detected = collect_setup_status(env={"LONDON_COMFYUI_URL": "http://127.0.0.1:8188"})

    workflow = tmp_path / "workflow.json"
    workflow.write_text('{"1": {"inputs": {"text": "{{prompt}}"}}}', encoding="utf-8")
    ready = collect_setup_status(
        env={
            "LONDON_COMFYUI_URL": "http://127.0.0.1:8188",
            "LONDON_COMFYUI_WORKFLOW": str(workflow),
        }
    )

    detected_comfy = next(provider for provider in detected["providers"] if provider["id"] == "comfyui")
    ready_comfy = next(provider for provider in ready["providers"] if provider["id"] == "comfyui")
    assert detected_comfy["status"] == "detected_needs_setup"
    assert detected_comfy["ready_generate"] is False
    assert ready_comfy["status"] == "ready_generate"
    assert ready_comfy["ready_generate"] is True


def test_external_cmd_generation_reads_prompt_and_returns_local_png(tmp_path):
    script = tmp_path / "write_image.py"
    script.write_text(
        """import argparse
import base64
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--prompt-file")
parser.add_argument("--output")
args = parser.parse_args()
prompt = Path(args.prompt_file).read_text(encoding="utf-8")
assert "London brain findings to translate" in prompt
Path(args.output).write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="))
""",
        encoding="utf-8",
    )
    pack = {
        "title": "Local image pipe",
        "brief": {"text": "A lunchbox ritual kit."},
        "brain_findings": [{"title": "Lunch reveal", "finding": "The reveal needs a visible ritual."}],
        "source_plan": {"sources": [{"name": "Bento reference"}]},
    }
    route = {"id": "lunchbox", "title": "Lunchbox Ritual Kit", "headline": "sticker lunchbox"}

    result = generate_route_concept(
        pack,
        route,
        route_index=1,
        provider="external-cmd",
        requested_provider="auto-local",
        env={
            "LONDON_EXTERNAL_IMAGE_COMMAND": f"{sys.executable} {script} --prompt-file {{prompt_file}} --output {{output}}"
        },
    )
    rendered = json.dumps({"asset": result.asset, "receipt": result.receipt})

    assert result.asset["kind"] == "generated-concept-image"
    assert result.asset["provider"] == "external-cmd"
    assert result.asset["src"].startswith("data:image/png;base64,")
    assert result.receipt["status"] == "generated_live"
    assert result.receipt["external_command"]["name"] == Path(sys.executable).name
    assert result.receipt["external_command"]["output_path_printed"] is False
    assert str(tmp_path) not in rendered
    assert "/private/" not in rendered


def test_draw_things_command_generation_receipts_named_provider_without_paths(tmp_path):
    script = tmp_path / "write_image.py"
    script.write_text(
        """import argparse
import base64
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--cli")
parser.add_argument("--prompt-file")
parser.add_argument("--output")
args = parser.parse_args()
assert args.cli.endswith("draw things cli")
prompt = Path(args.prompt_file).read_text(encoding="utf-8")
assert "London brain findings to translate" in prompt
Path(args.output).write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="))
""",
        encoding="utf-8",
    )
    pack = {
        "title": "Local image pipe",
        "brief": {"text": "A lunchbox ritual kit."},
        "brain_findings": [{"title": "Lunch reveal", "finding": "The reveal needs a visible ritual."}],
        "source_plan": {"sources": [{"name": "Bento reference"}]},
    }
    route = {"id": "lunchbox", "title": "Lunchbox Ritual Kit", "headline": "sticker lunchbox"}
    cli_path = tmp_path / "draw things cli"

    result = generate_route_concept(
        pack,
        route,
        route_index=1,
        provider="draw-things",
        requested_provider="draw-things",
        env={
            "LONDON_DRAW_THINGS_CLI": str(cli_path),
            "LONDON_DRAW_THINGS_COMMAND": f"{sys.executable} {script} --cli {{cli}} --prompt-file {{prompt_file}} --output {{output}}",
        },
    )
    rendered = json.dumps({"asset": result.asset, "receipt": result.receipt})

    assert result.asset["kind"] == "generated-concept-image"
    assert result.asset["provider"] == "draw-things"
    assert result.asset["src"].startswith("data:image/png;base64,")
    assert result.receipt["status"] == "generated_live"
    assert result.receipt["provider"] == "draw-things"
    assert result.receipt["external_command"]["name"] == Path(sys.executable).name
    assert result.receipt["external_command"]["output_path_printed"] is False
    assert str(tmp_path) not in rendered
    assert "/private/" not in rendered


def test_external_cmd_failure_falls_back_to_visual_board_without_path_leakage(tmp_path):
    script = tmp_path / "no_image.py"
    script.write_text("from pathlib import Path\nPath('touched.txt').write_text('no image')\n", encoding="utf-8")
    pack = {"title": "Local image pipe", "brief": {"text": "A lunchbox ritual kit."}}
    route = {"id": "lunchbox", "title": "Lunchbox Ritual Kit", "headline": "sticker lunchbox"}

    result = generate_route_concept(
        pack,
        route,
        route_index=1,
        provider="external-cmd",
        requested_provider="auto-local",
        env={"LONDON_EXTERNAL_IMAGE_COMMAND": f"{sys.executable} {script}"},
    )
    rendered = json.dumps({"asset": result.asset, "receipt": result.receipt})

    assert result.asset["kind"] == "visual-direction-board"
    assert result.asset["provider"] == "manual-prompt"
    assert result.receipt["provider"] == "manual-prompt"
    assert result.receipt["status"] == "fallback_no_image_returned"
    assert "visual direction board" in result.receipt["summary"]
    assert str(tmp_path) not in rendered
    assert "/private/" not in rendered


# =============================================================================
# Phase 4.5 HERO-01 / GATE-03 — build_image_prompt artifact_type branching (RED
# stubs; Wave 0). Clones the :412-423 string-assert honesty idiom. They fail today
# because build_image_prompt has NO artifact_type parameter yet. Wave 3 drives
# them GREEN. Honesty rules ("current brief only", "no fake brand logos…", never
# "make it pretty") MUST hold in every branch.
# =============================================================================

_ARTIFACT_PROMPT_MARKERS = {
    "website": ("web mockup", "full-page", "full page", "landing page"),
    "app": ("product screen", "device", "app screen", "mobile"),
    "product": ("packaging", "vessel", "on-shelf", "on shelf"),
    "brand": ("identity", "symbol", "mark"),
    "generic": ("object", "interface", "service scene"),
}


def test_prompt_artifact_type_branches_subject_and_composition(tmp_path):
    # HERO-01: each type yields a per-type subject/composition marker, while the honesty
    # rules survive in EVERY branch. build_image_prompt(..., artifact_type=t) does not
    # exist yet -> TypeError today (genuinely RED for the missing-param reason).
    pack = write_london_pack(_brief(tmp_path), tmp_path / "pack")
    route = pack["routes"][0]

    for artifact_type, markers in _ARTIFACT_PROMPT_MARKERS.items():
        prompt = build_image_prompt(pack, route, artifact_type=artifact_type)
        lowered = prompt.lower()
        assert any(marker in lowered for marker in markers), (
            f"{artifact_type} prompt must carry a per-type marker (one of {markers})"
        )
        # Honesty rules hold in every branch (clone of :412-423 asserts).
        assert "current brief only" in lowered
        assert "no fake brand logos, no raw archive media, no lorem ipsum" in lowered
        assert "make it pretty" not in lowered


def test_generated_prompt_keeps_proof_metadata_out_of_bitmap(tmp_path):
    pack = write_london_pack(_brief(tmp_path), tmp_path / "pack")
    route = pack["routes"][0]

    prompt = build_image_prompt(pack, route, artifact_type="app")
    lowered = prompt.lower()

    assert "text-free public app/tool scene" in lowered
    assert "text-free by default" in lowered
    assert "allowed visible words: none" in lowered
    assert "do not typeset london's route title" in lowered
    assert "route title is private direction only" in lowered
    assert "keep london prose and supporting proof outside the generated image" in lowered
    assert "leave all london prose, metadata, and proof copy outside the generated image" in lowered
    assert "do not render dense ui copy" in lowered
    assert "no readable dashboards" in lowered
    assert "fake alphabets" in lowered
    assert "font specimen sheets" in lowered
    assert "price tables" in lowered
    assert "receipt/provider/source notes" in lowered
    assert "palette hex codes as visible text" in lowered
    assert "typography specimen" not in lowered
    assert "surrounding evidence details" not in lowered
    assert "palette rail" not in lowered


def test_generated_prompt_keeps_london_words_private_not_typeset(tmp_path):
    pack = {
        "title": "Daily Motivation Notebook",
        "brief": {"text": "Design a daily motivation notebook with cover, prompt pages, and an inside spread."},
    }
    route = {
        "id": "checkout-card",
        "title": "The Checkout Card",
        "headline": "Check the day out, then check it back in.",
        "rationale": "The route turns motivation into a tangible repeat ritual instead of a quote-poster moment.",
        "type": "A compact grotesk makes the card feel procedural without becoming bureaucratic.",
    }

    prompt = build_image_prompt(pack, route, artifact_type="product")
    lowered = prompt.lower()

    assert "the checkout card" in lowered
    assert "check the day out" in lowered
    assert "tangible repeat ritual" in lowered
    assert "allowed visible words: none" in lowered
    assert "not lettering for the bitmap: the checkout card" in lowered
    assert "do not render this as text or headline" in lowered
    assert "translate into materials, hierarchy, framing, and gesture, not words" in lowered
    assert "photographed product/object system in use" in lowered
    assert "blank panels, symbolic marks" in lowered
    assert "no type sheets, fake labels, dense packaging copy" in lowered
    assert "polished product mockup" not in lowered
    assert "logo-forward mockups" in lowered


def test_generated_prompt_artifact_frames_are_concrete_and_anti_text():
    pack = {"title": "Starter", "brief": {"text": "A public starter-set brief."}}
    route = {"id": "route", "title": "Route Name", "headline": "Route headline"}

    product_prompt = build_image_prompt(pack, route, artifact_type="product").lower()
    app_prompt = build_image_prompt(pack, route, artifact_type="app").lower()
    brand_prompt = build_image_prompt(pack, route, artifact_type="brand").lower()
    generic_prompt = build_image_prompt(pack, route, artifact_type="generic").lower()

    assert "one human gesture" in product_prompt
    assert "blank panels" in product_prompt
    assert "no type sheets" in product_prompt
    assert "concrete object/hand/context cue" in app_prompt
    assert "blank cards" in app_prompt
    assert "no readable dashboards" in app_prompt
    assert "simple non-readable symbol/mark" in brand_prompt
    assert "no logo specimen sheets" in brand_prompt
    assert "object, interface, paper, or service artifact in context" in generic_prompt
    for prompt in (product_prompt, app_prompt, brand_prompt, generic_prompt):
        assert "allowed visible words: none" in prompt
        assert "no generic ai mockup defaults" in prompt
        assert "beige product-on-plinth default" in prompt
        assert "lorem ipsum" in prompt


def test_generated_prompt_does_not_feed_section_titles_as_visible_ui_copy():
    pack = {
        "title": "Kiln Ledger",
        "brief": {
            "text": "Create an artist studio budget tool with material batches and price simulation."
        },
    }
    route = {
        "id": "bench-slip",
        "title": "Bench Slip",
        "headline": "Your studio, on the books.",
        "rationale": "A warm studio ledger interface.",
        "sections": [
            {
                "title": "The Bench",
                "body": "A two-second cashflow scan across the top, then batch cards below like slips on a shelf.",
            },
            {
                "title": "Fire the Price",
                "body": "A horizontal slider that moves wholesale, retail, and margin together.",
            },
        ],
    }

    prompt = build_image_prompt(pack, route, artifact_type="app")
    lowered = prompt.lower()

    assert "allowed visible words: none" in lowered
    assert "not lettering for the bitmap: bench slip" in lowered
    assert "private interaction cues" in lowered
    assert "no readable dashboards, tables, numbers, price cards" in lowered
    assert "product/interface moments:" not in lowered
    assert "the bench" not in lowered
    assert "fire the price" not in lowered
    assert "wholesale" not in lowered
    assert "retail" not in lowered
    assert "margin" not in lowered
    assert "cashflow" not in lowered


def test_artifact_type_flows_into_generated_prompt(tmp_path):
    # GATE-03: the renderer/prompt path reads artifact_type AS GIVEN off the pack — no
    # renderer-side re-derivation. Set pack["artifact_type"]="website" and assert the
    # prompt build picks it up (a website marker appears) when artifact_type is read from
    # the pack rather than re-inferred. Fails today (no artifact_type param / no read).
    pack = write_london_pack(_brief(tmp_path), tmp_path / "pack")
    route = pack["routes"][0]
    pack["artifact_type"] = "website"

    prompt = build_image_prompt(pack, route, artifact_type=pack["artifact_type"])
    lowered = prompt.lower()

    assert any(marker in lowered for marker in _ARTIFACT_PROMPT_MARKERS["website"])


# =============================================================================
# Phase 4.5 HERO-02 — generate-by-default-when-ready / honest card zero-spend (RED
# stubs; Wave 0). Mocks the adapter boundary (urlopen) so NO network call happens
# (TST-04). NOTE: the default-on provider ladder already shipped in this codebase
# (RESEARCH C2's premise that the default is False is stale). So these stubs assert
# the genuinely-NEW dimension Wave 2/3 must build:
# the generated/card hero is artifact-TYPED end-to-end (pack carries artifact_type
# as given). They fail today for KeyError: 'artifact_type'. BFL (paid) is never
# auto-fired; Gemini is the free default-on lane.
# =============================================================================


def _fake_gemini_response():
    class Headers:
        def get_content_type(self):
            return "image/png"

    class FakeResponse:
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            return json.dumps(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {"inlineData": {"mimeType": "image/png", "data": "ZmFrZS1nZW1pbmktaW1hZ2U="}}
                                ]
                            }
                        }
                    ]
                }
            ).encode("utf-8")

    return FakeResponse()


def test_default_on_generates_when_provider_ready_zero_network(tmp_path, monkeypatch):
    # HERO-02: with a READY paid-gated Gemini provider and NO --images flag, the default path
    # generates — the hero asset kind is "generated-concept-image" — AND the generated hero
    # is artifact-TYPED (--artifact website carries through to pack["artifact_type"]). NO
    # real network call happens (urlopen mocked). Fails today: KeyError 'artifact_type' —
    # the type does not yet thread end-to-end into the generated path. Wave 2/3 → GREEN.
    _clear_live_image_keys(monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    set_config_value("image.allow_paid", "true")
    set_config_value("image.spend_limit_usd", "1.00")
    # Disable local-provider readiness probes so the only outbound call is the Gemini
    # image-gen adapter (the mocked endpoint below).
    monkeypatch.setattr("london.setup_checks._http_available", lambda _url: False)

    calls: list[str] = []

    def fake_urlopen(request, timeout):
        calls.append(getattr(request, "full_url", str(request)))
        return _fake_gemini_response()

    monkeypatch.setattr("london.image_generation.urllib.request.urlopen", fake_urlopen)

    out = tmp_path / "pack"
    # The live default dispatch: a bare brief, NO --images flag, an explicit --artifact type.
    main([str(_brief(tmp_path)), "--out", str(out), "--artifact", "website"])

    rendered_pack = json.loads((out / "london-pack.json").read_text(encoding="utf-8"))
    first_asset = rendered_pack["routes"][0]["assets"][0]
    # NEW (RED today): the generated hero is artifact-typed end-to-end.
    assert rendered_pack["artifact_type"] == "website"
    # The default-on flip already works — a ready provider generates.
    assert first_asset["kind"] == "generated-concept-image", "default-on must generate when a provider is ready"
    # Every outbound call went to the mocked Gemini endpoint — never a real provider.
    assert calls and all("generativelanguage.googleapis.com" in url for url in calls)


def test_default_path_no_key_is_honest_card_zero_spend(tmp_path, monkeypatch):
    # HERO-02: with NO keys, the default path degrades to an HONEST card (zero spend) and
    # the image-generation adapter is NEVER invoked. The card is artifact-TYPED end-to-end
    # (--artifact website carries to pack["artifact_type"]). _http_available is disabled so
    # no local-provider readiness probe fires (that localhost probe is detection, not spend
    # — the spend boundary is the image-gen provider adapter). Fails today: KeyError
    # 'artifact_type' (the type does not thread into the pack yet). Wave 2 → GREEN.
    _clear_live_image_keys(monkeypatch)
    monkeypatch.setattr("london.setup_checks._http_available", lambda _url: False)

    def fail_urlopen(*_args, **_kwargs):  # pragma: no cover - must never run
        raise AssertionError("keyless default must NEVER call a live image provider (TST-04)")

    monkeypatch.setattr("london.image_generation.urllib.request.urlopen", fail_urlopen)

    out = tmp_path / "pack"
    main([str(_brief(tmp_path)), "--out", str(out), "--artifact", "website"])

    rendered_pack = json.loads((out / "london-pack.json").read_text(encoding="utf-8"))
    first_asset = rendered_pack["routes"][0]["assets"][0]
    # NEW (RED today): the honest card is artifact-typed end-to-end.
    assert rendered_pack["artifact_type"] == "website"
    # Honest keyless floor: visible direction board, manual-prompt provider, zero spend.
    assert rendered_pack["provider_selection"]["selected_provider"] == "manual-prompt"
    assert first_asset["kind"] == "visual-direction-board"
    assert first_asset["provider"] == "manual-prompt"
    assert first_asset["src"].endswith(".svg")
    assert (out / first_asset["src"]).exists()
