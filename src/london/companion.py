from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs

from .assets import normalize_palette, pack_routes, slugify
from .text import clean_title, display_text

TOKEN_COST_CAVEAT = "London, Show Me is token-intensive. Start it only after you acknowledge this is token-intensive."
MODEL_PATH_UNAVAILABLE = (
    "London, Show Me is available when running inside a model. Offline and standalone "
    "runs do not fake clicks, results, or London reasoning."
)
SELECTION_FILENAME = "show-me-selection.json"

_LOCAL_PATH_RE = re.compile(r"(/Users/[^\s\"']+|/tmp/[^\s\"']+|/private/[^\s\"']+|[A-Za-z]:[\\/][^\s\"']+)")
_SECRET_RE = re.compile(r"\b(?:sk|anthropic|openai|gemini|bfl|replicate|fal)-[A-Za-z0-9._-]{8,}\b", re.IGNORECASE)


@dataclass(frozen=True)
class CompanionOption:
    option_id: str
    route_ref: str
    title: str
    headline: str
    rationale: str
    artifact_type: str
    palette: tuple[dict[str, str], ...]
    layout_cues: tuple[str, ...]


@dataclass
class CompanionGate:
    started: bool
    reason: str
    message: str
    caveat: str = TOKEN_COST_CAVEAT
    url: str = ""
    selection_file: str = SELECTION_FILENAME

    def as_dict(self) -> dict[str, Any]:
        return {
            "started": self.started,
            "reason": self.reason,
            "message": self.message,
            "caveat": self.caveat,
            "url": self.url,
            "selection_file": self.selection_file,
            "secrets_printed": False,
        }


@dataclass
class RunningCompanion:
    httpd: ThreadingHTTPServer
    thread: threading.Thread
    selection_path: Path
    options: tuple[CompanionOption, ...]

    @property
    def url(self) -> str:
        host, port = self.httpd.server_address
        return f"http://{host}:{port}/"

    def stop(self) -> None:
        self.httpd.shutdown()
        self.thread.join(timeout=2)
        self.httpd.server_close()

    def wait_until_stopped(self, timeout: float = 30.0) -> bool:
        self.thread.join(timeout=timeout)
        return not self.thread.is_alive()


