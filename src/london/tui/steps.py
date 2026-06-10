"""Pure-function step generator for the London guided installer TUI.

All logic for "what steps are needed for this profile + this status" lives here.
The App stays thin — it calls these functions and renders results.
No textual imports; fully unit-testable without a display.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

PROFILES = ("core", "recommended", "pro-image", "details")


@dataclass
class GuidedStep:
    """One step in the guided setup flow.

    Attributes
    ----------
    id:             Machine-readable identifier (e.g. "model_path").
    title:          Short title line shown at the top of the step.
    subtitle:       Subtitle / step-count context (e.g. "step 1 of 3 · model path").
    body:           Multi-line explanation text rendered in the step body.
    terminal_cmd:   Command to run in another terminal (shown on the left column).
    paste_hint:     Brief label for the paste-key shortcut (shown on the right column), or "".
    recheck_label:  Label for the re-check action (default "[r] re-check").
    skip_label:     Label for the skip action, or "" if skip is not available.
    skip_note:      Explanation of what happens when skipping.
    status_keys:    List of env-var or status keys to show as detected / not-detected rows.
    cost_disclosure:  Non-empty when the step requires the W0-09 paid disclosure.
    allows_paste:   True when the user may paste a key that will be written to .env.
    paste_env_var:  The specific env var this step's paste writes, or "" if allows_paste=False.
    """

    id: str
    title: str
    subtitle: str
    body: str
    terminal_cmd: str = ""
    paste_hint: str = ""
    recheck_label: str = "[r] re-check"
    skip_label: str = ""
    skip_note: str = ""
    status_keys: list[dict[str, Any]] = field(default_factory=list)
    cost_disclosure: str = ""
    allows_paste: bool = False
    paste_env_var: str = ""


@dataclass
class ProfileSteps:
    """The full ordered set of steps for one profile on one machine."""

    profile_id: str
    profile_label: str
    steps: list[GuidedStep]
    first_command: str  # The copyable done-screen command
    done_note: str  # Extra note shown on the done screen


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def collect_setup_status_summary(status: dict[str, Any]) -> dict[str, Any]:
    """Extract the TUI-relevant fields from a full ``collect_setup_status()`` dict.

    Returns a smaller dict that steps.py functions use internally.
    This function is the ONLY place TUI logic reads from the status dict —
    ensuring one source of truth and making tests trivial to write.
    """
    direction = status.get("direction_mode") if isinstance(status.get("direction_mode"), dict) else {}
    mode = str(direction.get("mode") or "none")
    verdict = str(status.get("verdict") or "CORE READY")
    blocked = status.get("status") == "blocked"

    image = status.get("image_generation") if isinstance(status.get("image_generation"), dict) else {}
    selected_provider = str(image.get("selected_provider") or "manual-prompt")
    allow_paid = bool(image.get("allow_paid", False))
    price_ceilings = dict(image.get("price_ceilings_usd") if isinstance(image.get("price_ceilings_usd"), dict) else {})
    price_verified = str(image.get("price_ceiling_last_verified") or "2026-06-09")

    providers = {
        str(p["id"]): p
        for p in status.get("providers", [])
        if isinstance(p, dict)
    }
    gemini_key = _any_env_present(providers.get("gemini", {}))
    openai_key = _any_env_present(providers.get("openai", {}))
    bfl_key = _any_env_present(providers.get("bfl_flux", {}))
    anthropic_key = bool(direction.get("model_key_present"))

    paid_policy_ready = allow_paid and bool(
        (image.get("config") if isinstance(image.get("config"), dict) else {}).get("spend_limit_usd", 0)
    )

    has_local_generator = any(
        p.get("id") in {"automatic1111", "comfyui", "draw_things", "external_cmd"}
        and bool(p.get("ready_generate"))
        for p in status.get("providers", [])
        if isinstance(p, dict)
    )
    has_live_image = selected_provider not in {"manual-prompt", "none", "fixture"}

    return {
        "verdict": verdict,
        "blocked": blocked,
        "direction_mode": mode,
        "model_key_present": anthropic_key,
        "in_session": mode == "in_session",
        "api_ready": mode == "api",
        "gemini_key": gemini_key,
        "openai_key": openai_key,
        "bfl_key": bfl_key,
        "allow_paid": allow_paid,
        "paid_policy_ready": paid_policy_ready,
        "selected_provider": selected_provider,
        "has_local_generator": has_local_generator,
        "has_live_image": has_live_image,
        "price_ceilings": price_ceilings,
        "price_verified": price_verified,
    }


def _any_env_present(provider_row: dict[str, Any]) -> bool:
    """True if any env check in the provider row is present."""
    return any(
        bool(e.get("present"))
        for e in provider_row.get("env", [])
        if isinstance(e, dict)
    )


def steps_for_profile(profile_id: str, status: dict[str, Any]) -> ProfileSteps:
    """Return the ordered guided steps for *profile_id* given *status*.

    *status* is the full dict from ``collect_setup_status()``.
    This is the primary entry point for the TUI.
    """
    summary = collect_setup_status_summary(status)
    profile_id = profile_id.strip().lower()

    if profile_id in {"core", "core-demo", "keyless"}:
        return _steps_core(summary)
    if profile_id in {"recommended"}:
        return _steps_recommended(summary)
    if profile_id in {"pro-image", "pro_image", "pro"}:
        return _steps_pro_image(summary)
    if profile_id in {"details"}:
        return _steps_details(summary)

    # Default fallback to core
    return _steps_core(summary)


# ---------------------------------------------------------------------------
# Per-profile step builders
# ---------------------------------------------------------------------------


def _steps_core(s: dict[str, Any]) -> ProfileSteps:
    """Core demo — keyless profile."""
    steps: list[GuidedStep] = []

    # Step: Model path (only if no model is reachable)
    if not s["in_session"] and not s["api_ready"]:
        steps.append(_model_path_step(s, step_n=len(steps) + 1, total=None))

    total = len(steps) + 1  # +1 for the implicit "all set" step
    # Renumber if we added steps
    for i, step in enumerate(steps):
        step.subtitle = f"step {i + 1} of {len(steps)} · {_step_subtitle_label(step.id)}"

    if s["in_session"]:
        first_cmd = "london examples/brief.md --offline --out my-first-pack"
        done_note = "then open my-first-pack/index.html"
    elif s["api_ready"]:
        first_cmd = "london examples/brief.md --out my-first-pack"
        done_note = "then open my-first-pack/index.html"
    else:
        first_cmd = "london examples/brief.md --offline --out my-first-pack"
        done_note = "then open my-first-pack/index.html"

    return ProfileSteps(
        profile_id="core",
        profile_label="Core demo",
        steps=steps,
        first_command=first_cmd,
        done_note=done_note,
    )


def _steps_recommended(s: dict[str, Any]) -> ProfileSteps:
    """Recommended profile — local generators or Gemini/OpenAI."""
    steps: list[GuidedStep] = []

    # Model path (if missing)
    if not s["in_session"] and not s["api_ready"]:
        steps.append(_model_path_step(s, step_n=len(steps) + 1, total=None))

    # Image lane (if no key or local generator)
    if not s["has_local_generator"] and not s["gemini_key"] and not s["openai_key"]:
        steps.append(_image_lane_step(s, step_n=len(steps) + 1, total=None))

    total = len(steps)
    for i, step in enumerate(steps):
        step.subtitle = f"step {i + 1} of {total} · {_step_subtitle_label(step.id)}"

    if s["in_session"] or s["api_ready"]:
        first_cmd = "london examples/brief.md --out my-first-pack"
    else:
        first_cmd = "london examples/brief.md --offline --out my-first-pack"

    return ProfileSteps(
        profile_id="recommended",
        profile_label="Recommended",
        steps=steps,
        first_command=first_cmd,
        done_note="then open my-first-pack/index.html",
    )


def _steps_pro_image(s: dict[str, Any]) -> ProfileSteps:
    """Pro image lab — BFL/FLUX with explicit paid consent."""
    steps: list[GuidedStep] = []

    # Model path (if missing)
    if not s["in_session"] and not s["api_ready"]:
        steps.append(_model_path_step(s, step_n=len(steps) + 1, total=None))

    # Image lane (always show if no local generator and no existing key)
    if not s["has_local_generator"] and not s["gemini_key"] and not s["openai_key"]:
        steps.append(_image_lane_step(s, step_n=len(steps) + 1, total=None))

    # BFL paid gate (always shown for this profile — cost disclosure mandatory)
    if not s["paid_policy_ready"]:
        steps.append(_paid_gate_step(s, step_n=len(steps) + 1, total=None))

    total = len(steps)
    for i, step in enumerate(steps):
        step.subtitle = f"step {i + 1} of {total} · {_step_subtitle_label(step.id)}"

    if s["in_session"] or s["api_ready"]:
        first_cmd = "london examples/brief.md --out my-first-pack"
    else:
        first_cmd = "london examples/brief.md --offline --out my-first-pack"

    return ProfileSteps(
        profile_id="pro-image",
        profile_label="Pro image lab",
        steps=steps,
        first_command=first_cmd,
        done_note="then open my-first-pack/index.html",
    )


def _steps_details(s: dict[str, Any]) -> ProfileSteps:
    """Details profile — just the status table, no guided steps."""
    return ProfileSteps(
        profile_id="details",
        profile_label="Details",
        steps=[],
        first_command="london providers list",
        done_note="run london setup --json for machine-readable status",
    )


# ---------------------------------------------------------------------------
# Individual step constructors
# ---------------------------------------------------------------------------

_MODEL_PATH_BODY = """\
London is model-driven by default. To generate real creative direction
you need one of:

  • Run inside Claude Code — no key needed, in-session model provides
    the creative thinking.

  • Set ANTHROPIC_API_KEY — standalone key path for london run outside
    a Claude Code session.

  • Run --offline — uses the deterministic OfflineDirector (labeled
    template demo, not model-driven creative direction).\
