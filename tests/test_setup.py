import json
from types import SimpleNamespace
from pathlib import Path

import pytest

import london.cli as cli
from london.cli import main
from london.config import load_config, set_config_value
from london.director import LondonNoModelError, OfflineDirector
from london.providers import capability_registry, provider_registry
from london.setup_checks import ENV_EXAMPLE_TEXT, collect_setup_status, parse_env_file, sanitize_for_output


def missing_module(_: str) -> bool:
    return False


def present_module(_: str) -> bool:
    return True


def _plain(text: str) -> str:
    """Strip ANSI escapes — rich force-enables terminal styling in CI runners."""
    import re
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def test_provider_registry_lists_local_generators_before_api_lanes():
    providers = provider_registry()

    assert providers[0]["id"] == "local_deterministic"
    assert providers[1]["id"] == "automatic1111"
    assert "external_cmd" in {provider["id"] for provider in providers}
    external = next(provider for provider in providers if provider["id"] == "external_cmd")
    assert external["kind"] == "local"
    assert "image_generation" in external["capabilities"]
    gemini = next(provider for provider in providers if provider["id"] == "gemini")
    assert "GEMINI_API_KEY" in gemini["env_vars"]
    assert "GOOGLE_API_KEY" in gemini["env_vars"]
    assert gemini["python_modules"] == []
    assert "image_generation" in gemini["capabilities"]

    capabilities = {capability["id"] for capability in capability_registry()}
    assert "multimodal_direction" in capabilities
    assert "deterministic_pack" in capabilities
    assert "semantic_london_brain" in capabilities
    image_generation = next(capability for capability in capability_registry() if capability["id"] == "image_generation")
    assert image_generation["mode"] == "hybrid"


def test_missing_live_keys_do_not_block_when_manual_prompt_handoff_passes():
    status = collect_setup_status(env={}, module_finder=missing_module)

    assert status["status"] == "ok"
    assert status["blockers"] == []
    assert status["recommended_provider"] == "manual_prompt"
    assert status["secrets_printed"] is False

    providers = {provider["id"]: provider for provider in status["providers"]}
    checks = {check["id"]: check for check in status["checks"]}
    capabilities = {capability["id"]: capability for capability in status["capabilities"]}
    assert providers["gemini"]["status"] == "missing_key"
    assert providers["gemini"]["optional"] is True
    assert providers["local_deterministic"]["ready"] is True
    assert providers["manual_prompt"]["status"] == "manual_only"
    assert providers["manual_prompt"]["ready"] is True
    assert checks["semantic_london_brain"]["status"] == "warn"
    assert checks["semantic_london_brain"]["blocking"] is False
    assert capabilities["deterministic_pack"]["ready"] is True
    assert capabilities["semantic_london_brain"]["ready"] is False


def test_setup_status_reports_provider_state_labels_and_runtime():
    status = collect_setup_status(env={}, module_finder=missing_module)
    providers = {provider["id"]: provider for provider in status["providers"]}

    assert "runtime" in status
    assert status["verdict"] == "CORE READY"
    assert status["env_policy"]["auto_read_dotenv"] is False
    assert "MISSING" in providers["gemini"]["state_labels"]
    assert "LOCAL" in providers["local_deterministic"]["state_labels"]
    assert "READY" in providers["local_deterministic"]["state_labels"]
    assert providers["automatic1111"]["status"] in {"missing", "detected_needs_setup", "ready_generate"}
    assert providers["automatic1111"]["ready_generate"] is False
    assert providers["external_cmd"]["status"] == "missing"
    assert providers["external_cmd"]["ready_generate"] is False
    assert status["image_generation"]["selected_provider"] == "manual-prompt"
    assert status["setup_profiles"]


