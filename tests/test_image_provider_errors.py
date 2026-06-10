import json
import urllib.error
from io import BytesIO

from london.image_generation import _scrub_error, generate_route_concept


def test_gemini_http_error_body_is_scrubbed_into_failure(monkeypatch):
    secret = "gemini-secret-value"

    def fake_urlopen(request, timeout):
        body = b'{"error":{"status":"INVALID_ARGUMENT","message":"bad image config for gemini-secret-value"}}'
        raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", {}, BytesIO(body))

    monkeypatch.setattr("london.image_generation.urllib.request.urlopen", fake_urlopen)
    pack = {"title": "Pet weather app", "brief": {"text": "Design a weather app for pet owners."}}
    route = {"id": "safe-walk-window", "title": "Safe Walk Window", "headline": "weather app"}

    result = generate_route_concept(
        pack,
        route,
        route_index=1,
        provider="gemini",
        requested_provider="gemini",
        spend_policy={"allow_paid": True, "spend_limit_usd": 1.0},
        env={"GEMINI_API_KEY": secret},
    )

    assert result.receipt["status"] == "fallback_provider_error"
    assert "INVALID_ARGUMENT" in result.receipt["failure"]
    assert "bad image config" in result.receipt["failure"]
    assert secret not in json.dumps(result.receipt)


def test_image_provider_error_scrubs_secret_before_truncation_edge():
    secret = "zzzzzzzz-secret-boundary-qqqqqqqq"
    message = ("x" * 230) + secret + " after"

    scrubbed = _scrub_error(RuntimeError(message), {"OPENAI_API_KEY": secret})

    assert "[redacted]" in scrubbed
    assert secret not in scrubbed
    leaked_windows = {secret[index : index + 4] for index in range(0, len(secret) - 3)}
    assert not any(window in scrubbed for window in leaked_windows)


def test_image_provider_error_scrubs_novel_secret_env_name_from_http_body():
    secret = "weird-provider-secret-value"
    body = BytesIO(f'{{"error":"bad key {secret}"}}'.encode("utf-8"))
    exc = urllib.error.HTTPError("https://example.invalid", 400, "Bad Request", {}, body)

    scrubbed = _scrub_error(exc, {"MY_WEIRD_PROVIDER_API_KEY": secret})

    assert "bad key" in scrubbed
    assert "[redacted]" in scrubbed
    assert secret not in scrubbed