def load_pack(path: Path) -> dict[str, Any]:
    pack_path = path / "london-pack.json" if path.is_dir() else path
    data = json.loads(pack_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("London pack must be a JSON object")
    return data


def is_model_path_pack(pack: Mapping[str, Any]) -> bool:
    """Return true only when receipts say the direction was model-path-like."""

    receipts = pack.get("receipts")
    if not isinstance(receipts, list):
        return False
    for receipt in receipts:
        if not isinstance(receipt, Mapping) or receipt.get("kind") != "director":
            continue
        provider = display_text(receipt.get("provider"))
        if receipt.get("deterministic") is True:
            return False
        if provider in {"offline-template-preview", "fixture", "local-session", "local-deterministic"}:
            return False
        return provider in {"in_session", "keyed", "ClaudeCodeDirector", "FakeDirector"} or bool(provider)
    return False


def build_options(pack: Mapping[str, Any]) -> tuple[CompanionOption, ...]:
    artifact_type = display_text(pack.get("artifact_type"), fallback="generic")
    options: list[CompanionOption] = []
    for index, route in enumerate(pack_routes(pack), start=1):
        title = display_text(route.get("title"), fallback=f"Route {index}")
        route_ref = display_text(route.get("id") or route.get("title"), fallback=f"route-{index}")
        option_id = f"option-{index}-{slugify(title, fallback='route')}"
        sections = route.get("sections") if isinstance(route.get("sections"), list) else []
        cues = tuple(
            display_text(section.get("title"))
            for section in sections
            if isinstance(section, Mapping) and display_text(section.get("title"))
        )
        options.append(
            CompanionOption(
                option_id=option_id,
                route_ref=route_ref,
                title=title,
                headline=display_text(route.get("headline") or route.get("subhead") or route.get("thesis")),
                rationale=display_text(route.get("rationale") or route.get("lore")),
                artifact_type=artifact_type,
                palette=tuple(normalize_palette(route.get("palette"))),
                layout_cues=cues or ("Hero proof", "Route section", "Handoff move"),
            )
        )
    return tuple(options)


def gate_for_pack(pack: Mapping[str, Any], *, ack_token_cost: bool) -> CompanionGate:
    if not ack_token_cost:
        return CompanionGate(
            started=False,
            reason="ack_required",
            message="Acknowledge the token-cost caveat before starting the local companion server.",
        )
    if not is_model_path_pack(pack):
        return CompanionGate(started=False, reason="model_path_required", message=MODEL_PATH_UNAVAILABLE)
    return CompanionGate(started=True, reason="ready", message="Ready to start the local companion server.")


def start_companion_server(
    pack: Mapping[str, Any],
    out_dir: Path,
    *,
    ack_token_cost: bool,
    host: str = "127.0.0.1",
    port: int = 0,
    stop_after_selection: bool = True,
) -> RunningCompanion:
    gate = gate_for_pack(pack, ack_token_cost=ack_token_cost)
    if not gate.started:
        raise ValueError(gate.message)
    out_dir.mkdir(parents=True, exist_ok=True)
    options = build_options(pack)
    selection_path = out_dir / SELECTION_FILENAME
    if selection_path.exists():
        selection_path.unlink()
    html = render_companion_html(pack, options, acknowledged=True)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: Any) -> None:  # noqa: A002 - stdlib API name
            return

        def do_GET(self) -> None:  # noqa: N802 - stdlib API name
            if self.path not in {"/", "/index.html"}:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._send_html(html)

        def do_POST(self) -> None:  # noqa: N802 - stdlib API name
            if self.path != "/select":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            length = int(self.headers.get("Content-Length", "0") or 0)
            payload = self.rfile.read(length).decode("utf-8")
            selected_id = parse_qs(payload).get("option_id", [""])[0]
            option = next((item for item in options if item.option_id == selected_id), None)
            if option is None:
                self.send_error(HTTPStatus.BAD_REQUEST, "Unknown companion option")
                return
            record = build_selection_record(pack, option)
            selection_path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
            self._send_html(render_companion_html(pack, options, acknowledged=True, selected=option))
            if stop_after_selection:
                threading.Thread(target=self.server.shutdown, daemon=True).start()

        def _send_html(self, body: str) -> None:
            encoded = body.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    httpd = ThreadingHTTPServer((host, port), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return RunningCompanion(httpd=httpd, thread=thread, selection_path=selection_path, options=options)


def render_companion_html(
    pack: Mapping[str, Any],
    options: tuple[CompanionOption, ...],
    *,
    acknowledged: bool,
    selected: CompanionOption | None = None,
    unavailable: bool = False,
) -> str:
    title = clean_title(pack, fallback="London Pack")
    option_cards = "".join(_option_card(option, disabled=unavailable or not acknowledged) for option in options)
    selected_html = (
        f"""<section class="selection-receipt" data-selection-recorded="true">
          <p class="kicker">Selection recorded</p>
          <h2>{escape(selected.title)}</h2>
          <p>This click was written as a selection artifact for London's next reasoning pass.</p>
        </section>"""
        if selected
        else ""
    )
    unavailable_html = f'<p class="unavailable">{escape(MODEL_PATH_UNAVAILABLE)}</p>' if unavailable else ""
    ack_label = "Acknowledged before server start" if acknowledged else "Not acknowledged"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} - London Show Me</title>
  <style>
    :root {{ --ink:#151515; --paper:#f8f5ec; --line:#d5cec0; --muted:#6f685f; --accent:#ff6b35; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; font-family: Inter, Arial, sans-serif; background:var(--paper); color:var(--ink); }}
    main {{ max-width:1180px; margin:0 auto; padding:32px 20px 48px; }}
    header {{ display:grid; gap:12px; border-bottom:1px solid var(--line); padding-bottom:22px; }}
    h1 {{ margin:0; font-family: Georgia, serif; font-size: clamp(34px, 5vw, 68px); line-height:1; letter-spacing:0; }}
    h2, h3, p {{ overflow-wrap:anywhere; }}
    .kicker {{ margin:0; color:var(--muted); text-transform:uppercase; font-size:12px; font-weight:700; letter-spacing:.06em; }}
    .caveat {{ margin:0; max-width:72ch; font-size:18px; line-height:1.5; }}
    .ack {{ display:inline-flex; width:max-content; border:1px solid var(--line); padding:8px 10px; font-size:13px; color:var(--muted); }}
    .unavailable {{ border-left:3px solid var(--accent); padding-left:14px; max-width:68ch; }}
    .option-grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(260px, 1fr)); gap:18px; margin-top:28px; }}
    .option-card {{ min-width:0; background:#fffdf8; border:1px solid var(--line); display:grid; grid-template-rows:auto 1fr auto; }}
    .mockup {{ min-height:190px; display:grid; grid-template-columns:1.05fr .95fr; gap:10px; padding:14px; background:var(--ink); }}
    .mock-panel {{ background:var(--paper); min-width:0; display:grid; align-content:end; padding:14px; }}
    .mock-panel strong {{ font-family:Georgia, serif; font-size:24px; line-height:1.05; }}
    .mock-stack {{ display:grid; gap:8px; }}
    .mock-row {{ min-height:34px; background:var(--paper); }}
    .card-body {{ padding:16px; display:grid; gap:10px; }}
    .card-body h2 {{ margin:0; font-size:22px; line-height:1.15; }}
    .card-body p {{ margin:0; line-height:1.5; color:#3a342f; }}
    .palette {{ display:flex; flex-wrap:wrap; gap:6px; }}
    .swatch {{ width:32px; height:32px; border:1px solid rgba(0,0,0,.16); }}
    .cue-list {{ margin:0; padding-left:18px; color:var(--muted); }}
    form {{ padding:0 16px 16px; }}
    button {{ width:100%; min-height:44px; border:1px solid var(--ink); background:var(--ink); color:var(--paper); font-weight:700; cursor:pointer; }}
    button:disabled {{ cursor:not-allowed; opacity:.45; }}
    .selection-receipt {{ margin-top:28px; border-top:1px solid var(--line); padding-top:18px; }}
    @media (max-width:640px) {{ main {{ padding:22px 14px 38px; }} .mockup {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
  <main data-companion-static="true" data-token-caveat="{escape(TOKEN_COST_CAVEAT, quote=True)}">
    <header>
      <p class="kicker">London, Show Me</p>
      <h1>{escape(title)}</h1>
      <p class="caveat">{escape(TOKEN_COST_CAVEAT)}</p>
      <p class="ack">{escape(ack_label)}</p>
      {unavailable_html}
    </header>
    <section class="option-grid" aria-label="Visual companion options">
      {option_cards}
    </section>
    {selected_html}
  </main>
</body>
</html>"""


def build_selection_record(pack: Mapping[str, Any], option: CompanionOption) -> dict[str, Any]:
    title = clean_title(pack, fallback="London Pack")
    reasoning_input = (
        "The user clicked a London, Show Me visual option. Continue the next reasoning pass "
        f"from route '{option.title}' ({option.route_ref}) for the {option.artifact_type} artifact. "
        "Treat the click as user feedback, not as a fabricated approval."
    )
    return {
        "schema_version": "london.show_me.selection.v1",
        "pack_ref": display_text(pack.get("pack_id"), fallback="london-pack"),
        "brief_title": _safe_text(title),
        "selected_option_id": _safe_text(option.option_id),
        "selected_route_ref": _safe_text(option.route_ref),
        "selected_route_title": _safe_text(option.title),
        "selected_artifact_type": _safe_text(option.artifact_type),
        "selection_source": "local_companion_click",
        "selection_round_trip": "recorded",
        "flows_back_to_london": True,
        "reasoning_input": _safe_text(reasoning_input),
        "secrets_printed": False,
        "local_paths_written": False,
        "selected_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


def selection_context(selection: Mapping[str, Any]) -> dict[str, str]:
    allowed = (
        "selected_option_id",
        "selected_route_ref",
        "selected_route_title",
        "selected_artifact_type",
        "reasoning_input",
    )
    return {key: _safe_text(selection.get(key)) for key in allowed if _safe_text(selection.get(key))}


def load_selection_context(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("London Show Me selection must be a JSON object")
    return selection_context(data)


def wait_for_http(url: str, *, timeout: float = 5.0) -> bool:
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:  # noqa: S310 - local smoke helper
                return response.status == HTTPStatus.OK
        except Exception:  # noqa: BLE001 - retry until timeout
            time.sleep(0.05)
    return False


def _option_card(option: CompanionOption, *, disabled: bool) -> str:
    swatches = "".join(
        f'<span class="swatch" title="{escape(color["name"], quote=True)}" style="background:{escape(color["hex"], quote=True)}"></span>'
        for color in option.palette
    )
    rows = "".join('<span class="mock-row"></span>' for _ in option.layout_cues)
    cues = "".join(f"<li>{escape(cue)}</li>" for cue in option.layout_cues)
    disabled_attr = " disabled" if disabled else ""
    return f"""<article class="option-card" data-option-id="{escape(option.option_id, quote=True)}">
      <div class="mockup" aria-hidden="true">
        <div class="mock-panel"><strong>{escape(option.title)}</strong></div>
        <div class="mock-stack">{rows}</div>
      </div>
      <div class="card-body">
        <p class="kicker">{escape(option.artifact_type)} option</p>
        <h2>{escape(option.title)}</h2>
        <p>{escape(option.headline or option.rationale)}</p>
        <div class="palette">{swatches}</div>
        <ul class="cue-list">{cues}</ul>
      </div>
      <form method="post" action="/select">
        <input type="hidden" name="option_id" value="{escape(option.option_id, quote=True)}">
        <button type="submit"{disabled_attr}>Choose this option</button>
      </form>
    </article>"""


def _safe_text(value: Any) -> str:
    text = display_text(value)
    text = _LOCAL_PATH_RE.sub("[redacted-local-path]", text)
    text = _SECRET_RE.sub("[redacted-secret]", text)
    return text.strip()