def test_setup_human_concierge_is_capability_first_and_ascii(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    for key in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "BFL_API_KEY",
        "OPENAI_API_KEY",
        "FIRECRAWL_API_KEY",
        "FAL_KEY",
        "FAL_API_KEY",
        "REPLICATE_API_TOKEN",
        "REPLICATE_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    main(["setup"])
    output = capsys.readouterr().out

    output.encode("ascii")
    assert "\x1b[" not in output
    assert "Verdict: CORE READY" in output
    assert output.index("Capability map:") < output.index("Provider cards:")
    for label in (
        "Core engine",
        "Local pack builder",
        "Browser capture",
        "Vision reading",
        "Image generation",
        "Web discovery",
        "Design bridges",
    ):
        assert label in output
    assert "[1] Core demo" in output
    assert "[2] Recommended" in output
    assert "[3] Pro image lab" in output
    assert "[4] Details" in output
    normalized = " ".join(output.split())
    assert "Firecrawl" in output
    assert "Discovery and source hydration" in normalized
    assert "does not decide visual truth from branding tokens" in normalized
    assert "Live probes run only with --live" in output
    assert "Metered image disclosure" in output
    assert "london config set image.quality standard" in output
    assert "visual direction boards" in output
    assert "External image command" in output
    assert "london /tmp/london-brief.md --images auto --out /tmp/london-pack" in normalized


def test_json_setup_output_redacts_key_values_and_keeps_key_names():
    env = {
        "GEMINI_API_KEY": "gemini-secret-value",
        "OPENAI_API_KEY": "openai-secret-value",
        "FIRECRAWL_API_KEY": "firecrawl-secret-value",
    }

    status = collect_setup_status(env=env, module_finder=present_module)
    rendered = json.dumps(status, sort_keys=True)

    assert "gemini-secret-value" not in rendered
    assert "openai-secret-value" not in rendered
    assert "firecrawl-secret-value" not in rendered
    assert "GEMINI_API_KEY" in rendered
    assert "OPENAI_API_KEY" in rendered
    assert "FIRECRAWL_API_KEY" in rendered
    assert status["recommended_provider"] == "manual_prompt"
    assert status["image_generation"]["selected_provider"] == "manual-prompt"
    assert status["image_generation"]["price_ceilings_usd"]["gemini"] >= 0.25
    semantic = next(check for check in status["checks"] if check["id"] == "semantic_london_brain")
    semantic_capability = next(
        capability for capability in status["capabilities"] if capability["id"] == "semantic_london_brain"
    )
    assert semantic["status"] == "pass"
    assert "core derived retrieval path" in semantic["message"]
    assert semantic_capability["ready"] is True


def test_sanitize_for_output_scrubs_secret_fields_and_embedded_values():
    payload = {
        "api_key": "raw-secret",
        "message": "provider returned raw-secret in an error",
        "nested": [{"token": "another-secret"}],
    }

    sanitized = sanitize_for_output(payload, secret_values=("raw-secret", "another-secret"))
    rendered = json.dumps(sanitized)

    assert "raw-secret" not in rendered
    assert "another-secret" not in rendered
    assert sanitized["api_key"] == "[redacted]"
    assert sanitized["message"] == "provider returned [redacted] in an error"
    assert sanitized["nested"][0]["token"] == "[redacted]"


def test_gemini_key_is_paid_blocked_without_image_spend_policy():
    status = collect_setup_status(
        env={"GEMINI_API_KEY": "gemini-secret-value"},
        module_finder=missing_module,
    )
    providers = {provider["id"]: provider for provider in status["providers"]}

    assert status["status"] == "ok"
    assert status["blockers"] == []
    assert status["image_generation"]["selected_provider"] == "manual-prompt"
    assert providers["gemini"]["status"] == "paid_blocked"
    assert providers["gemini"]["ready"] is False
    assert providers["gemini"]["ready_generate"] is False
    assert providers["local_deterministic"]["ready"] is True


def test_optional_dependency_gaps_are_reported_but_not_blocking():
    status = collect_setup_status(
        env={"FIRECRAWL_API_KEY": "firecrawl-secret-value"},
        module_finder=missing_module,
    )
    providers = {provider["id"]: provider for provider in status["providers"]}

    assert status["status"] == "ok"
    assert status["blockers"] == []
    assert providers["firecrawl"]["status"] == "missing_dependency"
    assert providers["firecrawl"]["ready"] is False
    assert providers["local_deterministic"]["ready"] is True


def test_env_file_is_explicit_and_secret_safe(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GEMINI_API_KEY=gemini-secret-value\nUNKNOWN_SECRET=should-not-load\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)

    parsed = parse_env_file(env_file)
    status = collect_setup_status(env={}, env_file=env_file, module_finder=present_module)
    rendered = json.dumps(status, sort_keys=True)

    assert parsed["loaded_keys"] == ["GEMINI_API_KEY"]
    assert "UNKNOWN_SECRET" in rendered
    assert "gemini-secret-value" not in rendered
    assert status["env_file"]["loaded_keys"] == ["GEMINI_API_KEY"]
    assert status["env_file"]["loaded"] is True
    assert "UNKNOWN_SECRET" in " ".join(status["env_file"]["warnings"])


def test_env_file_strips_inline_comments_on_unquoted_values(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=placeholder-model-key # local note\n", encoding="utf-8")
    env_file.chmod(0o600)

    parsed = parse_env_file(env_file)

    assert parsed["env"]["GEMINI_API_KEY"] == "placeholder-model-key"


def test_env_file_loads_known_local_generator_settings(tmp_path, monkeypatch):
    workflow = tmp_path / "workflow.json"
    workflow.write_text('{"1": {"inputs": {"text": "{{prompt}}"}}}', encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"LONDON_COMFYUI_URL=http://127.0.0.1:8188\n"
        f"LONDON_COMFYUI_WORKFLOW={workflow}\n"
        "LONDON_COMFYUI_MODEL_PROFILE=ideogram-4\n"
        "LONDON_COMFYUI_MODEL_FAMILY=ideogram-4\n"
        "LONDON_COMFYUI_LICENSE_POSTURE=non-commercial-public-weights\n"
        "LONDON_COMFYUI_COMMERCIAL_USE=not-permitted-without-commercial-license\n"
        "LONDON_COMFYUI_CHECKPOINTS=model-a.safetensors,model-b.safetensors\n"
        "UNKNOWN_SECRET=should-not-load\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    monkeypatch.setattr("london.setup_checks._http_available", lambda url: "8188" in url)

    parsed = parse_env_file(env_file)
    status = collect_setup_status(env={}, env_file=env_file, module_finder=missing_module)
    comfyui = next(provider for provider in status["providers"] if provider["id"] == "comfyui")
    rendered = json.dumps(status, sort_keys=True)

    assert parsed["loaded_keys"] == [
        "LONDON_COMFYUI_CHECKPOINTS",
        "LONDON_COMFYUI_COMMERCIAL_USE",
        "LONDON_COMFYUI_LICENSE_POSTURE",
        "LONDON_COMFYUI_MODEL_FAMILY",
        "LONDON_COMFYUI_MODEL_PROFILE",
        "LONDON_COMFYUI_URL",
        "LONDON_COMFYUI_WORKFLOW",
    ]
    assert status["env_file"]["loaded_keys"] == parsed["loaded_keys"]
    assert comfyui["status"] == "ready_generate"
    assert comfyui["ready_generate"] is True
    assert status["comfyui_setup"]["active_profile"] == {
        "profile": "ideogram-4",
        "model_family": "ideogram-4",
        "license_posture": "non-commercial-public-weights",
        "commercial_use": "not-permitted-without-commercial-license",
        "checkpoint_count": 2,
    }
    assert status["image_generation"]["selected_provider"] == "comfyui"
    assert "UNKNOWN_SECRET" in rendered
    assert "should-not-load" not in rendered
    assert str(workflow.parent) not in rendered


def test_env_file_loads_anthropic_key_into_director_env(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=placeholder-model-key\n", encoding="utf-8")
    env_file.chmod(0o600)
    brief = tmp_path / "brief.md"
    brief.write_text("# Joyful Retro-Futurist Product\n\nBuild a tactile public product system.", encoding="utf-8")

    captured_env: dict[str, str] = {}

    def capture_director_env(*, offline, director, env):
        captured_env.update(env)
        raise LondonNoModelError("stop after env merge")

    monkeypatch.setattr(cli, "_resolve_director", capture_director_env)

    with pytest.raises(LondonNoModelError):
        cli.write_london_pack(brief, tmp_path / "pack", env_file=env_file, assume_yes=True)

    assert captured_env["ANTHROPIC_API_KEY"] == "placeholder-model-key"


def test_director_mode_offline_env_routes_cli_to_offline_director():
    director = cli._resolve_director(
        offline=False,
        director=None,
        env={"LONDON_DIRECTOR_MODE": "offline"},
    )

    assert isinstance(director, OfflineDirector)


def test_env_file_warns_for_unknown_secret_like_key_without_value(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("UNKNOWN_THING_KEY=ignored-placeholder\n", encoding="utf-8")
    env_file.chmod(0o600)

    parsed = parse_env_file(env_file)
    rendered = json.dumps(parsed, sort_keys=True)

    assert parsed["loaded"] is True
    assert parsed["loaded_keys"] == []
    assert "UNKNOWN_THING_KEY" in rendered
    assert "ignored-placeholder" not in rendered


def test_setup_reports_comfyui_profiles():
    status = collect_setup_status(env={}, module_finder=missing_module)
    setup = status["comfyui_setup"]
    profiles = {profile["id"]: profile for profile in setup["profiles"]}

    assert setup["id"] == "comfyui"
    assert setup["recommended"] is True
    assert setup["install_entrypoint"] == "london setup --install comfyui"
    assert {"flux-schnell", "ideogram-4", "hidream-i1"} <= set(profiles)
    assert profiles["flux-schnell"]["license_posture"] == "apache-2.0"
    assert profiles["flux-schnell"]["commercial_use"] == "permitted"
    assert "non-commercial" in profiles["ideogram-4"]["license_posture"]
    assert "license" in profiles["ideogram-4"]["commercial_use"]
    assert "hardware_note" in profiles["hidream-i1"]
    assert setup["secrets_printed"] is False


def test_comfyui_profile_metadata_does_not_leak_paths():
    status = collect_setup_status(
        env={
            "LONDON_COMFYUI_URL": "http://127.0.0.1:8188",
            "LONDON_COMFYUI_WORKFLOW": "/Users/example/private/models/workflows/ideogram.json",  # EXPECTED-FIXTURE
            "LONDON_COMFYUI_MODEL_PROFILE": "ideogram-4",
            "LONDON_COMFYUI_MODEL_FAMILY": "ideogram-4",
            "LONDON_COMFYUI_LICENSE_POSTURE": "non-commercial-public-weights",
            "LONDON_COMFYUI_COMMERCIAL_USE": "not-permitted-without-commercial-license",
            "LONDON_COMFYUI_CHECKPOINTS": "/private/model-a.safetensors,/private/model-b.safetensors",
        },
        module_finder=missing_module,
    )
    rendered = json.dumps(status, sort_keys=True)
    active = status["comfyui_setup"]["active_profile"]

    assert active["profile"] == "ideogram-4"
    assert active["license_posture"] == "non-commercial-public-weights"
    assert active["checkpoint_count"] == 2
    assert "/Users/example/private/models/workflows" not in rendered  # EXPECTED-FIXTURE
    assert "/private/model-a.safetensors" not in rendered
    assert "/private/model-b.safetensors" not in rendered


def test_comfyui_ideogram_profile_is_not_paid_but_is_labeled_noncommercial():
    status = collect_setup_status(
        env={
            "LONDON_COMFYUI_MODEL_PROFILE": "ideogram-4",
            "LONDON_COMFYUI_MODEL_FAMILY": "ideogram-4",
            "LONDON_COMFYUI_LICENSE_POSTURE": "non-commercial-public-weights",
            "LONDON_COMFYUI_COMMERCIAL_USE": "not-permitted-without-commercial-license",
        },
        module_finder=missing_module,
    )
    setup = status["comfyui_setup"]
    ideogram = next(profile for profile in setup["profiles"] if profile["id"] == "ideogram-4")

    assert "paid" not in json.dumps(ideogram).lower()
    assert "non-commercial" in ideogram["license_posture"]
    assert "license" in ideogram["commercial_use"]
    assert setup["active_profile"]["commercial_use"] == "not-permitted-without-commercial-license"


def test_env_file_loads_external_cmd_as_ready_local_provider(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LONDON_EXTERNAL_IMAGE_COMMAND=python fake_writer.py --prompt-file {prompt_file} --output {output}\n"
        "LONDON_EXTERNAL_IMAGE_OUTPUT_DIR=/tmp/london-local-images\n"
        "UNKNOWN_SECRET=should-not-load\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)

    parsed = parse_env_file(env_file)
    status = collect_setup_status(env={}, env_file=env_file, module_finder=missing_module)
    external = next(provider for provider in status["providers"] if provider["id"] == "external_cmd")
    rendered = json.dumps(status, sort_keys=True)

    assert parsed["loaded_keys"] == ["LONDON_EXTERNAL_IMAGE_COMMAND", "LONDON_EXTERNAL_IMAGE_OUTPUT_DIR"]
    assert external["status"] == "ready_generate"
    assert external["ready_generate"] is True
    assert status["image_generation"]["selected_provider"] == "external-cmd"
    assert "UNKNOWN_SECRET" in rendered
    assert "should-not-load" not in rendered


def test_dotenv_is_not_auto_read_by_setup(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "BFL_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / ".env").write_text("GEMINI_API_KEY=gemini-secret-value\n", encoding="utf-8")

    main(["setup", "--json"])
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert payload["image_generation"]["selected_provider"] == "manual-prompt"
    assert "gemini-secret-value" not in output


def test_setup_json_surfaces_direction_mode_presence_only(tmp_path, monkeypatch, capsys):
    # Pitfall 6: setup/doctor must surface WHICH director would run on the default path so
    # a keyless user is not left guessing why the model path hard-errors — without ever
    # printing key material. Mirrors the canonical setup-status idiom (main setup --json →
    # json.loads) and the presence-only secret-safety pattern. This is the runtime proof
    # of piece 5: without it, `pytest tests/test_setup.py` would pass even if the mode
    # were never surfaced.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-secret-value")

    main(["setup", "--json"])
    output = capsys.readouterr().out
    payload = json.loads(output)

    direction = payload["direction_mode"]
    assert direction["id"] == "direction_mode"
    assert direction["mode"] in {"in_session", "claude_cli_print", "api", "none"}
    assert "label" in direction
    assert "hint" in direction
    # Presence-only: the key VALUE never appears anywhere in the printed JSON, only a
    # boolean presence flag.
    assert "anthropic-secret-value" not in output
    assert isinstance(direction["model_key_present"], bool)
    assert direction["secret_values_printed"] is False


def test_direction_mode_status_is_presence_only_with_key_set():
    from london.setup_checks import direction_mode_status

    status = direction_mode_status(
        env={"ANTHROPIC_API_KEY": "anthropic-secret-value"},
        module_finder=missing_module,
    )
    rendered = json.dumps(status)

    # API key present but the SDK is absent → not API-ready; offline always available.
    assert status["mode"] == "none"
    assert status["model_key_present"] is True
    assert status["offline_available"] is True
    assert "anthropic-secret-value" not in rendered


def test_direction_mode_status_requires_runtime_marker_for_in_session(monkeypatch):
    from london.setup_checks import direction_mode_status

    def only_claude_sdk(name: str) -> bool:
        return name == "claude_agent_sdk"

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    no_marker = direction_mode_status(env={}, module_finder=only_claude_sdk)
    assert no_marker["mode"] == "none"
    assert no_marker["in_session_available"] is False
    assert no_marker["runtime_marker_present"] is False

    with_marker = direction_mode_status(env={"CLAUDECODE": "1"}, module_finder=only_claude_sdk)
    assert with_marker["mode"] == "in_session"
    assert with_marker["in_session_available"] is True
    assert with_marker["runtime_marker_present"] is True


def test_direction_mode_status_reports_explicit_claude_cli_print(monkeypatch):
    from london.setup_checks import direction_mode_status

    def only_claude_sdk(name: str) -> bool:
        return name == "claude_agent_sdk"

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    status = direction_mode_status(
        env={"LONDON_CLAUDE_CLI_PRINT": "1"},
        module_finder=only_claude_sdk,
    )

    assert status["mode"] == "claude_cli_print"
    assert status["in_session_available"] is False
    assert status["claude_cli_print_requested"] is True
    assert status["claude_cli_print_available"] is True


def test_setup_json_is_pure_and_support_report_is_secret_safe(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-secret-value")
    report = tmp_path / "support.json"

    main(["setup", "--json", "--support-report", str(report)])
    output = capsys.readouterr().out
    payload = json.loads(output)
    report_text = report.read_text(encoding="utf-8")

    assert payload["secrets_printed"] is False
    assert output.lstrip().startswith("{")
    assert "\x1b[" not in output
    assert "gemini-secret-value" not in output
    assert "gemini-secret-value" not in report_text


def test_setup_human_and_support_report_hide_secret_fragments(tmp_path, monkeypatch, capsys):
    secret = "setup-secret-prefix-middle-suffix"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    report = tmp_path / "support.json"

    main(["setup", "--support-report", str(report)])
    output = capsys.readouterr().out
    report_text = report.read_text(encoding="utf-8")

    assert "Support report written." in output
    assert "Support report written:" not in output
    for fragment in (secret, secret[:12], secret[-12:]):
        assert fragment not in output
        assert fragment not in report_text
    assert '"present": true' in report_text


def test_setup_live_gate_is_explicit_json_and_clean(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    for key in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "BFL_API_KEY",
        "OPENAI_API_KEY",
        "FIRECRAWL_API_KEY",
        "FAL_KEY",
        "FAL_API_KEY",
        "REPLICATE_API_TOKEN",
        "REPLICATE_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    main(["setup", "--json", "--non-interactive"])
    baseline_output = capsys.readouterr()
    baseline_payload = json.loads(baseline_output.out)

    assert "setup" not in baseline_payload
    assert baseline_payload["verdict"] == "CORE READY"
    assert baseline_output.out.lstrip().startswith("{")
    assert "\x1b[" not in baseline_output.out

    with pytest.raises(SystemExit) as exc:
        main(["setup", "--json", "--live", "--non-interactive"])
    live_output = capsys.readouterr()
    live_payload = json.loads(live_output.out)

    assert exc.value.code == 1
    assert live_payload["verdict"] == "LIVE UPGRADES MISSING"
    assert live_payload["setup"]["live_requested"] is True
    assert live_payload["setup"]["live_ready"] is False
    assert live_payload["setup"]["live_provider_ids"] == []
    assert "Traceback" not in live_output.err
    assert "\x1b[" not in live_output.out


def test_setup_live_gate_requires_paid_config_before_bfl_counts(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    for key in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "FIRECRAWL_API_KEY",
        "FAL_KEY",
        "FAL_API_KEY",
        "REPLICATE_API_TOKEN",
        "REPLICATE_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("BFL_API_KEY", "bfl-secret-value")

    with pytest.raises(SystemExit) as missing_paid_exit:
        main(["setup", "--json", "--live", "--non-interactive"])
    missing_paid = json.loads(capsys.readouterr().out)
    bfl_state = next(provider for provider in missing_paid["providers"] if provider["id"] == "bfl_flux")

    assert missing_paid_exit.value.code == 1
    assert missing_paid["verdict"] == "LIVE UPGRADES MISSING"
    assert missing_paid["setup"]["live_provider_ids"] == []
    assert missing_paid["image_generation"]["selected_provider"] == "manual-prompt"
    assert bfl_state["status"] == "paid_blocked"
    assert bfl_state["ready"] is False
    assert bfl_state["ready_generate"] is False

    set_config_value("image.allow_paid", "true")
    set_config_value("image.spend_limit_usd", "1.00")

    main(["setup", "--json", "--live", "--non-interactive"])
    paid_enabled = json.loads(capsys.readouterr().out)

    assert paid_enabled["verdict"] == "CORE READY"
    assert paid_enabled["setup"]["live_provider_ids"] == ["bfl_flux"]
    assert paid_enabled["image_generation"]["allow_paid"] is True


def test_doctor_live_gate_uses_same_paid_bfl_policy_as_setup(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    for key in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "FIRECRAWL_API_KEY",
        "FAL_KEY",
        "FAL_API_KEY",
        "REPLICATE_API_TOKEN",
        "REPLICATE_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("BFL_API_KEY", "bfl-secret-value")

    with pytest.raises(SystemExit) as missing_paid_exit:
        main(["doctor", "--json", "--live"])
    missing_paid = json.loads(capsys.readouterr().out)
    bfl_state = next(provider for provider in missing_paid["providers"] if provider["id"] == "bfl_flux")

    assert missing_paid_exit.value.code == 1
    assert missing_paid["verdict"] == "LIVE UPGRADES MISSING"
    assert missing_paid["doctor"]["live_requested"] is True
    assert missing_paid["doctor"]["live_ready"] is False
    assert missing_paid["doctor"]["live_provider_ids"] == []
    assert missing_paid["image_generation"]["selected_provider"] == "manual-prompt"
    assert bfl_state["status"] == "paid_blocked"
    assert bfl_state["ready"] is False
    assert bfl_state["ready_generate"] is False

    set_config_value("image.allow_paid", "true")
    set_config_value("image.spend_limit_usd", "1.00")

    main(["doctor", "--json", "--live"])
    paid_enabled = json.loads(capsys.readouterr().out)

    assert paid_enabled["verdict"] == "CORE READY"
    assert paid_enabled["doctor"]["live_ready"] is True
    assert paid_enabled["doctor"]["live_provider_ids"] == ["bfl_flux"]
    assert paid_enabled["image_generation"]["allow_paid"] is True


def test_public_setup_provider_config_help_surfaces(capsys):
    help_cases = [
        (["setup", "--help"], "Inspect local capabilities"),
        (["doctor", "--help"], "Run setup diagnostics"),
        (["providers", "--help"], "Inspect and verify optional London providers"),
        (["providers", "list", "--help"], "List provider readiness"),
        (["providers", "recommend", "--help"], "Recommend an image provider lane"),
        (["providers", "verify", "--help"], "Verify one provider"),
        (["config", "--help"], "Manage non-secret London preferences"),
        (["config", "show", "--help"], "Show non-secret London config"),
        (["config", "set", "--help"], "Set a non-secret London config value"),
        (["session", "--help"], "Run London on a brief"),
    ]

    for args, expected in help_cases:
        main(args)
        output = _plain(capsys.readouterr().out)
        assert expected in output
        if args == ["setup", "--help"]:
            assert "--live" in output


def test_root_help_lists_all_real_typer_commands(capsys):
    main(["--help"])
    output = capsys.readouterr().out

    assert "gallery" in output
    assert "launch-gate" in output
    assert "session" in output


def test_providers_bare_json_defaults_to_list(capsys):
    main(["providers", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert "providers" in payload
    assert "image_generation" in payload
    assert payload["providers"][0]["id"] == "local_deterministic"


def test_provider_verify_accepts_fixture_registry_alias(capsys):
    main(["providers", "verify", "--provider", "local_deterministic", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["provider"] == "fixture"
    assert payload["registry_id"] == "local_deterministic"
    assert payload["ready"] is True
    assert payload["ready_generate"] is False
    assert payload["secrets_printed"] is False


def test_setup_json_verify_providers_exits_nonzero_without_traceback(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "BFL_API_KEY", "OPENAI_API_KEY", "FIRECRAWL_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(SystemExit) as exc:
        main(["setup", "--json", "--verify-providers"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exc.value.code == 1
    assert payload["image_generation"]["selected_provider"] == "manual-prompt"
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out


def test_live_failure_paths_are_clean_json_exits(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "BFL_API_KEY", "OPENAI_API_KEY", "FIRECRAWL_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(SystemExit) as doctor_exit:
        main(["doctor", "--json", "--live"])
    doctor_output = capsys.readouterr()
    doctor_payload = json.loads(doctor_output.out)

    assert doctor_exit.value.code == 1
    assert doctor_payload["doctor"]["live_requested"] is True
    assert "Traceback" not in doctor_output.err

    with pytest.raises(SystemExit) as verify_exit:
        main(["providers", "verify", "--provider", "gemini", "--json"])
    verify_output = capsys.readouterr()
    verify_payload = json.loads(verify_output.out)

    assert verify_exit.value.code == 1
    assert verify_payload["provider"] == "gemini"
    assert verify_payload["ready"] is False
    assert "Traceback" not in verify_output.err


def test_setup_and_config_user_input_errors_are_clean_exits(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    with pytest.raises(SystemExit) as missing_env_exit:
        main(["setup", "--env-file", str(tmp_path / "missing.env")])
    missing_env = capsys.readouterr()

    assert missing_env_exit.value.code == 2
    assert "Env file not found" in missing_env.err
    assert "Traceback" not in missing_env.err

    with pytest.raises(SystemExit) as config_set_exit:
        main(["config", "set", "image.primary", "sk-secret-value"])
    config_set = capsys.readouterr()

    assert config_set_exit.value.code == 2
    assert "Unknown image provider choice" in config_set.err
    assert "sk-secret-value" not in config_set.err
    assert "Traceback" not in config_set.err

    with pytest.raises(SystemExit) as spend_limit_exit:
        main(["config", "set", "image.spend_limit_usd", "sk-secret-value"])
    spend_limit = capsys.readouterr()

    assert spend_limit_exit.value.code == 2
    assert "image.spend_limit_usd requires a non-negative number" in spend_limit.err
    assert "sk-secret-value" not in spend_limit.err
    assert "Traceback" not in spend_limit.err

    config_dir = tmp_path / "bad-config" / "london"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text('[image]\nprimary = "sk-secret-value"\n', encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "bad-config"))

    with pytest.raises(SystemExit) as bad_config_exit:
        main(["setup", "--json"])
    bad_config = capsys.readouterr()

    assert bad_config_exit.value.code == 2
    assert "Unknown image provider choice" in bad_config.err
    assert "sk-secret-value" not in bad_config.err
    assert "Traceback" not in bad_config.err


def test_env_example_and_setup_plan_do_not_teach_shell_history_leaks(capsys):
    assert ENV_EXAMPLE_TEXT == "GEMINI_API_KEY=\nBFL_API_KEY=\nOPENAI_API_KEY=\nFIRECRAWL_API_KEY=\n"
    assert Path(".env.example").read_text(encoding="utf-8") == ENV_EXAMPLE_TEXT

    main(["setup", "--plan"])
    output = capsys.readouterr().out

    assert "cp .env.example .env" in output
    assert "chmod 600 .env" in output
    assert "$EDITOR .env" in output
    assert "echo" not in output.lower()


def test_setup_plan_verify_providers_exits_nonzero_without_traceback(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "BFL_API_KEY", "OPENAI_API_KEY", "FIRECRAWL_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(SystemExit) as excinfo:
        main(["setup", "--plan", "--verify-providers"])

    captured = capsys.readouterr()
    assert excinfo.value.code == 1
    assert "Traceback" not in captured.err


def test_bfl_is_not_auto_primary_unless_paid_use_is_explicit():
    key_env = {"BFL_API_KEY": "bfl-secret-value"}
    gemini_and_bfl_env = {"GEMINI_API_KEY": "gemini-secret-value", "BFL_API_KEY": "bfl-secret-value"}
    default_status = collect_setup_status(env=key_env, module_finder=present_module)
    paid_auto_status = collect_setup_status(
        env=key_env,
        module_finder=present_module,
        config={
            "image": {
                "primary": "auto",
                "backups": ["gemini", "openai", "manual-prompt"],
                "allow_paid": True,
                "spend_limit_usd": 1.0,
            }
        },
    )
    paid_auto_with_gemini_status = collect_setup_status(
        env=gemini_and_bfl_env,
        module_finder=present_module,
        config={
            "image": {
                "primary": "auto",
                "backups": ["gemini", "openai", "manual-prompt"],
                "allow_paid": True,
                "spend_limit_usd": 1.0,
            }
        },
    )
    paid_without_spend_status = collect_setup_status(
        env=key_env,
        module_finder=present_module,
        config={
            "image": {
                "primary": "auto",
                "backups": ["gemini", "openai", "manual-prompt"],
                "allow_paid": True,
                "spend_limit_usd": 0.0,
            }
        },
    )
    paid_without_spend_primary_status = collect_setup_status(
        env=key_env,
        module_finder=present_module,
        config={
            "image": {
                "primary": "bfl",
                "backups": ["gemini", "manual-prompt"],
                "allow_paid": True,
                "spend_limit_usd": 0.0,
            }
        },
    )
    paid_status = collect_setup_status(
        env=key_env,
        module_finder=present_module,
        config={
            "image": {
                "primary": "bfl",
                "backups": ["gemini", "manual-prompt"],
                "allow_paid": True,
                "spend_limit_usd": 1.0,
            }
        },
    )

    assert default_status["image_generation"]["selected_provider"] == "manual-prompt"
    default_bfl = next(provider for provider in default_status["providers"] if provider["id"] == "bfl_flux")
    assert default_bfl["status"] == "paid_blocked"
    assert default_bfl["ready_generate"] is False
    assert paid_without_spend_status["image_generation"]["selected_provider"] == "manual-prompt"
    assert all(
        item["provider"] != "bfl"
        for item in paid_without_spend_status["image_generation"]["fallback_chain"]
    )
    assert paid_without_spend_primary_status["image_generation"]["selected_provider"] == "manual-prompt"
    no_spend_primary_chain_bfl = next(
        item for item in paid_without_spend_primary_status["image_generation"]["fallback_chain"] if item["provider"] == "bfl"
    )
    assert no_spend_primary_chain_bfl["allowed"] is False
    assert no_spend_primary_chain_bfl["ready_generate"] is False
    assert "spend_limit_usd > 0" in no_spend_primary_chain_bfl["reason"]
    assert paid_auto_status["image_generation"]["selected_provider"] == "bfl"
    assert any(item["provider"] == "bfl" for item in paid_auto_status["image_generation"]["fallback_chain"])
    assert paid_auto_with_gemini_status["image_generation"]["selected_provider"] == "gemini"
    assert paid_status["image_generation"]["selected_provider"] == "bfl"
    assert paid_status["image_generation"]["allow_paid"] is True


def test_config_set_writes_non_secret_image_preferences(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    set_config_value("image.primary", "gemini")
    set_config_value("image.backups", "openai,manual-prompt")
    set_config_value("image.allow_paid", "true")
    set_config_value("image.spend_limit_usd", "1.25")
    set_config_value("image.allow_experimental_free_network", "true")
    config = load_config(env={"XDG_CONFIG_HOME": str(tmp_path / "config")})

    assert config["image"]["primary"] == "gemini"
    assert config["image"]["backups"] == ["openai", "manual-prompt"]
    assert config["image"]["allow_paid"] is True
    assert config["image"]["spend_limit_usd"] == 1.25
    assert config["image"]["allow_experimental_free_network"] is True


def test_providers_detect_local_json_reports_generator_readiness(monkeypatch, capsys):
    monkeypatch.delenv("LONDON_AUTOMATIC1111_URL", raising=False)

    main(["providers", "detect", "--local", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["local_only"] is True
    assert payload["secrets_printed"] is False
    ids = {provider["id"] for provider in payload["providers"]}
    assert ids == {"automatic1111", "comfyui", "external_cmd", "draw_things"}
    assert all("ready_generate" in provider for provider in payload["providers"])


def test_detected_but_unimplemented_local_generators_are_not_selected_ready():
    status = collect_setup_status(
        env={
            "LONDON_DRAW_THINGS_CLI": "/bin/echo",
            "LONDON_DRAW_THINGS_READY": "true",
        },
        module_finder=missing_module,
    )
    providers = {provider["id"]: provider for provider in status["providers"]}

    assert providers["draw_things"]["status"] == "detected_needs_setup"
    assert providers["draw_things"]["ready_generate"] is False
    assert "invokeai" not in providers
    assert status["image_generation"]["selected_provider"] == "manual-prompt"


def test_draw_things_macos_missing_binary_recommends_install_without_ready(monkeypatch):
    monkeypatch.setattr("london.setup_checks.platform.system", lambda: "Darwin")
    monkeypatch.setattr("london.setup_checks.shutil.which", lambda _name: None)

    status = collect_setup_status(env={}, module_finder=missing_module)
    providers = {provider["id"]: provider for provider in status["providers"]}

    assert providers["draw_things"]["status"] == "missing"
    assert providers["draw_things"]["ready_generate"] is False
    assert status["draw_things_setup"]["recommended"] is True
    assert status["draw_things_setup"]["install_entrypoint"] == "london setup --install draw-things"


def test_draw_things_binary_only_is_detected_not_ready(monkeypatch):
    monkeypatch.setattr(
        "london.setup_checks.shutil.which",
        lambda name: "/usr/local/bin/draw-things-cli" if name == "draw-things-cli" else None,
    )

    status = collect_setup_status(env={"LONDON_DRAW_THINGS_READY": "true"}, module_finder=missing_module)
    providers = {provider["id"]: provider for provider in status["providers"]}

    assert providers["draw_things"]["status"] == "detected_needs_setup"
    assert providers["draw_things"]["ready_generate"] is False
    assert status["image_generation"]["selected_provider"] == "manual-prompt"


def test_draw_things_command_and_cli_are_ready_and_selected(monkeypatch):
    monkeypatch.setattr("london.setup_checks.shutil.which", lambda _name: None)

    status = collect_setup_status(
        env={
            "LONDON_DRAW_THINGS_CLI": "/Applications/Draw Things CLI.app/Contents/MacOS/draw-things-cli",
            "LONDON_DRAW_THINGS_COMMAND": "{cli} --prompt-file {prompt_file} --output {output}",
        },
        module_finder=missing_module,
    )
    providers = {provider["id"]: provider for provider in status["providers"]}

    assert providers["draw_things"]["status"] == "ready_generate"
    assert providers["draw_things"]["ready_generate"] is True
    assert status["image_generation"]["selected_provider"] == "draw-things"
    assert status["recommended_provider"] == "draw_things"


def test_draw_things_command_missing_output_placeholder_is_not_ready(monkeypatch):
    monkeypatch.setattr("london.setup_checks.shutil.which", lambda _name: "/usr/local/bin/draw-things-cli")

    status = collect_setup_status(
        env={"LONDON_DRAW_THINGS_COMMAND": "{cli} --prompt-file {prompt_file}"},
        module_finder=missing_module,
    )
    providers = {provider["id"]: provider for provider in status["providers"]}

    assert providers["draw_things"]["status"] == "detected_needs_setup"
    assert providers["draw_things"]["ready_generate"] is False


def test_external_cmd_local_generator_is_selected_when_configured():
    status = collect_setup_status(
        env={"LONDON_EXTERNAL_IMAGE_COMMAND": "python fake_writer.py --prompt-file {prompt_file} --output {output}"},
        module_finder=missing_module,
    )
    providers = {provider["id"]: provider for provider in status["providers"]}

    assert providers["external_cmd"]["status"] == "ready_generate"
    assert providers["external_cmd"]["ready_generate"] is True
    assert status["image_generation"]["selected_provider"] == "external-cmd"
    assert any(item["provider"] == "external-cmd" for item in status["image_generation"]["fallback_chain"])


def test_setup_install_draw_things_machine_modes_never_install(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    def fail_run(*_args, **_kwargs):
        raise AssertionError("machine-mode setup must not run Homebrew")

    monkeypatch.setattr("london.cli.subprocess.run", fail_run)

    main(["setup", "--json", "--install", "draw-things", "--non-interactive"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["setup_install"]["target"] == "draw-things"
    assert payload["setup_install"]["status"] == "skipped_machine_mode"
    assert payload["setup_install"]["mutated"] is False


def test_setup_install_comfyui_machine_mode_never_installs(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    def fail_run(*_args, **_kwargs):
        raise AssertionError("ComfyUI setup guidance must not run subprocess installers")

    monkeypatch.setattr("london.cli.subprocess.run", fail_run)

    main(["setup", "--json", "--install", "comfyui", "--non-interactive"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["setup_install"]["target"] == "comfyui"
    assert payload["setup_install"]["status"] == "skipped_machine_mode"
    assert payload["setup_install"]["install_commands"] == ["pip install comfy-cli", "comfy install", "comfy launch"]
    assert payload["setup_install"]["mutated"] is False
    assert payload["setup_install"]["secrets_printed"] is False


def test_setup_install_comfyui_human_mode_returns_manual_steps(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("CI", raising=False)

    def fail_run(*_args, **_kwargs):
        raise AssertionError("ComfyUI manual guidance must not run subprocess installers")

    monkeypatch.setattr("london.cli.subprocess.run", fail_run)

    main(["setup", "--install", "comfy"])
    output = capsys.readouterr().out

    assert "ComfyUI install: manual steps only" in output
    assert "comfy-cli" in output
    assert "comfy install" in output
    assert "comfy launch" in output
    assert "LONDON_COMFYUI_URL" in output


def test_setup_install_draw_things_homebrew_missing_prints_guidance(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr("london.cli.shutil.which", lambda _name: None)

    def fail_run(*_args, **_kwargs):
        raise AssertionError("missing Homebrew path must not run an installer")

    monkeypatch.setattr("london.cli.subprocess.run", fail_run)

    main(["setup", "--install", "draw-things"])
    output = capsys.readouterr().out

    assert "Draw Things install: Homebrew not found" in output
    assert "brew install drawthingsai/draw-things/draw-things-cli" in " ".join(output.split())


def test_setup_install_draw_things_runs_homebrew_when_allowed(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr("london.cli.shutil.which", lambda name: "/opt/homebrew/bin/brew" if name == "brew" else None)
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(list(argv))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("london.cli.subprocess.run", fake_run)

    main(["setup", "--install", "draw-things"])
    output = capsys.readouterr().out

    assert calls == [["/opt/homebrew/bin/brew", "install", "drawthingsai/draw-things/draw-things-cli"]]
    assert "Draw Things install: completed" in output


def test_none_and_fixture_config_choices_are_honored():
    none_status = collect_setup_status(
        env={},
        module_finder=missing_module,
        config={
            "image": {
                "primary": "none",
                "backups": ["manual-prompt"],
                "allow_paid": False,
                "spend_limit_usd": 0.0,
            }
        },
    )
    fixture_status = collect_setup_status(
        env={},
        module_finder=missing_module,
        config={
            "image": {
                "primary": "fixture",
                "backups": ["manual-prompt"],
                "allow_paid": False,
                "spend_limit_usd": 0.0,
            }
        },
    )

    assert none_status["image_generation"]["selected_provider"] == "none"
    assert none_status["image_generation"]["fallback_chain"][0]["reason"] == "images disabled"
    assert fixture_status["image_generation"]["selected_provider"] == "fixture"
    assert fixture_status["image_generation"]["fallback_chain"][0]["reason"] == "fixture sketch mode"


def test_pollinations_requires_explicit_experimental_network_config():
    default_status = collect_setup_status(env={}, module_finder=present_module)
    enabled_status = collect_setup_status(
        env={},
        module_finder=present_module,
        config={
            "image": {
                "primary": "pollinations",
                "backups": ["manual-prompt"],
                "allow_paid": False,
                "spend_limit_usd": 0.0,
                "allow_experimental_free_network": True,
            }
        },
    )
    default_pollinations = next(provider for provider in default_status["providers"] if provider["id"] == "pollinations")
    enabled_pollinations = next(provider for provider in enabled_status["providers"] if provider["id"] == "pollinations")

    assert default_pollinations["status"] == "detected_needs_setup"
    assert default_pollinations["ready_generate"] is False
    assert enabled_pollinations["status"] == "ready_generate"
    assert enabled_pollinations["ready_generate"] is True
    assert enabled_status["image_generation"]["selected_provider"] == "pollinations"


def test_provider_docs_describe_ladder_boundaries():
    text = Path("docs/providers.md").read_text(encoding="utf-8")

    assert "visual direction board" in text
    assert "LONDON_EXTERNAL_IMAGE_COMMAND" in text
    assert "Draw Things" in text and "LONDON_DRAW_THINGS_COMMAND" in text
    assert "recommended free/local mac path" in text.lower()
    assert "detected_needs_setup" in text
    assert "InvokeAI" in text and "detected" in text
    assert "Pollinations" in text and "opt-in" in text
    assert "Perchance" in text and "manual-only" in text
    assert "image.allow_paid" in text
    assert "image.spend_limit_usd" in text