"""


def _model_path_step(s: dict[str, Any], step_n: int, total: int | None) -> GuidedStep:
    if s["in_session"]:
        body = "Claude Code session detected — no key needed. London is model-ready."
        paste_hint = ""
        allows_paste = False
        paste_env_var = ""
        terminal_cmd = ""
    elif s["api_ready"]:
        body = "ANTHROPIC_API_KEY detected — API model path is ready."
        paste_hint = ""
        allows_paste = False
        paste_env_var = ""
        terminal_cmd = ""
    else:
        body = _MODEL_PATH_BODY
        paste_hint = "[ p ] paste — masked,\n      saved only to .env"
        allows_paste = True
        paste_env_var = "ANTHROPIC_API_KEY"
        terminal_cmd = "export ANTHROPIC_API_KEY=...\n  (or add to ./.env)"

    return GuidedStep(
        id="model_path",
        title="Model path",
        subtitle=f"step {step_n} of {total or '?'} · model path",
        body=body,
        terminal_cmd=terminal_cmd,
        paste_hint=paste_hint,
        recheck_label="[r] re-check",
        skip_label="[s] skip — run --offline instead",
        skip_note="--offline uses the deterministic template demo (no model)",
        status_keys=[
            {"label": "Claude Code session", "present": s["in_session"]},
            {"label": "ANTHROPIC_API_KEY", "present": s["model_key_present"]},
        ],
        allows_paste=allows_paste,
        paste_env_var=paste_env_var,
    )


_IMAGE_LANE_BODY = """\
No image key detected. Two ways in:

  in another terminal:                 or paste here:
  $ export GEMINI_API_KEY=...          [ p ] paste — masked,
    (or add to ./.env)                       saved only to .env

