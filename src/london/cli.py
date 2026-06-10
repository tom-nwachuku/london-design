from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import typer
from rich.console import Console
from typer.core import TyperGroup

# Typer bundles a fork of click as ``typer._click``; the public ``click`` package is a
# separate install and its exceptions are NOT the same objects.  Import UsageError from
# wherever typer actually raises it so the ``except`` clause is guaranteed to fire.
try:
    from typer._click.exceptions import UsageError as _ClickUsageError  # type: ignore[import]
except ImportError:  # pragma: no cover — fallback for future typer versions that re-unify
    import click as _click_fallback
    _ClickUsageError = _click_fallback.UsageError  # type: ignore[assignment]

from london import pack_build as _pack_build
from london import brain_loader
from london.brain import LondonBrain
from london.companion import (
    MODEL_PATH_UNAVAILABLE,
    TOKEN_COST_CAVEAT,
    gate_for_pack,
    load_pack as load_companion_pack,
    start_companion_server,
)
from london.config import default_config_path, load_config, set_config_value
from london.director import (
    CreativeDirector,
)
from london.errors import LondonError, LondonUsageError
from london.image_generation import (
    METERED_IMAGE_PROVIDERS,
    build_image_prompt,
    generate_route_concept,
    normalize_image_provider,
)
from london.intake import build_intake_markdown, write_intake_html
from london.launch import evaluate_launch_gates
from london.gallery import write_gallery
from london.library import (
    DEFAULT_CHROMA_DIR,
    readonly_sqlite_uri,
)
from london.setup_checks import (
    ENV_EXAMPLE_TEXT,
    collect_setup_status,
    merge_env_file,
    write_support_report,
)
from london.text import display_text
from london.validation import run_chassis_validation
from london.workbench import enrich_workbench_pack

class LondonTyperGroup(TyperGroup):
    """Route bare brief invocations to the real session subcommand."""

    def resolve_command(self, ctx: typer.Context, args: list[str]) -> tuple[str | None, Any, list[str]]:
        if args and args[0] not in self.commands and args[0] not in HELP_FLAGS:
            args.insert(0, "session")
        return super().resolve_command(ctx, args)


app = typer.Typer(
    name="london",
    cls=LondonTyperGroup,
    help="London Osei creative director: research, direction, dossier, prototype, and handoff.",
    no_args_is_help=True,
)
brain_app = typer.Typer(help="Inspect and query the sanitized London brain.")
providers_app = typer.Typer(help="Inspect and verify optional London providers.")
config_app = typer.Typer(help="Manage non-secret London preferences.")
image_app = typer.Typer(help="Try image provider prompts and generation lanes.")
gallery_app = typer.Typer(help="Build public proof galleries from London packs.")
app.add_typer(brain_app, name="brain")
app.add_typer(providers_app, name="providers")
app.add_typer(config_app, name="config")
app.add_typer(image_app, name="image")
app.add_typer(gallery_app, name="gallery")

console = Console()
HELP_FLAGS = {"--help", "-h"}
TYPER_COMMANDS = {
    "setup",
    "doctor",
    "session",
    "intake",
    "show-me",
    "launch-gate",
    "gallery",
    "validate-chassis",
    "brain",
    "providers",
    "config",
    "image",
}


def main(argv: list[str] | None = None) -> None:
    """Console-script shim preserving bare ``london brief.md`` UX."""
    try:
        args = list(sys.argv[1:] if argv is None else argv)
        if not args:
            app(args=["--help"], prog_name="london", standalone_mode=False)
            return
        # Map bare -h to the standard --help flag so typer renders help (exit 0)
        # instead of treating it as an unknown command and raising UsageError.
        args = ["--help" if a == "-h" else a for a in args]
        if args[0] == "providers" and (
            len(args) == 1 or (args[1].startswith("-") and args[1] not in HELP_FLAGS)
        ):
            args = ["providers", "list", *args[1:]]
        if args[0] == "config" and len(args) == 1:
            args = ["config", "show"]
        routed_args = args if args[0] in TYPER_COMMANDS or args[0] in HELP_FLAGS else ["session", *args]
        app(args=routed_args, prog_name="london", standalone_mode=False)
    except typer.Exit as exc:
        raise SystemExit(exc.exit_code or 0) from None
    except typer.BadParameter as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise SystemExit(2) from None
    except _ClickUsageError as exc:
        typer.echo(f"Error: {exc.format_message()}", err=True)
        raise SystemExit(2) from None
    except LondonError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from None
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise SystemExit(2) from None


def _main(argv: list[str] | None = None) -> None:
    """Backward-compatible test helper; public execution goes through Typer."""
    args = list(sys.argv[1:] if argv is None else argv)
    main(args)


DRAW_THINGS_BREW_INSTALL = "brew install drawthingsai/draw-things/draw-things-cli"
COMFYUI_INSTALL_COMMANDS = ("pip install comfy-cli", "comfy install", "comfy launch")
_LOCAL_FONT_EXTENSIONS = {".otf", ".ttf", ".woff", ".woff2"}


def _normalize_cli_image_provider(value: str) -> str:
    if value.strip().lower() in {"auto", "auto-local"}:
        return "auto"
    try:
        return normalize_image_provider(value)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _image_mode_to_provider(images: str | None, image_provider: str | None) -> str | None:
    if images is None:
        return image_provider
    mode = images.strip().lower().replace("_", "-")
    if mode not in {"auto", "none", "fixture"}:
        raise typer.BadParameter("--images requires one of: auto, none, fixture")
    return mode if image_provider is None else image_provider


def _run_show_me(
    pack_path: Path,
    *,
    out: Path | None = None,
    ack_token_cost: bool = False,
    json_output: bool = False,
    dry_run: bool = False,
    host: str = "127.0.0.1",
    port: int = 0,
    timeout: int = 300,
) -> None:
    out = out or (pack_path if pack_path.is_dir() else pack_path.parent)
    pack = load_companion_pack(pack_path)
    gate = gate_for_pack(pack, ack_token_cost=ack_token_cost)
    if dry_run or not gate.started:
        if json_output:
            typer.echo(json.dumps(gate.as_dict(), indent=2, sort_keys=True))
        else:
            console.print(gate.message)
            if gate.reason == "ack_required":
                console.print(TOKEN_COST_CAVEAT)
            elif gate.reason == "model_path_required":
                console.print(MODEL_PATH_UNAVAILABLE)
        return

    running = start_companion_server(pack, out, ack_token_cost=True, host=host, port=port)
    payload = {
        **gate.as_dict(),
        "url": running.url,
        "selection_file": running.selection_path.name,
    }
    try:
        if json_output:
            typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        else:
            console.print(TOKEN_COST_CAVEAT)
            console.print(f"London, Show Me is running at {running.url}")
            console.print(f"Selection will be written to {running.selection_path.name}")
        if timeout:
            running.wait_until_stopped(timeout=timeout)
    finally:
        if running.thread.is_alive():
            running.stop()
        else:
            running.httpd.server_close()


def _run_launch_gate(pack_path: Path, *, json_output: bool = False) -> None:
    payload = evaluate_launch_gates(pack_path)
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        verdict = "PASS" if payload["ok"] else "FAIL"
        console.print(f"Phase 8 launch gate: {verdict}")
        for gate_id, result in payload["gates"].items():
            marker = "ok" if result["ok"] else "fail"
            console.print(f"- {gate_id}: {marker} - {result['detail']}", markup=False)
            for failure in result.get("failures", []):
                console.print(f"  {failure}", markup=False)
    if not payload["ok"]:
        raise SystemExit(1)