Visual boards work keyless with manual-prompt — skip if that's fine.\
"""

_COST_DISCLOSURE = (
    "Metered image disclosure (W0-09): Gemini 4K <= ${gemini:.2f}/image, "
    "OpenAI 4K/high <= ${openai:.2f}/image (verified {verified}).\n"
    "Downshift: london config set image.quality standard"
)


def _image_lane_step(s: dict[str, Any], step_n: int, total: int | None) -> GuidedStep:
    gemini_ceil = float(s["price_ceilings"].get("gemini", 0.25))
    openai_ceil = float(s["price_ceilings"].get("openai", 0.35))
    verified = s["price_verified"]

    disclosure = (
        f"Metered image disclosure (W0-09): Gemini 4K <= ${gemini_ceil:.2f}/image, "
        f"OpenAI 4K/high <= ${openai_ceil:.2f}/image (verified {verified}).\n"
        "Downshift: london config set image.quality standard"
    )

    status_keys = [
        {"label": "GEMINI_API_KEY", "present": s["gemini_key"]},
        {"label": "OPENAI_API_KEY", "present": s["openai_key"]},
        {"label": "local ComfyUI", "present": s["has_local_generator"]},
    ]

    return GuidedStep(
        id="image_lane",
        title="Image lane",
        subtitle=f"step {step_n} of {total or '?'} · image lane",
        body=_IMAGE_LANE_BODY,
        terminal_cmd="$ export GEMINI_API_KEY=...\n  (or add to ./.env)",
        paste_hint="[ p ] paste — masked,\n      saved only to .env",
        recheck_label="[r] re-check",
        skip_label="[s] skip — visual boards work keyless",
        skip_note="visual direction boards are available without any image key",
        status_keys=status_keys,
        cost_disclosure=disclosure,
        allows_paste=True,
        paste_env_var="GEMINI_API_KEY",
    )


_PAID_GATE_BODY = """\
BFL/FLUX is the pro image lane. Generating with it requires:

  1. Setting BFL_API_KEY in your environment or ./.env
  2. Running:  london config set image.allow_paid true
  3. Running:  london config set image.spend_limit_usd 5.0

London will never call a paid provider without both flags set.
The per-image ceiling is enforced BEFORE any API call.\
"""


def _paid_gate_step(s: dict[str, Any], step_n: int, total: int | None) -> GuidedStep:
    gemini_ceil = float(s["price_ceilings"].get("gemini", 0.25))
    openai_ceil = float(s["price_ceilings"].get("openai", 0.35))
    verified = s["price_verified"]

    disclosure = (
        f"Cost disclosure (W0-09): BFL/FLUX is a paid metered provider.\n"
        f"Other paid lanes: Gemini 4K <= ${gemini_ceil:.2f}/image, "
        f"OpenAI 4K/high <= ${openai_ceil:.2f}/image (verified {verified}).\n"
        "These gates apply: image.allow_paid=true AND image.spend_limit_usd > 0.\n"
        "Downshift: london config set image.quality standard"
    )

    return GuidedStep(
        id="paid_gate",
        title="Paid image gate",
        subtitle=f"step {step_n} of {total or '?'} · paid gate",
        body=_PAID_GATE_BODY,
        terminal_cmd=(
            "$ export BFL_API_KEY=...\n"
            "  london config set image.allow_paid true\n"
            "  london config set image.spend_limit_usd 5.0"
        ),
        paste_hint="[ p ] paste BFL key — masked,\n      saved only to .env",
        recheck_label="[r] re-check",
        skip_label="[s] skip — keep paid lane off",
        skip_note="paid providers remain blocked until you enable them manually",
        status_keys=[
            {"label": "BFL_API_KEY", "present": s["bfl_key"]},
            {"label": "image.allow_paid", "present": s["allow_paid"]},
            {"label": "image.spend_limit_usd", "present": s["paid_policy_ready"]},
        ],
        cost_disclosure=disclosure,
        allows_paste=True,
        paste_env_var="BFL_API_KEY",
    )


def _step_subtitle_label(step_id: str) -> str:
    return {
        "model_path": "model path",
        "image_lane": "image lane",
        "paid_gate": "paid gate",
    }.get(step_id, step_id)


# ---------------------------------------------------------------------------
# Capability map rows (for Frame 2)
# ---------------------------------------------------------------------------

CAPABILITY_CHIP_MAP = {
    "in_session": "IN-SESSION MODEL",
    "api": "API MODEL",
    "none": "NO MODEL — use --offline",
    "claude_cli_print": "CLI PRINT MODEL",
}

CAPABILITY_ROW_IDS = [
    "core_engine",
    "deterministic_pack",
    "browser_capture",
    "multimodal_direction",
    "image_generation",
    "web_extraction",
    "design_bridges",
]

CAPABILITY_ROW_LABELS = {
    "core_engine": "Core engine",
    "deterministic_pack": "Local pack builder",
    "browser_capture": "Browser capture",
    "multimodal_direction": "Vision reading",
    "image_generation": "Image generation",
    "web_extraction": "Web discovery",
    "design_bridges": "Design bridges",
}