def _run_gallery_build(
    pack_dirs: list[Path],
    *,
    out: Path = Path("london-gallery"),
    json_output: bool = False,
) -> None:
    if not pack_dirs:
        raise typer.BadParameter("london gallery build requires at least one pack directory")
    index_path = write_gallery(pack_dirs, out)
    payload = {
        "index": str(index_path),
        "out": str(out),
        "pack_dirs": [str(path) for path in pack_dirs],
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    console.print(f"London public gallery written to {index_path}")


def _setup_status(env_file: Path | None) -> dict[str, object]:
    return collect_setup_status(env_file=env_file, config=load_config())


def _run_setup(
    *,
    json_output: bool = False,
    live: bool = False,
    env_file: Path | None = None,
    plan: bool = False,
    non_interactive: bool = False,
    install: str | None = None,
    support_report: Path | None = None,
    print_env_example: bool = False,
    verify_providers: bool = False,
) -> None:
    if print_env_example:
        print(ENV_EXAMPLE_TEXT, end="")
        return

    install_status = (
        _setup_install_status(install, json_output=json_output, non_interactive=non_interactive)
        if install
        else None
    )
    status = _setup_status(env_file)
    if install_status:
        status["setup_install"] = install_status
    live_failed = _setup_live_failed(status, live=live)
    if live:
        status = _setup_with_live_status(status)
    if support_report:
        write_support_report(status, support_report)
    verify_failed = _setup_verify_providers_failed(status, verify_providers=verify_providers)

    if json_output:
        print(json.dumps(status, indent=2, sort_keys=True))
        if verify_failed or live_failed:
            raise SystemExit(1)
        return

    if plan:
        console.print(_setup_plan_text())
        if verify_failed or live_failed:
            raise SystemExit(1)
        return

    console.print(_setup_concierge_text(status, support_report=support_report))
    if verify_failed or live_failed:
        raise SystemExit(1)


def _setup_verify_providers_failed(status: dict[str, object], *, verify_providers: bool) -> bool:
    if not verify_providers:
        return False
    image = status.get("image_generation") if isinstance(status.get("image_generation"), dict) else {}
    selected = str(image.get("selected_provider") or "manual-prompt")
    return selected in {"manual-prompt", "none", "fixture"}


def _setup_ready_live_providers(status: dict[str, object]) -> list[dict[str, object]]:
    return [
        provider for provider in status.get("providers", [])
        if (
            isinstance(provider, dict)
            and provider.get("kind") == "live"
            and provider.get("ready")
            and _setup_live_provider_allowed(provider, status)
        )
    ]


def _setup_live_provider_allowed(provider: dict[str, object], status: dict[str, object]) -> bool:
    if provider.get("id") != "bfl_flux":
        return True
    image = status.get("image_generation") if isinstance(status.get("image_generation"), dict) else {}
    config = image.get("config") if isinstance(image.get("config"), dict) else {}
    allow_paid = bool(image.get("allow_paid") or config.get("allow_paid"))
    spend_limit = float(image.get("spend_limit_usd") or config.get("spend_limit_usd") or 0.0)
    return allow_paid and spend_limit > 0


def _setup_with_live_status(status: dict[str, object]) -> dict[str, object]:
    ready_live = _setup_ready_live_providers(status)
    verdict = status.get("verdict", "CORE READY")
    if status.get("status") != "blocked" and not ready_live:
        verdict = "LIVE UPGRADES MISSING"
    return {
        **status,
        "verdict": verdict,
        "setup": {
            "live_requested": True,
            "live_ready": bool(ready_live),
            "live_provider_ids": [str(provider["id"]) for provider in ready_live],
        },
    }


def _setup_install_status(
    target: str | None,
    *,
    json_output: bool = False,
    non_interactive: bool = False,
) -> dict[str, object]:
    normalized = (target or "").strip().lower().replace("_", "-")
    if normalized in {"drawthings", "draw-things-cli"}:
        normalized = "draw-things"
    if normalized in {"comfy", "comfy-ui"}:
        normalized = "comfyui"
    if normalized not in {"draw-things", "comfyui"}:
        raise typer.BadParameter("--install currently supports draw-things or comfyui")
    machine_mode = json_output or non_interactive or bool(os.environ.get("CI"))
    if normalized == "comfyui":
        return _setup_comfyui_install_guidance(machine_mode=machine_mode)
    if machine_mode:
        return {
            "target": "draw-things",
            "status": "skipped_machine_mode",
            "install_command": DRAW_THINGS_BREW_INSTALL,
            "message": "Install skipped because setup is running in JSON, non-interactive, or CI mode.",
            "mutated": False,
            "secrets_printed": False,
        }
    return _install_draw_things_cli()


def _setup_comfyui_install_guidance(*, machine_mode: bool) -> dict[str, object]:
    return {
        "target": "comfyui",
        "status": "skipped_machine_mode" if machine_mode else "manual_steps",
        "install_commands": list(COMFYUI_INSTALL_COMMANDS),
        "message": "Install ComfyUI, download a model/workflow, then set LONDON_COMFYUI_URL and LONDON_COMFYUI_WORKFLOW.",
        "mutated": False,
        "secrets_printed": False,
    }


def _install_draw_things_cli() -> dict[str, object]:
    brew = shutil.which("brew")
    if not brew:
        return {
            "target": "draw-things",
            "status": "homebrew_missing",
            "install_command": DRAW_THINGS_BREW_INSTALL,
            "message": "Homebrew was not found. Run the install command yourself after installing Homebrew.",
            "mutated": False,
            "secrets_printed": False,
        }
    completed = subprocess.run(  # noqa: S603 - explicit user-requested installer command
        [brew, "install", "drawthingsai/draw-things/draw-things-cli"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return {
            "target": "draw-things",
            "status": "failed",
            "install_command": DRAW_THINGS_BREW_INSTALL,
            "message": "Homebrew install failed. Re-run the install command in a terminal to inspect Homebrew output.",
            "mutated": False,
            "secrets_printed": False,
        }
    return {
        "target": "draw-things",
        "status": "installed",
        "install_command": DRAW_THINGS_BREW_INSTALL,
        "message": "Draw Things CLI install command completed. First generation may still need model downloads, disk space, and local compute.",
        "mutated": True,
        "secrets_printed": False,
    }


def _setup_live_failed(status: dict[str, object], *, live: bool) -> bool:
    return live and not _setup_ready_live_providers(status)


def _run_doctor(
    *,
    json_output: bool = False,
    live: bool = False,
    env_file: Path | None = None,
    support_report: Path | None = None,
) -> None:
    status = _setup_status(env_file)
    live_status = _setup_with_live_status(status)
    setup_live = live_status.get("setup") if isinstance(live_status.get("setup"), dict) else {}
    live_ready = bool(setup_live.get("live_ready"))
    live_provider_ids = [str(provider_id) for provider_id in setup_live.get("live_provider_ids", [])]
    doctor_payload = {
        **status,
        "verdict": live_status.get("verdict", status.get("verdict", "CORE READY")) if live else status.get("verdict", "CORE READY"),
        "doctor": {
            "live_requested": live,
            "live_ready": live_ready,
            "live_provider_ids": live_provider_ids,
        },
    }
    if support_report:
        write_support_report(doctor_payload, support_report)
    if json_output:
        print(json.dumps(doctor_payload, indent=2, sort_keys=True))
    else:
        console.print(_doctor_text(doctor_payload))
    if live and not live_ready:
        raise SystemExit(1)


def _run_intake(
    *,
    out: Path = Path("london-intake.html"),
    print_markdown: bool = False,
    brief: str | None = None,
    refusals: str | None = None,
    anti_audience: str | None = None,
    seeds: str | None = None,
    artifact_hint: str | None = None,
) -> None:
    if print_markdown:
        if brief is None:
            raise typer.BadParameter("intake --print-markdown requires --brief")
        try:
            print(
                build_intake_markdown(
                    brief,
                    refusals=refusals or "",
                    anti_audience=anti_audience or "",
                    seeds=seeds or "",
                    artifact_hint=artifact_hint or "",
                ),
                end="",
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        return

    write_intake_html(out)
    console.print(f"London intake written to {out}")


def _run_validate_chassis(
    *,
    json_output: bool = False,
    captures_dir: Path | None = None,
    write_html_dir: Path | None = None,
) -> None:
    payload = run_chassis_validation(captures_dir=captures_dir, write_html_dir=write_html_dir)
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        status = "PASS" if payload.get("ok") else "FAIL"
        console.print(
            f"London chassis validation: {status} "
            f"({payload.get('scenario_count')} scenarios, {payload.get('capture_count')} captures)"
        )
    if not payload.get("ok"):
        raise SystemExit(1)


def _run_providers_list(*, json_output: bool = False, env_file: Path | None = None) -> None:
    status = _setup_status(env_file)
    if json_output:
        print(json.dumps({"providers": status["providers"], "image_generation": status["image_generation"]}, indent=2, sort_keys=True))
    else:
        _print_provider_rows(status)


def _run_providers_recommend(*, json_output: bool = False, env_file: Path | None = None) -> None:
    status = _setup_status(env_file)
    payload = status["image_generation"]
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        console.print(_provider_recommendation_text(payload))


def _run_providers_verify(
    *,
    provider: str,
    no_spend: bool = False,
    json_output: bool = False,
    env_file: Path | None = None,
) -> None:
    status = _setup_status(env_file)
    payload = _verify_provider_payload(provider, status, no_spend=no_spend)
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        console.print(_verify_provider_text(payload))
    if not payload["ready"]:
        raise SystemExit(1)


def _run_providers_detect(
    *,
    local: bool = False,
    json_output: bool = False,
    env_file: Path | None = None,
) -> None:
    status = _setup_status(env_file)
    providers = [
        provider for provider in status.get("providers", [])
        if isinstance(provider, dict)
        and (
            not local
                or provider.get("id") in {"automatic1111", "comfyui", "external_cmd", "draw_things"}
        )
    ]
    payload = {
        "local_only": local,
        "providers": providers,
        "secrets_printed": False,
    }
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for provider in providers:
            console.print(f"{provider['label']}: {provider['status']}")


def _run_image_try(
    *,
    prompt: str,
    provider: str = "auto",
    out: Path = Path("london-image-try"),
    env_file: Path | None = None,
    image_quality: str | None = None,
    allow_paid: bool = False,
    spend_limit_usd: float | None = None,
    json_output: bool = False,
) -> None:
    raw_provider = provider
    command_env, _ = merge_env_file(os.environ, env_file)
    config = _image_try_config(load_config(), allow_paid=allow_paid, spend_limit_usd=spend_limit_usd)
    local_only = raw_provider.strip().lower().replace("_", "-") == "auto-local"
    if raw_provider == "auto" or local_only:
        status = collect_setup_status(env=command_env, config=config)
        recommendation = dict(status.get("image_generation", {}))
        if local_only:
            local_chain = [
                item for item in recommendation.get("fallback_chain", [])
                if isinstance(item, dict) and item.get("provider") in {"automatic1111", "comfyui", "external-cmd", "draw-things", "manual-prompt"}
            ]
            selected = next(
                (str(item["provider"]) for item in local_chain if item.get("ready_generate")),
                "manual-prompt",
            )
            recommendation["selected_provider"] = selected
            recommendation["fallback_chain"] = local_chain or [{"provider": "manual-prompt", "ready": True, "reason": "visual direction board"}]
            recommendation["requested_provider"] = "auto-local"
        else:
            selected = str(recommendation.get("selected_provider") or "manual-prompt")
    else:
        selected = normalize_image_provider(raw_provider)
        recommendation = _explicit_provider_selection(
            requested_provider=raw_provider,
            provider=selected,
            env=command_env,
            config=config,
        )
    pack = {
        "title": "London image try",
        "brief": {"title": "Image try", "text": prompt, "digest": "image-try", "source_label": "cli prompt", "source_ref": "cli:image-try"},
        "brain_findings": [],
        "source_plan": {"sources": []},
    }
    route = {
        "id": "image-try",
        "title": prompt[:72] or "London image try",
        "headline": prompt,
        "rationale": "Single prompt trial for the image provider ladder.",
        "sections": [{"title": "Concept", "body": prompt}],
    }
    result = generate_route_concept(
        pack,
        route,
        route_index=1,
        provider=selected,
        requested_provider=str(recommendation.get("requested_provider") or raw_provider),
        fallback_chain=recommendation.get("fallback_chain", []) if isinstance(recommendation.get("fallback_chain"), list) else [],
        selection_reason=str(recommendation.get("selected_reason") or "image try"),
        spend_policy={
            "allow_paid": bool(recommendation.get("allow_paid", False)),
            "spend_limit_usd": float(recommendation.get("spend_limit_usd", 0.0) or 0.0),
            "allow_experimental_free_network": bool(
                (recommendation.get("config") if isinstance(recommendation.get("config"), dict) else {}).get("allow_experimental_free_network", False)
            ),
        },
        env=command_env,
    )
    out.mkdir(parents=True, exist_ok=True)
    asset = dict(result.asset)
    if asset.get("src"):
        asset_dir = out / "assets"
        asset_dir.mkdir(parents=True, exist_ok=True)
        asset["src"] = _materialize_asset_src(str(asset["src"]), asset_dir, route_index=1, asset_index=1)
    (out / "image-try.json").write_text(
        json.dumps({"asset": asset, "receipt": result.receipt, "provider_selection": recommendation}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    # image-try uses a synthetic pack with no artifact_type; the honest default is "generic".
    (out / "prompt.txt").write_text(
        str(asset.get("prompt") or build_image_prompt(pack, route, artifact_type="generic")),
        encoding="utf-8",
    )
    if json_output:
        typer.echo(json.dumps({"out": str(out), "asset": asset, "receipt": result.receipt}, indent=2, sort_keys=True))
        return
    console.print(f"London image try written to {out}")


def _run_image_materialize_pack(
    pack_arg: Path,
    *,
    out: Path,
    image_provider: str,
    env_file: Path,
    allow_paid: bool = False,
    spend_limit_usd: float | None = None,
    image_quality: str | None = None,
    json_output: bool = False,
) -> None:
    raw_provider = image_provider
    provider = _normalize_cli_image_provider(raw_provider)
    if provider in {"auto", "manual-prompt", "none", "fixture"}:
        raise typer.BadParameter(
            "london image materialize-pack requires a real explicit image provider, not auto/manual/none/fixture"
        )

    input_root, source_pack = _load_materialization_pack(pack_arg)
    _require_real_director_pack(source_pack)
    output_root = _copy_pack_for_materialization(input_root, out)
    _, pack = _load_materialization_pack(output_root)

    command_env, env_file_status = merge_env_file(os.environ, env_file)
    config = _image_try_config(load_config(), allow_paid=allow_paid, spend_limit_usd=spend_limit_usd)
    provider_selection = _explicit_provider_selection(
        requested_provider=raw_provider,
        provider=provider,
        env=command_env,
        config=config,
    )
    quality_level = _resolve_image_quality(
        image_quality,
        env=command_env,
        assume_yes=True,
    )

    pack["provider_selection"] = provider_selection
    if env_file_status:
        pack.setdefault("setup_context", {})
        if isinstance(pack["setup_context"], dict):
            pack["setup_context"]["env_file"] = env_file_status
    route_assets, image_receipts = _write_visual_routes(
        pack,
        output_root,
        generate_images=True,
        image_provider=provider,
        requested_provider=raw_provider,
        provider_selection=provider_selection,
        env=command_env,
        max_generated_routes=1,
        image_quality=quality_level,
    )
    pack["routes"] = route_assets
    pack["receipts"] = [
        receipt
        for receipt in pack.get("receipts", [])
        if not (isinstance(receipt, Mapping) and receipt.get("kind") == "image-generation")
    ] + image_receipts

    _write_public_pack_files(pack, output_root)

    payload = {
        "input": str(input_root),
        "out": str(output_root),
        "provider": provider,
        "requested_provider": raw_provider,
        "max_generated_routes": 1,
        "generated_live_route_ids": [
            display_text(receipt.get("route_id"))
            for receipt in image_receipts
            if isinstance(receipt, Mapping) and receipt.get("status") == "generated_live"
        ],
        "receipt_statuses": [
            {
                "route_id": display_text(receipt.get("route_id")),
                "status": display_text(receipt.get("status")),
                "provider": display_text(receipt.get("provider")),
                "resolved_provider": display_text(receipt.get("resolved_provider")),
                "model": display_text(receipt.get("model")),
                "asset_src": display_text(receipt.get("asset_src")),
                "request_config": (
                    receipt.get("request_config")
                    if isinstance(receipt.get("request_config"), Mapping)
                    else None
                ),
                "failure": display_text(receipt.get("failure")),
            }
            for receipt in image_receipts
            if isinstance(receipt, Mapping)
        ],
        "secrets_printed": False,
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    console.print(f"London pack image materialization written to {output_root}")


def _load_materialization_pack(path: Path) -> tuple[Path, dict[str, object]]:
    root = path if path.is_dir() else path.parent
    pack_path = path if path.is_file() else root / "london-pack.json"
    if not pack_path.exists():
        raise typer.BadParameter(f"London pack not found: {pack_path}")
    try:
        payload = json.loads(pack_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"London pack JSON is invalid: {pack_path}") from exc
    if not isinstance(payload, dict):
        raise typer.BadParameter(f"London pack must be a JSON object: {pack_path}")
    return root, payload


def _require_real_director_pack(pack: Mapping[str, object]) -> None:
    receipts = pack.get("receipts")
    if not isinstance(receipts, list):
        raise typer.BadParameter("image materialization requires a real director receipt")
    director_receipts = [
        receipt
        for receipt in receipts
        if isinstance(receipt, Mapping) and receipt.get("kind") == "director"
    ]
    if not director_receipts:
        raise typer.BadParameter("image materialization requires a real director receipt")
    allowed = {"claude_cli_print", "in_session", "keyed"}
    blocked_markers = ("offline", "fixture", "fake", "manual-prompt")
    for receipt in director_receipts:
        provider = display_text(receipt.get("provider")).strip()
        lowered = provider.lower().replace("_", "-")
        if (
            provider in allowed
            and not any(marker in lowered for marker in blocked_markers)
            and receipt.get("deterministic") is not True
        ):
            return
    providers = ", ".join(display_text(receipt.get("provider")) or "<missing>" for receipt in director_receipts)
    raise typer.BadParameter(
        "image materialization refuses offline/FakeDirector packs; "
        f"director receipt provider(s): {providers}"
    )


def _copy_pack_for_materialization(input_root: Path, output_root: Path) -> Path:
    resolved_input = input_root.resolve()
    resolved_output = output_root.resolve()
    if resolved_input == resolved_output:
        return resolved_output
    if resolved_output.exists():
        try:
            has_contents = any(resolved_output.iterdir()) if resolved_output.is_dir() else True
        except OSError as exc:
            raise typer.BadParameter(f"--out cannot be inspected: {output_root}") from exc
        if has_contents:
            raise typer.BadParameter("--out already exists; choose an empty path for materialized proof")
        resolved_output.rmdir()
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(resolved_input, resolved_output)
    return resolved_output


def _image_try_config(
    config: dict[str, object],
    *,
    allow_paid: bool = False,
    spend_limit_usd: float | None = None,
) -> dict[str, object]:
    """Return command-scoped image config for one provider smoke.

    This keeps BFL spend acknowledgement local to ``london image try`` instead of
    requiring a global config mutation for a one-image smoke.
    """

    resolved = dict(config)
    image_config = dict(resolved.get("image") if isinstance(resolved.get("image"), dict) else {})
    if allow_paid:
        image_config["allow_paid"] = True
    if spend_limit_usd is not None:
        image_config["spend_limit_usd"] = spend_limit_usd
    resolved["image"] = image_config
    return resolved


def _run_config_show(*, json_output: bool = False) -> None:
    config = load_config()
    payload = {"path": str(default_config_path()), "config": config, "secrets_stored": False}
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        console.print(f"London config: {payload['path']}")
        console.print(json.dumps(config, indent=2, sort_keys=True))


def _run_config_set(key: str, value: str) -> None:
    config = set_config_value(key, value)
    console.print(f"Updated {key} in {default_config_path()}")
    console.print(json.dumps(config, indent=2, sort_keys=True))


def _setup_plan_text() -> str:
    return """London setup plan

1. Keep keys in environment variables, an explicit --env-file, direnv, or a secret manager.
2. For local .env use: cp .env.example .env && chmod 600 .env && $EDITOR .env
3. Run: london setup --env-file .env
4. Run keyless if preferred: london examples/brief.md --images auto --out london-pack
5. For secret managers: op run --env-file=.env -- london brief.md --images auto

London never prints, saves, hashes, uploads, prefixes, suffixes, or length-reports key values."""


_SETUP_PROFILE_LINES: tuple[tuple[str, str, str], ...] = (
    ("1", "Core demo", "keyless bundled brain + visual direction boards"),
    ("2", "Recommended", "ready local generators or Gemini/OpenAI"),
    ("3", "Pro image lab", "BFL only after explicit paid-use config"),
    ("4", "Details", "london providers list"),
)


_SETUP_PROVIDER_CARDS: tuple[dict[str, str], ...] = (
    {
        "id": "gemini",
        "title": "Gemini",
        "role": "Preferred live multimodal direction and image lane.",
        "best_for": "Visual reads, route imagery, and design-literate critique.",
        "needs": "GEMINI_API_KEY or GOOGLE_API_KEY plus image.allow_paid=true and a spend limit for image generation.",
        "cost_risk": "Metered API image lane; 4K generation is gated by estimated spend before any provider call.",
        "fallback": "OpenAI when configured, local generators, then visual direction boards.",
    },
    {
        "id": "openai",
        "title": "OpenAI",
        "role": "Secondary live language, multimodal, and image lane.",
        "best_for": "Backup critique and image generation when Gemini is unavailable.",
        "needs": "OPENAI_API_KEY plus image.allow_paid=true and a spend limit for image generation.",
        "cost_risk": "Metered API image lane; default gpt-image-2 4K/high generation is gated by estimated spend.",
        "fallback": "Gemini, local generators, then visual direction boards.",
    },
    {
        "id": "bfl_flux",
        "title": "BFL / FLUX",
        "role": "Premium pro image lab.",
        "best_for": "High-control route imagery after the user enables paid image work.",
        "needs": "BFL_API_KEY plus image.allow_paid=true and a spend limit.",
        "cost_risk": "Metered provider; auto mode will not choose it without explicit paid-use config.",
        "fallback": "Gemini/OpenAI/local generators, then visual direction boards.",
    },
    {
        "id": "draw_things",
        "title": "Draw Things CLI",
        "role": "Recommended free/local Mac image path when explicitly configured.",
        "best_for": "Local concept-image trials on a Mac, subject to model setup, disk, and compute.",
        "needs": "LONDON_DRAW_THINGS_COMMAND with {prompt_file} and {output}; {cli} may come from LONDON_DRAW_THINGS_CLI.",
        "cost_risk": "No provider spend; never installed silently and never auto-generates until the command path is ready.",
        "fallback": "Generic external command, then visual direction board.",
    },
    {
        "id": "external_cmd",
        "title": "External image command",
        "role": "Bring-your-own local image pipe.",
        "best_for": "Handing London's prompt to a local script, GPU tool, or wrapper that writes an image file.",
        "needs": "LONDON_EXTERNAL_IMAGE_COMMAND with {prompt_file} and {output} placeholders.",
        "cost_risk": "Local command execution only; London receipts the command name and never prints local output paths.",
        "fallback": "Visual direction board if the command fails or returns no image.",
    },
    {
        "id": "firecrawl",
        "title": "Firecrawl",
        "role": "Discovery and source hydration for source packs.",
        "best_for": "Finding public references and keeping receipts connected to sources.",
        "needs": "FIRECRAWL_API_KEY and the optional firecrawl package.",
        "cost_risk": "External web extraction; it does not decide visual truth from branding tokens.",
        "fallback": "Manual source lists and bundled London Brain evidence.",
    },
    {
        "id": "playwright",
        "title": "Playwright",
        "role": "Local browser capture bridge.",
        "best_for": "Screenshots and local prototype QA evidence.",
        "needs": "Python package and browser binaries.",
        "cost_risk": "Local only; no provider spend.",
        "fallback": "Manual browser review.",
    },
    {
        "id": "manual_prompt",
        "title": "Visual direction board",
        "role": "Always-available zero-spend visual floor.",
        "best_for": "A visible route board with palette, type, composition, prompt, and evidence cues when no generator is ready.",
        "needs": "No keys.",
        "cost_risk": "Zero spend; clearly labeled as direction, not generated concept art.",
        "fallback": "None needed.",
    },
)


def _setup_concierge_text(status: dict[str, object], *, support_report: Path | None = None) -> str:
    image = status.get("image_generation") if isinstance(status.get("image_generation"), dict) else {}
    selected = image.get("selected_provider", "manual-prompt")
    env_file = status.get("env_file") if isinstance(status.get("env_file"), dict) else {}
    warnings = env_file.get("warnings", []) if isinstance(env_file.get("warnings"), list) else []
    report_line = "\nSupport report written." if support_report else ""
    install_line = _setup_install_line(status)
    draw_things_line = _draw_things_setup_line(status)
    warning_text = "\n".join(f"  - {warning}" for warning in warnings)
    warning_block = f"\nEnv file notes:\n{warning_text}" if warning_text else ""
    return f"""+--------------------------------------------------+
| LONDON                                           |
| Creative Director CLI                            |
| Actual work -> visual reads -> London Pack       |
+--------------------------------------------------+

Verdict: {_setup_human_verdict(status)}

Capability map:
  Core engine          [{_direction_mode_badge(status)}]
  Local pack builder   [{_capability_badge(status, "deterministic_pack")}]
  Browser capture      [{_capability_badge(status, "browser_capture")}]
  Vision reading       [{_capability_badge(status, "multimodal_direction")}]
  Image generation     [{_image_generation_badge(status)}]
  Web discovery        [{_capability_badge(status, "web_extraction")}]
  Design bridges       [{_design_bridges_badge(status)}]

Recommended image lane: {selected}
Reason: {image.get("selected_reason", "visual direction board is available")}

Setup profiles:
{_setup_profile_lines()}

Provider cards:
{_setup_provider_card_lines(status)}

Secret setup:
  cp .env.example .env
  chmod 600 .env
  $EDITOR .env

Secret managers:
  op run --env-file=.env -- london brief.md --images auto
  doppler run -- london brief.md --images auto
  direnv allow

London found key presence only. Values printed: never.
Keyless runs do not fake concept art; they export visual direction boards with copyable route prompts.
Live probes run only with --live. Paid image providers require explicit paid-use config.
{_metered_image_cost_line(status)}
{draw_things_line}
{install_line}
Next command: printf '%s\n' '# Brief' 'A joyful retro-futurist lunchbox ritual kit.' > /tmp/london-brief.md && london /tmp/london-brief.md --images auto --out /tmp/london-pack{warning_block}{report_line}"""


def _setup_human_verdict(status: dict[str, object]) -> str:
    if status.get("status") == "blocked":
        return "BLOCKED"
    setup = status.get("setup") if isinstance(status.get("setup"), dict) else {}
    if setup.get("live_requested") and not setup.get("live_ready"):
        return "LIVE UPGRADES MISSING"
    return str(status.get("verdict") or "CORE READY")


def _setup_profile_lines() -> str:
    return "\n".join(f"  [{number}] {label:<13} {description}" for number, label, description in _SETUP_PROFILE_LINES)


def _setup_provider_card_lines(status: dict[str, object]) -> str:
    lines: list[str] = []
    for card in _SETUP_PROVIDER_CARDS:
        status_label = _provider_status_label(status, card["id"])
        lines.extend(
            [
                f"  {card['title']} [{status_label}]",
                f"    Role: {card['role']}",
                f"    Best for: {card['best_for']}",
                f"    Needs: {card['needs']}",
                f"    Cost/risk: {card['cost_risk']}",
                f"    Fallback: {card['fallback']}",
            ]
        )
    return "\n".join(lines)


def _metered_image_cost_line(status: dict[str, object]) -> str:
    image = status.get("image_generation") if isinstance(status.get("image_generation"), dict) else {}
    ceilings = image.get("price_ceilings_usd") if isinstance(image.get("price_ceilings_usd"), dict) else {}
    gemini = ceilings.get("gemini", 0.25)
    openai = ceilings.get("openai", 0.35)
    verified = image.get("price_ceiling_last_verified") or "2026-06-09"
    return (
        "Metered image disclosure: Gemini/OpenAI image defaults are gated before generation "
        f"(ceilings verified {verified}: Gemini 4K <= ${float(gemini):.2f}/image, "
        f"OpenAI 4K/high <= ${float(openai):.2f}/image).\n"
        "Downshift command: london config set image.quality standard\n"
        "Downshift flag: --image-quality model-default"
    )


def _draw_things_setup_line(status: dict[str, object]) -> str:
    setup = status.get("draw_things_setup") if isinstance(status.get("draw_things_setup"), dict) else {}
    if not setup.get("recommended"):
        return "Draw Things CLI: optional local Mac path; configure LONDON_DRAW_THINGS_COMMAND when ready."
    return (
        "Draw Things CLI: recommended free/local Mac path when no generator is ready. "
        "Run london setup --install draw-things, then try "
        'london image try "kids lunchbox ritual kit" --provider draw-things --out /tmp/london-draw-things-try. '
        "First generation may require model downloads, disk space, and local compute."
    )


def _setup_install_line(status: dict[str, object]) -> str:
    install = status.get("setup_install") if isinstance(status.get("setup_install"), dict) else {}
    if not install:
        return ""
    target = str(install.get("target") or "")
    status_label = str(install.get("status") or "unknown")
    message = str(install.get("message") or "")
    if target == "comfyui":
        commands = install.get("install_commands") if isinstance(install.get("install_commands"), list) else []
        command_text = " && ".join(str(command) for command in commands)
        if status_label == "skipped_machine_mode":
            return f"ComfyUI install: skipped in machine mode. Manual commands: {command_text}"
        return f"ComfyUI install: manual steps only. {message} Commands: {command_text}"
    command = str(install.get("install_command") or DRAW_THINGS_BREW_INSTALL)
    if status_label == "homebrew_missing":
        return f"Draw Things install: Homebrew not found. Run: {command}"
    if status_label == "skipped_machine_mode":
        return f"Draw Things install: skipped in machine mode. Run interactively: {command}"
    if status_label == "installed":
        return f"Draw Things install: completed. {message}"
    return f"Draw Things install: {status_label}. {message}"


def _capability_badge(status: dict[str, object], capability_id: str) -> str:
    for capability in status.get("capabilities", []):
        if isinstance(capability, dict) and capability.get("id") == capability_id:
            return "READY" if capability.get("ready") else "MISSING"
    return "MISSING"


def _image_generation_badge(status: dict[str, object]) -> str:
    image = status.get("image_generation") if isinstance(status.get("image_generation"), dict) else {}
    selected = str(image.get("selected_provider") or "manual-prompt")
    if selected == "manual-prompt":
        return "VISUAL BOARDS READY"
    if selected == "none":
        return "DISABLED"
    if selected == "fixture":
        return "FIXTURE ONLY"
    return f"{selected.upper()} READY"


def _design_bridges_badge(status: dict[str, object]) -> str:
    local_image_providers = {"automatic1111", "comfyui", "external_cmd", "draw_things"}
    for provider in status.get("providers", []):
        if (
            isinstance(provider, dict)
            and provider.get("id") in local_image_providers
            and provider.get("ready_generate")
        ):
            return "LOCAL LAB READY"
    return "OPTIONAL"


def _direction_mode_badge(status: dict[str, object]) -> str:
    """Human badge for which director would run on the default path (Pitfall 6).

    Presence-only — reads only the boolean/mode fields of the ``direction_mode`` report;
    never touches key material."""

    direction = status.get("direction_mode") if isinstance(status.get("direction_mode"), dict) else {}
    mode = str(direction.get("mode") or "none")
    return {
        "in_session": "IN-SESSION MODEL",
        "api": "API MODEL",
        "none": "NO MODEL (use --offline)",
    }.get(mode, "NO MODEL (use --offline)")


def _provider_status_label(status: dict[str, object], provider_id: str) -> str:
    for provider in status.get("providers", []):
        if isinstance(provider, dict) and provider.get("id") == provider_id:
            raw = str(provider.get("status") or "missing")
            if raw == "ready_generate":
                return "READY"
            if raw == "detected_needs_setup":
                return "NEEDS SETUP"
            return raw.upper().replace("_", " ")
    return "MISSING"


def _doctor_text(payload: dict[str, object]) -> str:
    doctor = payload.get("doctor") if isinstance(payload.get("doctor"), dict) else {}
    live = "READY" if doctor.get("live_ready") else "MISSING"
    return (
        f"London doctor: {payload.get('verdict', 'CORE READY')}\n"
        f"Creative direction: {_direction_mode_badge(payload)}\n"
        f"Live providers: {live}\nSecrets printed: never"
    )


def _print_provider_rows(status: dict[str, object]) -> None:
    for provider in status.get("providers", []):
        if not isinstance(provider, dict):
            continue
        labels = ", ".join(str(label) for label in provider.get("state_labels", []))
        console.print(f"{provider['label']}: {provider['status']} [{labels}]")


def _provider_recommendation_text(payload: object) -> str:
    if not isinstance(payload, dict):
        return "Recommended image lane: local"
    chain = " -> ".join(str(item.get("provider")) for item in payload.get("fallback_chain", []) if isinstance(item, dict))
    return f"Recommended image lane: {payload.get('selected_provider', 'local')}\nFallback chain: {chain}\nReason: {payload.get('selected_reason', '')}"


def _verify_provider_payload(provider: str, status: dict[str, object], *, no_spend: bool) -> dict[str, object]:
    normalized = provider.strip().lower().replace("_", "-")
    aliases = {
        "local": "manual-prompt",
        "local-deterministic": "fixture",
        "local-renderer": "fixture",
        "manual": "manual-prompt",
        "prompt": "manual-prompt",
        "a1111": "automatic1111",
        "automatic-1111": "automatic1111",
        "external": "external-cmd",
        "external-command": "external-cmd",
        "local-command": "external-cmd",
        "local-cmd": "external-cmd",
        "bring-your-own": "external-cmd",
        "byo": "external-cmd",
        "drawthings": "draw-things",
        "draw-things-cli": "draw-things",
        "bfl-flux": "bfl",
        "flux": "bfl",
        "perchance": "manual-prompt",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized in {"bfl-flux", "flux"}:
        normalized = "bfl"
    registry_id = {
        "automatic1111": "automatic1111",
        "comfyui": "comfyui",
        "external-cmd": "external_cmd",
        "draw-things": "draw_things",
        "gemini": "gemini",
        "bfl": "bfl_flux",
        "openai": "openai",
        "fal": "fal",
        "replicate": "replicate",
        "pollinations": "pollinations",
        "manual-prompt": "manual_prompt",
        "fixture": "local_deterministic",
    }.get(normalized, normalized)
    row = next(
        (item for item in status.get("providers", []) if isinstance(item, dict) and item.get("id") == registry_id),
        None,
    )
    paid_blocked = (
        normalized in METERED_IMAGE_PROVIDERS
        and no_spend
        and bool(row and (row.get("ready_generate") or row.get("status") == "paid_blocked"))
    )
    return {
        "provider": normalized,
        "registry_id": registry_id,
        "ready": bool(row and row.get("ready") and not paid_blocked),
        "ready_generate": bool(row and row.get("ready_generate") and not paid_blocked),
        "status": "paid_blocked" if paid_blocked else (row.get("status") if row else "unknown_provider"),
        "no_spend": no_spend,
        "secrets_printed": False,
    }


def _verify_provider_text(payload: dict[str, object]) -> str:
    return f"{payload['provider']}: {payload['status']} / ready={payload['ready']} / secrets printed=never"


@brain_app.command("inventory")
def brain_inventory() -> None:
    """Show sanitized brain inventory."""
    try:
        console.print(LondonBrain(brain_loader.resolve_brain_path()).formatted_inventory(), markup=False)
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc)) from exc


@brain_app.command("query")
def brain_query(
    terms: list[str] = typer.Argument(..., help="Query terms (multi-word: london brain query night shift nurses)."),
    limit: int = typer.Option(8, "--limit", "-n", min=1, max=25),
) -> None:
    """Query the sanitized London brain."""
    query = " ".join(terms)
    try:
        console.print(LondonBrain(brain_loader.resolve_brain_path()).formatted_query(query, limit=limit), markup=False)
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc)) from exc


@brain_app.command("build-chroma")
def brain_build_chroma(
    out: Path = typer.Option(DEFAULT_CHROMA_DIR, "--out", help="Derived Chroma index directory."),
) -> None:
    """Build a derived Chroma index from the sanitized SQLite brain."""
    status = LondonBrain(brain_loader.resolve_brain_path()).build_chroma(index_path=out)
    console.print(json.dumps(status, indent=2, sort_keys=True))


def _brain_install_target() -> Path:
    """The user-installed brain slot. Indirection so tests redirect off real user state."""
    return brain_loader.user_brain_path()


@brain_app.command("install")
def brain_install(
    path: Path = typer.Argument(..., help="Path to a distilled London brain .sqlite to install."),
) -> None:
    """Validate then install a swappable distilled brain (BRAIN-01).

    TOM-LOCKED privacy boundary: this accepts a distilled `.sqlite` ONLY. It never
    re-runs extraction — the scrape/extraction stay private; the distilled brain is
    the only export. A bad brain (missing / unreadable / empty) is refused LOUDLY
    with a non-zero exit before anything is installed.
    """
    report = brain_loader.validate_brain(path)
    if not report.ok:
        console.print(f"Refusing to install invalid brain: {report.reason}")
        raise SystemExit(1)

    dest = _brain_install_target()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(readonly_sqlite_uri(path), uri=True)) as src:
        with closing(sqlite3.connect(dest)) as target:
            src.backup(target)
    console.print(f"Installed brain (version {report.brain_version}) -> {dest}")


@app.command("setup")
def setup(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable setup status."),
    live: bool = typer.Option(False, "--live", help="Require at least one configured live provider."),
    env_file: Optional[Path] = typer.Option(None, "--env-file", help="Explicit env file to read for this command only."),
    plan: bool = typer.Option(False, "--plan", help="Print safe setup steps."),
    non_interactive: bool = typer.Option(False, "--non-interactive", help="Do not prompt."),
    install: Optional[str] = typer.Option(None, "--install", help="Optional setup target guidance; draw-things or comfyui."),
    support_report: Optional[Path] = typer.Option(None, "--support-report", help="Write a sanitized support report."),
    print_env_example: bool = typer.Option(False, "--print-env-example", help="Print blank .env.example content."),
    verify_providers: bool = typer.Option(False, "--verify-providers", help="Fail if no live image provider is ready."),
    text: bool = typer.Option(False, "--text", help="Force the text readout even in a TTY (skip the TUI)."),
) -> None:
    """Inspect local capabilities without printing secrets."""
    # TUI dispatch: launch the guided installer if running in a real TTY with no
    # machine-mode flags set. Every existing flag path falls through to _run_setup
    # untouched. The TUI is a NEW front door, not a replacement.
    machine_flags = (
        json_output
        or live
        or plan
        or non_interactive
        or bool(install)
        or bool(support_report)
        or print_env_example
        or verify_providers
        or text
        or bool(env_file)  # explicit env-file: use text readout so it's reflected
    )
    ci_env = bool(os.environ.get("CI"))
    is_tty = sys.stdin.isatty() and sys.stdout.isatty()
    if not machine_flags and not ci_env and is_tty:
        # Lazy-import textual only on the TUI path — keeps --json/CI free of it.
        from london.tui import run_setup_tui  # noqa: PLC0415
        _code = run_setup_tui()
        raise SystemExit(_code)

    _run_setup(
        json_output=json_output,
        live=live,
        env_file=env_file,
        plan=plan,
        non_interactive=non_interactive,
        install=install,
        support_report=support_report,
        print_env_example=print_env_example,
        verify_providers=verify_providers,
    )


@app.command("doctor")
def doctor(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable doctor status."),
    live: bool = typer.Option(False, "--live", help="Require at least one configured live provider."),
    env_file: Optional[Path] = typer.Option(None, "--env-file", help="Explicit env file to read for this command only."),
    support_report: Optional[Path] = typer.Option(None, "--support-report", help="Write a sanitized support report."),
) -> None:
    """Run setup diagnostics without printing secrets."""
    _run_doctor(json_output=json_output, live=live, env_file=env_file, support_report=support_report)


@providers_app.command("list")
def providers_list(
    json_output: bool = typer.Option(False, "--json", help="Emit provider rows as JSON."),
    env_file: Optional[Path] = typer.Option(None, "--env-file", help="Explicit env file to read for this command only."),
) -> None:
    """List provider readiness."""
    _run_providers_list(json_output=json_output, env_file=env_file)


@providers_app.callback(invoke_without_command=True)
def providers_default(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Emit provider rows as JSON."),
    env_file: Optional[Path] = typer.Option(None, "--env-file", help="Explicit env file to read for this command only."),
) -> None:
    """Default to listing provider readiness."""
    if ctx.invoked_subcommand is not None:
        return
    _run_providers_list(json_output=json_output, env_file=env_file)


@providers_app.command("recommend")
def providers_recommend(
    json_output: bool = typer.Option(False, "--json", help="Emit recommendation as JSON."),
    env_file: Optional[Path] = typer.Option(None, "--env-file", help="Explicit env file to read for this command only."),
) -> None:
    """Recommend an image provider lane."""
    _run_providers_recommend(json_output=json_output, env_file=env_file)


@providers_app.command("verify")
def providers_verify(
    provider: str = typer.Option(..., "--provider", help="Provider id to verify."),
    no_spend: bool = typer.Option(False, "--no-spend", help="Disallow paid provider verification."),
    json_output: bool = typer.Option(False, "--json", help="Emit verification as JSON."),
    env_file: Optional[Path] = typer.Option(None, "--env-file", help="Explicit env file to read for this command only."),
) -> None:
    """Verify one provider without printing secrets."""
    _run_providers_verify(provider=provider, no_spend=no_spend, json_output=json_output, env_file=env_file)


@providers_app.command("detect")
def providers_detect(
    local: bool = typer.Option(False, "--local", help="Limit output to local generator providers."),
    json_output: bool = typer.Option(False, "--json", help="Emit provider rows as JSON."),
    env_file: Optional[Path] = typer.Option(None, "--env-file", help="Explicit env file to read for this command only."),
) -> None:
    """Detect configured image providers."""
    _run_providers_detect(local=local, json_output=json_output, env_file=env_file)


@config_app.command("show")
def config_show(json_output: bool = typer.Option(False, "--json", help="Emit config as JSON.")) -> None:
    """Show non-secret London config."""
    _run_config_show(json_output=json_output)


@config_app.command("set")
def config_set(key: str, value: str) -> None:
    """Set a non-secret London config value."""
    _run_config_set(key, value)


@image_app.command("try")
def image_try_command(
    prompt: str = typer.Argument(..., help="Prompt text to try."),
    provider: str = typer.Option("auto", "--provider", help="Provider id, or auto-local for local-only probing."),
    out: Path = typer.Option(Path("london-image-try"), "--out", help="Output directory for the image try pack."),
    env_file: Optional[Path] = typer.Option(None, "--env-file", help="Explicit env file to read for this command only."),
    image_quality: Optional[str] = typer.Option(None, "--image-quality", help="Image-quality level to record in receipts."),
    allow_paid: bool = typer.Option(False, "--allow-paid", help="Allow paid providers for this one-image smoke."),
    spend_limit_usd: Optional[float] = typer.Option(None, "--spend-limit-usd", min=0.0, help="Spend limit for this one-image smoke."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable output."),
) -> None:
    """Try one image-provider lane with a prompt."""
    _run_image_try(
        prompt=prompt,
        provider=provider,
        out=out,
        env_file=env_file,
        image_quality=image_quality,
        allow_paid=allow_paid,
        spend_limit_usd=spend_limit_usd,
        json_output=json_output,
    )


@image_app.command("materialize-pack")
def image_materialize_pack_command(
    pack: Path = typer.Argument(..., help="Source pack directory or london-pack.json."),
    out: Path = typer.Option(..., "--out", help="Output directory for the materialized pack."),
    image_provider: str = typer.Option(..., "--image-provider", help="Explicit image provider to use."),
    env_file: Path = typer.Option(..., "--env-file", help="Explicit env file to read for this command only."),
    allow_paid: bool = typer.Option(False, "--allow-paid", help="Allow paid providers for this one-image materialization."),
    spend_limit_usd: Optional[float] = typer.Option(None, "--spend-limit-usd", min=0.0, help="Spend limit for this one-image materialization."),
    image_quality: Optional[str] = typer.Option(None, "--image-quality", help="Image-quality level to record in receipts."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable output."),
) -> None:
    """Materialize one generated route image into an existing real-director pack."""
    _run_image_materialize_pack(
        pack,
        out=out,
        image_provider=image_provider,
        env_file=env_file,
        allow_paid=allow_paid,
        spend_limit_usd=spend_limit_usd,
        image_quality=image_quality,
        json_output=json_output,
    )


@image_app.command("materialize")
def image_materialize_command(
    pack: Path = typer.Argument(..., help="Source pack directory or london-pack.json."),
    out: Path = typer.Option(..., "--out", help="Output directory for the materialized pack."),
    image_provider: str = typer.Option(..., "--image-provider", help="Explicit image provider to use."),
    env_file: Path = typer.Option(..., "--env-file", help="Explicit env file to read for this command only."),
    allow_paid: bool = typer.Option(False, "--allow-paid", help="Allow paid providers for this one-image materialization."),
    spend_limit_usd: Optional[float] = typer.Option(None, "--spend-limit-usd", min=0.0, help="Spend limit for this one-image materialization."),
    image_quality: Optional[str] = typer.Option(None, "--image-quality", help="Image-quality level to record in receipts."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable output."),
) -> None:
    """Alias for materialize-pack."""
    image_materialize_pack_command(
        pack,
        out=out,
        image_provider=image_provider,
        env_file=env_file,
        allow_paid=allow_paid,
        spend_limit_usd=spend_limit_usd,
        image_quality=image_quality,
        json_output=json_output,
    )


@app.command("session")
def session_command(
    brief: Path = typer.Argument(..., help="Brief markdown to run through the London session."),
    out: Path = typer.Option(Path("london-pack"), "--out", help="Output directory for the London pack."),
    fixture: bool = typer.Option(False, "--fixture", help="Use explicit deterministic fixture routes."),
    offline: bool = typer.Option(False, "--offline", "--deterministic", help="Use the deterministic OfflineDirector (no model) instead of the default model director."),
    images: Optional[str] = typer.Option(None, "--images", help="Image mode: auto, none, or fixture."),
    image_provider: Optional[str] = typer.Option(None, "--image-provider", help="Image provider: auto, automatic1111, comfyui, draw-things, external-cmd, gemini, openai, bfl, fal, replicate, pollinations, manual-prompt, none, or fixture."),
    image_quality: Optional[str] = typer.Option(None, "--image-quality", help="Image-quality level: model-default (keyless auto-ladder), gemini, or bfl. Omit on a TTY to pick interactively; non-TTY/CI defaults to model-default."),
    max_generated_routes: Optional[int] = typer.Option(None, "--max-generated-routes", min=0, help="Limit provider-backed image generation, prioritizing the recommended route."),
    env_file: Optional[Path] = typer.Option(None, "--env-file", help="Explicit env file to read for this run only."),
    artifact_type: Optional[str] = typer.Option(None, "--artifact", help="Artifact type override: website, app, product, brand, or generic."),
    show_me_selection: Optional[Path] = typer.Option(None, "--show-me-selection", help="Recorded London, Show Me selection to feed into the next model pass."),
    font_asset: Optional[Path] = typer.Option(None, "--font-asset", help="Copy a licensed local font file into the pack for launch proof."),
    font_shelf_family: Optional[str] = typer.Option(None, "--font-shelf-family", help="Copy an approved bundled London Type Shelf font into the pack."),
    font_family: Optional[str] = typer.Option(None, "--font-family", help="Required with --font-asset; rendered @font-face family."),
    font_source_label: Optional[str] = typer.Option(None, "--font-source-label", help="Required with --font-asset; public source/license label."),
    font_license_note: Optional[str] = typer.Option(None, "--font-license-note", help="Required with --font-asset; public license note."),
    assume_yes: bool = typer.Option(False, "--yes", "-y", help="Non-interactive: never prompt; default the image-quality level to model-default."),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing london-pack.json in the output directory."),
) -> None:
    """Run London on a brief."""
    write_london_pack(
        brief,
        out,
        fixture=fixture,
        offline=offline,
        image_provider=_image_mode_to_provider(images, image_provider),
        image_quality=image_quality,
        assume_yes=assume_yes,
        max_generated_routes=max_generated_routes,
        env_file=env_file,
        artifact_type=artifact_type,
        show_me_selection=show_me_selection,
        font_asset=font_asset,
        font_shelf_family=font_shelf_family,
        font_family=font_family,
        font_source_label=font_source_label,
        font_license_note=font_license_note,
        force=force,
    )
    console.print(f"London session pack written to {out}")


@app.command("show-me")
def show_me_command(
    pack: Path = typer.Argument(..., help="Pack directory or london-pack.json."),
    out: Optional[Path] = typer.Option(None, "--out", help="Directory for show-me-selection.json."),
    ack_token_cost: bool = typer.Option(False, "--ack-token-cost", help="Acknowledge that this companion is token-intensive."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable gate/server status."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Check gates without starting a server."),
    host: str = typer.Option("127.0.0.1", "--host", help="Local bind host."),
    port: int = typer.Option(0, "--port", min=0, help="Local bind port; 0 auto-selects."),
    timeout: int = typer.Option(300, "--timeout", min=0, help="Seconds to wait for a click before shutdown."),
) -> None:
    """Start the opt-in London, Show Me visual companion."""
    _run_show_me(
        pack,
        out=out,
        ack_token_cost=ack_token_cost,
        json_output=json_output,
        dry_run=dry_run,
        host=host,
        port=port,
        timeout=timeout,
    )


@app.command("launch-gate")
def launch_gate_command(
    pack: Path = typer.Argument(..., help="Pack directory or london-pack.json to evaluate."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable launch gate results."),
) -> None:
    """Evaluate the Phase 8 launch gate for a pack."""
    _run_launch_gate(pack, json_output=json_output)


@gallery_app.command("build")
def gallery_build_command(
    pack_dirs: list[Path] = typer.Argument(..., help="Pack directories to include."),
    out: Path = typer.Option(Path("london-gallery"), "--out", help="Output directory for the gallery."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable gallery output paths."),
) -> None:
    """Build a public proof gallery from one or more pack directories."""
    _run_gallery_build(pack_dirs, out=out, json_output=json_output)


@app.command("intake")
def intake_command(
    out: Path = typer.Option(Path("london-intake.html"), "--out", help="Output HTML path."),
    print_markdown: bool = typer.Option(False, "--print-markdown", help="Print markdown from open-text fields instead of writing HTML."),
    brief: Optional[str] = typer.Option(None, "--brief", help="Required when --print-markdown is used."),
    refusals: Optional[str] = typer.Option(None, "--refusals", help="Optional open-text refusal notes."),
    anti_audience: Optional[str] = typer.Option(None, "--anti-audience", help="Optional open-text anti-audience notes."),
    seeds: Optional[str] = typer.Option(None, "--seeds", help="Optional open-text seed notes."),
    artifact_hint: Optional[str] = typer.Option(None, "--artifact-hint", help="Optional open-text artifact hint; does not override London."),
) -> None:
    """Write the local London intake surface."""
    _run_intake(
        out=out,
        print_markdown=print_markdown,
        brief=brief,
        refusals=refusals,
        anti_audience=anti_audience,
        seeds=seeds,
        artifact_hint=artifact_hint,
    )


@app.command("validate-chassis")
def validate_chassis_command(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable validation status."),
    captures_dir: Optional[Path] = typer.Option(
        None,
        "--captures-dir",
        help="Directory containing Phase-4.6 capture JSON files; required outside a source checkout.",
    ),
    write_html_dir: Optional[Path] = typer.Option(None, "--write-html-dir", help="Write rendered scenario HTML files for inspection."),
) -> None:
    """Run the cross-brief chassis validation harness."""
    _run_validate_chassis(json_output=json_output, captures_dir=captures_dir, write_html_dir=write_html_dir)


@app.callback(
    invoke_without_command=True,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def root(ctx: typer.Context) -> None:
    """London Osei creative director CLI."""


DEFAULT_IMAGE_QUALITY_LEVEL = _pack_build.DEFAULT_IMAGE_QUALITY_LEVEL
IMAGE_QUALITY_LEVELS = _pack_build.IMAGE_QUALITY_LEVELS
_image_quality_options = _pack_build._image_quality_options
_image_quality_readiness = _pack_build._image_quality_readiness
_image_quality_to_provider = _pack_build._image_quality_to_provider
_explicit_provider_selection = _pack_build._explicit_provider_selection
build_london_session_artifact = _pack_build.build_london_session_artifact
_apply_launch_font_shelf = _pack_build._apply_launch_font_shelf
_apply_launch_font_asset = _pack_build._apply_launch_font_asset
_copy_font_asset_contents = _pack_build._copy_font_asset_contents
_write_visual_routes = _pack_build._write_visual_routes
_route_ids_for_image_generation = _pack_build._route_ids_for_image_generation
_materialize_asset_src = _pack_build._materialize_asset_src
_stamp_receipt_asset_proof = _pack_build._stamp_receipt_asset_proof
_write_handoff_docs = _pack_build._write_handoff_docs
_pack_receipts = _pack_build._pack_receipts


def _prompt_image_quality(options: Sequence[str]) -> str:
    """Interactive image-quality menu (TTY only). Lists only ready options."""

    console.print("Select image-quality level:")
    for index, option in enumerate(options, start=1):
        console.print(f"  {index}) {option}")
    try:
        raw = typer.prompt("Image quality", default="model-default")
    except (EOFError, KeyboardInterrupt, typer.Abort):
        raise
    except Exception:
        return "model-default"
    choice = str(raw).strip().lower()
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(options):
            return options[idx]
    if choice in options:
        return choice
    return "model-default"


def _resolve_image_quality(
    image_quality: str | None,
    *,
    env: Mapping[str, str],
    assume_yes: bool = False,
) -> str:
    try:
        return _pack_build._resolve_image_quality(
            image_quality,
            env=env,
            assume_yes=assume_yes,
            prompt_image_quality=_prompt_image_quality,
        )
    except LondonUsageError as exc:
        raise typer.BadParameter(str(exc)) from exc


def validate_pack(pack: Mapping[str, object]) -> None:
    try:
        _pack_build.validate_pack(pack)
    except LondonUsageError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _resolve_director(
    *,
    offline: bool,
    director: CreativeDirector | None,
    env: Mapping[str, str],
) -> CreativeDirector:
    return _pack_build._resolve_director(offline=offline, director=director, env=env)


def _director_mode(director: CreativeDirector, *, offline: bool) -> str:
    return _pack_build._director_mode(director, offline=offline)


def write_london_pack(
    brief_path: Path,
    out_dir: Path,
    *,
    fixture: bool = False,
    offline: bool = False,
    image_provider: str | None = None,
    image_quality: str | None = None,
    assume_yes: bool = False,
    max_generated_routes: int | None = None,
    env_file: Path | None = None,
    director: CreativeDirector | None = None,
    artifact_type: str | None = None,
    show_me_selection: Path | Mapping[str, object] | None = None,
    font_asset: Path | None = None,
    font_shelf_family: str | None = None,
    font_family: str | None = None,
    font_source_label: str | None = None,
    font_license_note: str | None = None,
    force: bool = False,
) -> dict[str, object]:
    """CLI-facing pack writer: preserve Typer usage errors at the boundary."""

    try:
        return _pack_build.write_london_pack(
            brief_path,
            out_dir,
            fixture=fixture,
            offline=offline,
                image_provider=image_provider,
            image_quality=image_quality,
            assume_yes=assume_yes,
            max_generated_routes=max_generated_routes,
            env_file=env_file,
            director=director,
            artifact_type=artifact_type,
            show_me_selection=show_me_selection,
            font_asset=font_asset,
            font_shelf_family=font_shelf_family,
            font_family=font_family,
            font_source_label=font_source_label,
            font_license_note=font_license_note,
            force=force,
            resolve_director=_resolve_director,
            resolve_image_quality=_resolve_image_quality,
            validate_pack_func=validate_pack,
            enrich_workbench_pack_func=enrich_workbench_pack,
            generate_route_concept_func=generate_route_concept,
        )
    except LondonUsageError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _write_public_pack_files(pack: dict[str, object], out_dir: Path) -> None:
    try:
        _pack_build._write_public_pack_files(pack, out_dir, validate_pack_func=validate_pack)
    except LondonUsageError as exc:
        raise typer.BadParameter(str(exc)) from exc