def capability_map_rows(status: dict[str, Any]) -> list[dict[str, Any]]:
    """Return ordered capability rows for the hero screen (Frame 2).

    Each row has: id, label, chip (display text), ready (bool), detail.
    """
    s = collect_setup_status_summary(status)
    capabilities = {
        str(c["id"]): c
        for c in status.get("capabilities", [])
        if isinstance(c, dict)
    }
    direction = status.get("direction_mode") if isinstance(status.get("direction_mode"), dict) else {}

    rows = []

    # Core engine — derived from direction_mode, not capabilities list
    mode = s["direction_mode"]
    chip = CAPABILITY_CHIP_MAP.get(mode, "NO MODEL")
    detail = str(direction.get("hint") or "Run inside Claude Code or set ANTHROPIC_API_KEY.")
    rows.append({"id": "core_engine", "label": "Core engine", "chip": chip, "ready": s["in_session"] or s["api_ready"], "detail": detail})

    # Standard capabilities
    for cap_id in CAPABILITY_ROW_IDS[1:]:
        cap = capabilities.get(cap_id, {})
        ready = bool(cap.get("ready", False))

        if cap_id == "image_generation":
            chip = _image_chip(s)
        elif cap_id == "design_bridges":
            # Design bridges = optional; always show OPTIONAL
            chip = "LOCAL LAB READY" if s["has_local_generator"] else "OPTIONAL"
        else:
            chip = "READY" if ready else "MISSING"

        detail = _capability_detail(cap_id, status, s)
        rows.append({
            "id": cap_id,
            "label": CAPABILITY_ROW_LABELS.get(cap_id, cap_id),
            "chip": chip,
            "ready": ready,
            "detail": detail,
        })

    return rows


def _image_chip(s: dict[str, Any]) -> str:
    provider = s["selected_provider"]
    if provider == "manual-prompt":
        return "VISUAL BOARDS READY"
    if provider == "none":
        return "DISABLED"
    if provider == "fixture":
        return "FIXTURE ONLY"
    return f"{provider.upper()} READY"


def _capability_detail(cap_id: str, status: dict[str, Any], s: dict[str, Any]) -> str:
    details = {
        "deterministic_pack": (
            "Builds the London pack JSON and HTML dossier locally — "
            "no cloud dependency. Always available."
        ),
        "browser_capture": (
            "Playwright screenshots for QA evidence and the launch harness. "
            "Install: pip install playwright && playwright install chromium"
        ),
        "multimodal_direction": (
            "Gemini / OpenAI vision for image critique and direction reading. "
            "Needs GEMINI_API_KEY or OPENAI_API_KEY."
        ),
        "image_generation": (
            f"Selected lane: {s['selected_provider']}. "
            "Keyless: visual direction boards (no generated images). "
            "Add GEMINI_API_KEY or OPENAI_API_KEY to enable generation."
        ),
        "web_extraction": (
            "Firecrawl for source hydration and web discovery. "
            "Needs FIRECRAWL_API_KEY and: pip install firecrawl-py"
        ),
        "design_bridges": (
            "Local generators (ComfyUI, A1111, Draw Things, external-cmd). "
            "Configure LONDON_COMFYUI_URL or LONDON_DRAW_THINGS_COMMAND."
        ),
    }
    return details.get(cap_id, "")


# ---------------------------------------------------------------------------
# Profile picker rows (for Frame 3)
# ---------------------------------------------------------------------------

PROFILE_ROWS = [
    {
        "id": "core",
        "number": "1",
        "label": "Core demo",
        "tagline": "keyless · bundled brain · visual boards",
        "paid": False,
    },
    {
        "id": "recommended",
        "number": "2",
        "label": "Recommended",
        "tagline": "local generators or a Gemini/OpenAI lane",
        "paid": False,
    },
    {
        "id": "pro-image",
        "number": "3",
        "label": "Pro image lab",
        "tagline": "BFL/FLUX · paid · explicit spend consent",
        "paid": True,
    },
    {
        "id": "details",
        "number": "4",
        "label": "Just details",
        "tagline": "provider table + raw status",
        "paid": False,
    },
]


# ---------------------------------------------------------------------------
# Verdict helpers
# ---------------------------------------------------------------------------


def verdict_line(status: dict[str, Any]) -> str:
    """One-line verdict for the splash/done screens."""
    s = collect_setup_status_summary(status)
    if s["blocked"]:
        return "BLOCKED — see london setup --json for details"
    if s["in_session"]:
        return "CORE READY — the keyless demo works right now"
    if s["api_ready"]:
        return "CORE READY — API key detected"
    return "CORE READY — the keyless demo works right now"
