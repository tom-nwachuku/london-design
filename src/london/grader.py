"""The engine grader — an OBJECTIVE instrument that audits London's real work (GRADE-02).

London does NOT grade his own homework. The ``RunTelemetry`` side-channel (Plan 02) is the
objective transcript of what the engine actually did — ground truth. The ``DirectionResult``
is a CLAIM. ``grade(direction, telemetry)`` cross-checks the claim against the transcript and
the measurable output, and emits a scrubbed ``grader`` block:

  * 5 NAMED objective inspectors (D-07), each a transcript-/output-measurable check, NO
    taste-grading:
      - **Source Auditor**     — every cited ``source-…`` ID verified against the transcript.
      - **Grounding Inspector**— real brain-query depth; flags thin/0-call; ``captured=False`` → n/a.
      - **Distinctness Referee**— routes genuinely differ (perceptual palette ΔE + title-token
                                 overlap), NOT exact-hex (which would never fire — Pitfall 6).
      - **Output Manifest**    — every required region filled at honest cardinality, no padding.
      - **Type Selection Referee** — Font Lab offers enough non-local/sourceable type range that
                                    actual-loaded local fonts stay a proof asset, not a bias trap.
  * a claim-integrity AUDIT (D-06): show-verified-only + a visible ``CLAIM_UNVERIFIED`` flag —
    a cited-but-unverified source is dropped from grounded AND lit, the run NEVER hard-fails.
  * a transparent weighted COMPOSITE (D-08): a documented roll-up of the 5 sub-scores; a clean
    run scores ~100, a 0-brain-call/confabulated run scores visibly LOW (~27 worked example).
  * a two-layer COPY data shape (D-09): a humanized ``headline`` layer + a collapsible raw
    ``detail`` layer — progressive disclosure expressed as DATA, never CSS, never a 2nd model.

Honesty invariants (D-11): NO fake gauges — every metric is transcript-real (from
``RunTelemetry``) or output-measurable (from the pack), or it is not on the panel. A
``captured=False`` path renders ``"n/a"`` — DISTINCT from a captured-but-zero dead engine
(near-dead composite + 0 lit sources). The grader can show a BAD run honestly; that honesty is
the entire point.

The module is SELF-CONTAINED — one input (``DirectionResult`` dict + ``RunTelemetry``), one
output (the scrubbed grader block) — testable in isolation, no renderer/director coupling. It
is PURE: stdlib (``math``/``re``) + the existing ``RunTelemetry`` model only; no network, no
file I/O, NO color library (the redmean ΔE is ~15 lines of stdlib ``math``). The brain
denominator is the LIVE value the telemetry already carries (read from the swappable inventory
at capture time — never hardcoded here). The grader's receipts carry ONLY query strings +
``source-…`` IDs + counts; raw finding bodies never enter, and the block routes through the
single ``scrub_pack`` chokepoint (session.py) before any write — NO second sanitizer here.
"""

from __future__ import annotations

import math
import re
from typing import Any

from london.director import RunTelemetry

# --- Tunable constants (the SHAPE is locked; the NUMBERS are documented + tunable) --------
#
# D-07/D-08 delegate the exact weights + thresholds to "Claude's Discretion" with the shape
# locked. Each is a NAMED constant with an inline tunability note so the contract is auditable
# and a future calibration pass (5.3) can adjust the number without touching the structure.

# Composite weights (RESEARCH A1) — Grounding + Source-Auditor stay heaviest because they
# are the two transcript-real "did the engine actually run / did it tell the truth" checks.
# The output-measurable checks split the rest, with type selection visible but not dominant.
COMPOSITE_WEIGHTS: dict[str, float] = {
    "grounding": 0.30,      # tunable A1
    "source_auditor": 0.25,  # tunable A1
    "distinctness": 0.18,   # tunable A1
    "output_manifest": 0.15,  # tunable A1
    "type_selection": 0.12,  # tunable A1 — local-font proof is allowed, local-font bias is not
}

# Grounding TARGET: the low end of the observed 7–11 brain-query range (fingerprint). A run at
# or above TARGET reads "fully grounded"; below it the inspector flags thin grounding.
GROUNDING_TARGET = 8  # tunable A1 — the low end of the observed 7–11 range

# Distinctness thresholds (RESEARCH A2). Palette: average nearest-neighbour redmean ΔE; below
# the threshold the two palettes are perceptually "near" → one idea in two outfits. Title: token
# Jaccard above the ceiling → the routes are named the same thing twice.
#
# CALIBRATED against the 5 real captures (all legitimately-distinct route pairs): their
# avg-nearest ΔE is {website 70.3, product 51.3, brand 38.8, app 94.6, generic 72.5}. The
# threshold sits at 35 — comfortably BELOW the real minimum (brand 38.8) so every real capture
# PASSES, and far ABOVE a genuine "one idea in two outfits" pair (a synthetic near palette reads
# ΔE ≈ 6). RESEARCH A2 assumed ~40; the brand capture (38.8) is the real low end, so 40 would
# spuriously fail a legit run — 35 is the honest calibrated value with a wide separating margin.
DISTINCTNESS_DE_THRESHOLD = 35.0   # tunable A2 — calibrated: real min 38.8 (brand), synthetic ≈6
DISTINCTNESS_TITLE_JACCARD_MAX = 0.5  # tunable A2 — title-token overlap ceiling

# The cited-source citation form London uses (RESEARCH Q4): a `source-{12hex}` token. The brain
# RETURNS this same `source-…` form as `findings[].source_ref`; the Plan 02 tap captures it into
# `consulted_source_ids`, so the audit compares LIKE-FOR-LIKE (never the 24-hex entry `id`).
_SOURCE_ID_RE = re.compile(r"source-[0-9a-f]{12}")

# A sentinel for "this sub-score is unavailable" (captured=False) — rendered "n/a", distinct
# from a real 0.0 (a captured dead engine). Composite math treats this as "drop from the roll-up
# and re-normalise the remaining weights" rather than scoring it 0.
_NA = "n/a"

# The required output regions + their honest minimum cardinality (no padded slots). A route's
# font lab must carry ≥3 tiers; per-route checks are averaged into the manifest fraction.
_MIN_ROUTES = 2
_MIN_CONVERSATION = 1
_MIN_FONT_OPTIONS_PER_ROUTE = 3
_MIN_COPY_BLOCKS = 1
_MIN_NEXT_STEPS = 1
_MIN_ROUTE_COMPARISON = 1
_FONT_TIERS = frozenset({"safe_local", "open_public", "premium_inspiration"})
_GENERIC_FONT_FAMILIES = frozenset(
    {
        "-apple-system",
        "arial",
        "blinkmacsystemfont",
        "georgia",
        "helvetica",
        "monospace",
        "sans-serif",
        "segoe ui",
        "serif",
        "system",
        "system-ui",
        "times new roman",
        "ui-monospace",
        "ui-sans-serif",
        "ui-serif",
    }
)


# --- perceptual colour distance (NO color library — stdlib redmean ΔE, ~15 lines) ---------


def _hex_rgb(value: str) -> tuple[int, int, int]:
    """Parse ``#rrggbb`` (or ``rrggbb``) → an (r, g, b) tuple. Tolerant of a leading ``#``."""

    h = value.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _de(hex1: str, hex2: str) -> float:
    """Redmean ΔE between two hex colours — a low-cost perceptual distance (no color lib).

    Reference: https://en.wikipedia.org/wiki/Color_difference#sRGB (the "redmean" weighting).
    Deterministic and dependency-free; sufficient to answer "are these two palettes near or far"
    — which is the only question the Distinctness Referee asks.
    """

    (r1, g1, b1), (r2, g2, b2) = _hex_rgb(hex1), _hex_rgb(hex2)
    rmean = (r1 + r2) / 2
    dr, dg, db = r1 - r2, g1 - g2, b1 - b2
    return math.sqrt((2 + rmean / 256) * dr * dr + 4 * dg * dg + (2 + (255 - rmean) / 256) * db * db)


# --- title-token overlap (the second distinctness sub-check) ------------------------------

_TITLE_TOKEN_RE = re.compile(r"[a-z0-9]+")
_TITLE_STOPWORDS = frozenset(
    {"the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "with", "route"}
)


def _title_tokens(title: str) -> set[str]:
    """Lowercased content tokens of a route title (stopwords + 1-char dropped)."""

    return {
        t for t in _TITLE_TOKEN_RE.findall((title or "").lower()) if t not in _TITLE_STOPWORDS and len(t) > 1
    }


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


# --- cited-source extraction (claim-integrity ground truth) -------------------------------


def extract_cited_source_ids(direction: dict) -> list[str]:
    """Every ``source-{12hex}`` token London CITES anywhere in the DirectionResult dump.

    Regex-scans the serialised direction for the `source-…` form (RESEARCH Q4). On all 5 real
    captures this is EMPTY — London cites references in prose ("Fukasawa", "Lloyd's registers"),
    not machine source IDs — so the show-verified-only policy degrades safely to "nothing
    claimed, nothing to flag". The synthetic confabulated case is what exercises the exception.
    Order-preserving + deduped.
    """

    import json

    blob = json.dumps(direction, ensure_ascii=False)
    seen: set[str] = set()
    cited: list[str] = []
    for match in _SOURCE_ID_RE.findall(blob):
        if match not in seen:
            seen.add(match)
            cited.append(match)
    return cited


# --- the 4 inspectors (each returns a sub-score + an objective verdict) --------------------


def _source_auditor(direction: dict, telemetry: RunTelemetry) -> dict:
    """Claim integrity (D-06): cited ``source-…`` IDs ✗/✓ vs the transcript ground truth.

    Show-verified-only — a cited source NOT in ``consulted_source_ids`` is dropped from the
    grounded receipts AND added to ``claim_unverified`` (lighting CLAIM_UNVERIFIED). NEVER
    raises, NEVER hard-fails the run. Sub-score = 1.0 if no over-claim, else verified/cited.
    """

    cited = extract_cited_source_ids(direction)
    if not telemetry.captured:
        audit = {
            "grounded_source_ids": [],
            "claim_unverified": [],
            "verdict": "TELEMETRY_UNAVAILABLE",
        }
        return {
            "key": "source_auditor",
            "name": "Source Auditor",
            "dimension": "Every cited source verified against the real MCP transcript",
            "score": _NA,
            "verdict": "TELEMETRY_UNAVAILABLE",
            "audit": audit,
            "cited_count": len(cited),
            "verified_count": 0,
            "detail": "Telemetry not captured; no transcript to verify cited sources against.",
        }

    consulted = set(telemetry.consulted_source_ids)
    verified = [s for s in cited if s in consulted]
    unverified = [s for s in cited if s not in consulted]
    verdict = "CLAIM_OK" if not unverified else "CLAIM_UNVERIFIED"

    # Vacuously OK when nothing is cited (the clean-capture case): nothing claimed, nothing to
    # flag. Otherwise the fraction of citations that the transcript actually backs.
    if not cited:
        sub_score: float = 1.0
    else:
        sub_score = len(verified) / len(cited)

    audit = {
        "grounded_source_ids": verified,   # only these are shown grounded (D-06)
        "claim_unverified": unverified,    # lights CLAIM_UNVERIFIED, never hard-fails
        "verdict": verdict,
    }
    return {
        "key": "source_auditor",
        "name": "Source Auditor",
        "dimension": "Every cited source verified against the real MCP transcript",
        "score": round(sub_score, 4),
        "verdict": verdict,
        "audit": audit,
        "cited_count": len(cited),
        "verified_count": len(verified),
    }


def _grounding_inspector(telemetry: RunTelemetry) -> dict:
    """Real brain-query depth (D-07). Sub-score = min(1, brain_query_count / TARGET).

    ``captured=False`` → score ``"n/a"`` (an HONEST "transcript unavailable", NOT 0 — Pitfall 2),
    DISTINCT from a captured dead engine (``captured=True, count=0`` → score 0.0, "0 brain
    queries this run"). Flags thin grounding below TARGET.
    """

    if not telemetry.captured:
        return {
            "key": "grounding_inspector",
            "name": "Grounding Inspector",
            "dimension": f"Real brain-query depth (target ≈ {GROUNDING_TARGET})",
            "score": _NA,
            "verdict": "TELEMETRY_UNAVAILABLE",
            "brain_query_count": telemetry.brain_query_count,
            "brain_total_entries": telemetry.brain_total_entries,
            "detail": f"Telemetry not captured for engine mode '{telemetry.engine_mode}'.",
        }

    count = telemetry.brain_query_count
    sub_score = min(1.0, count / GROUNDING_TARGET) if GROUNDING_TARGET else 0.0
    if count == 0:
        verdict = "DEAD_ENGINE"   # captured, but the engine made zero brain calls
    elif count < GROUNDING_TARGET:
        verdict = "THIN_GROUNDING"
    else:
        verdict = "WELL_GROUNDED"
    return {
        "key": "grounding_inspector",
        "name": "Grounding Inspector",
        "dimension": f"Real brain-query depth (target ≈ {GROUNDING_TARGET})",
        "score": round(sub_score, 4),
        "verdict": verdict,
        "brain_query_count": count,
        "brain_total_entries": telemetry.brain_total_entries,
        "consulted_source_count": len(telemetry.consulted_source_ids),
    }


def _distinctness_referee(direction: dict) -> dict:
    """Routes genuinely differ (D-07). Perceptual palette ΔE + title-token Jaccard, NOT exact-hex.

    Generalises to N routes (pairwise — count = len(routes), open-list, no overfit). The pair
    PASSES when its avg-nearest ΔE ≥ DISTINCTNESS_DE_THRESHOLD AND its title Jaccard ≤
    DISTINCTNESS_TITLE_JACCARD_MAX. The overall sub-score is the fraction of route-pairs that
    pass (a graded penalty, not all-or-nothing) — so one near pair among many is partial credit.
    """

    routes = direction.get("routes") or []
    pairs = 0
    passed = 0
    unmeasurable = 0
    worst_de = None
    worst_jaccard = None
    for i in range(len(routes)):
        for j in range(i + 1, len(routes)):
            pairs += 1
            de = _avg_nearest_de(routes[i].get("palette") or [], routes[j].get("palette") or [])
            jac = _jaccard(_title_tokens(routes[i].get("title", "")), _title_tokens(routes[j].get("title", "")))
            if de is None:
                unmeasurable += 1
                if worst_jaccard is None or jac > worst_jaccard:
                    worst_jaccard = jac
                continue
            palette_ok = de >= DISTINCTNESS_DE_THRESHOLD
            title_ok = jac <= DISTINCTNESS_TITLE_JACCARD_MAX
            if palette_ok and title_ok:
                passed += 1
            if worst_de is None or de < worst_de:
                worst_de = de
            if worst_jaccard is None or jac > worst_jaccard:
                worst_jaccard = jac

    if pairs == 0:
        sub_score: Any = _NA
        verdict = "NOT_APPLICABLE"
        detail = "Only one route available — route distinctness is not applicable."
    elif unmeasurable:
        sub_score = _NA
        verdict = "UNMEASURABLE"
        detail = "At least one route pair had an empty or invalid palette; distinctness was not scored."
    else:
        sub_score = passed / pairs
        verdict = "DISTINCT" if sub_score >= 0.99 else "ROUTES_TOO_NEAR"
        detail = ""
    return {
        "key": "distinctness_referee",
        "name": "Distinctness Referee",
        "dimension": "Routes genuinely differ — perceptual palette ΔE + title overlap (not exact-hex)",
        "score": round(sub_score, 4) if isinstance(sub_score, (int, float)) else sub_score,
        "verdict": verdict,
        "route_pairs": pairs,
        "pairs_passed": passed,
        "pairs_unmeasurable": unmeasurable,
        "min_palette_de": round(worst_de, 2) if worst_de is not None else None,
        "max_title_jaccard": round(worst_jaccard, 4) if worst_jaccard is not None else None,
        "detail": detail,
    }


def _avg_nearest_de(palette_a: list, palette_b: list) -> float | None:
    """Average, over palette A's colours, of the ΔE to the NEAREST colour in palette B.

    Low average ⇒ every A colour has a near twin in B ⇒ the palettes are perceptually near.
    Returns ``None`` when either palette is empty or invalid; unmeasurable is n/a, not a pass.
    """

    hexes_a = [c.get("hex") for c in palette_a if isinstance(c, dict) and c.get("hex")]
    hexes_b = [c.get("hex") for c in palette_b if isinstance(c, dict) and c.get("hex")]
    if not hexes_a or not hexes_b:
        return None
    minima = []
    try:
        for ha in hexes_a:
            minima.append(min(_de(ha, hb) for hb in hexes_b))
    except (ValueError, IndexError):
        return None
    return sum(minima) / len(minima) if minima else None


def _output_manifest(direction: dict) -> dict:
    """Every required region filled at honest cardinality (D-07), no padded slots.

    Sub-score = fraction of required regions satisfied. The font-lab check is per-route averaged
    (a route with 2 of 3 tiers is partial credit), so an under-filled route drags the manifest
    DOWN rather than passing on a padded slot.
    """

    routes = direction.get("routes") or []
    font_groups = direction.get("font_options") or []

    checks: list[float] = []
    missing: list[str] = []

    def _check(name: str, ok: bool) -> None:
        checks.append(1.0 if ok else 0.0)
        if not ok:
            missing.append(name)

    _check("routes>=2", len(routes) >= _MIN_ROUTES)
    _check("conversation>=1", len(direction.get("conversation") or []) >= _MIN_CONVERSATION)
    _check("copy_blocks>=1", len(direction.get("copy_blocks") or []) >= _MIN_COPY_BLOCKS)
    _check("next_steps>=1", len(direction.get("next_steps") or []) >= _MIN_NEXT_STEPS)
    _check("route_comparison>=1", len(direction.get("route_comparison") or []) >= _MIN_ROUTE_COMPARISON)

    # font_options per route ≥3 — averaged across the groups (a partial group is partial credit).
    if font_groups:
        per_group = [
            1.0 if len(g.get("options") or []) >= _MIN_FONT_OPTIONS_PER_ROUTE else
            len(g.get("options") or []) / _MIN_FONT_OPTIONS_PER_ROUTE
            for g in font_groups
        ]
        font_fraction = sum(per_group) / len(per_group)
        checks.append(font_fraction)
        if font_fraction < 1.0:
            missing.append("font_options/route>=3")
    else:
        checks.append(0.0)
        missing.append("font_options")

    sub_score = sum(checks) / len(checks) if checks else 0.0
    verdict = "COMPLETE" if sub_score >= 0.999 else "INCOMPLETE"
    return {
        "key": "output_manifest",
        "name": "Output Manifest",
        "dimension": "Every required region filled at honest cardinality, no padded slots",
        "score": round(sub_score, 4),
        "verdict": verdict,
        "missing_regions": missing,
        "filled_fraction": round(sub_score, 4),
    }


def _type_selection_referee(direction: dict) -> dict:
    """Font Lab range check: local font proof is allowed, local font bias is flagged.

    This inspector is intentionally objective. It does NOT decide whether a typeface is
    beautiful. It checks that London's Font Lab gives each route enough sourceable range
    (safe-local + open/public + premium/reference), that local assets do not dominate the
    whole set, that names/families are not the same convenience choice repeated everywhere,
    and that options explain why the route needs that type direction.
    """

    font_groups = [group for group in direction.get("font_options") or [] if isinstance(group, dict)]
    total_options = 0
    local_like = 0
    non_local = 0
    rationale_ready = 0
    generic_default_hits = 0
    actual_loaded_unverified = 0
    route_scores: list[float] = []
    family_signals: set[str] = set()
    missing: list[str] = []

    for index, group in enumerate(font_groups, start=1):
        options = [option for option in group.get("options") or [] if isinstance(option, dict)]
        route_label = _text(group.get("route_title") or group.get("route_id") or f"route {index}")
        tiers = {_text(option.get("tier")) for option in options}
        tier_score = len(tiers & _FONT_TIERS) / len(_FONT_TIERS)
        route_non_local = 0
        route_rationale = 0

        for option in options:
            total_options += 1
            if _is_local_font_option(option):
                local_like += 1
            else:
                non_local += 1
                route_non_local += 1
            if _option_has_route_rationale(option):
                rationale_ready += 1
                route_rationale += 1
            if _option_has_generic_default_marker(option):
                generic_default_hits += 1
            if _preview(option).get("status") == "actual_loaded" and not _actual_loaded_has_proof(option):
                actual_loaded_unverified += 1
            family_signals.update(_font_family_signals(option))

        non_local_score = min(1.0, route_non_local / 2) if options else 0.0
        rationale_score = route_rationale / len(options) if options else 0.0
        route_score = (tier_score + non_local_score + rationale_score) / 3
        route_scores.append(route_score)

        if tier_score < 1.0:
            missing.append(f"{route_label}: missing one of safe_local/open_public/premium_inspiration")
        if route_non_local < 2:
            missing.append(f"{route_label}: fewer than two non-local/sourceable font lanes")
        if rationale_score < 0.75:
            missing.append(f"{route_label}: font rationale is too thin")

    route_range_score = sum(route_scores) / len(route_scores) if route_scores else 0.0
    local_ratio = local_like / total_options if total_options else 1.0
    local_balance_score = 1.0 if local_ratio <= 0.5 else max(0.0, 1.0 - ((local_ratio - 0.5) / 0.5))
    required_family_signals = max(4, min(12, len(font_groups) * 3))
    diversity_score = min(1.0, len(family_signals) / required_family_signals) if required_family_signals else 0.0
    generic_ratio = generic_default_hits / total_options if total_options else 1.0
    generic_score = 1.0 if generic_ratio <= 0.5 else max(0.0, 1.0 - ((generic_ratio - 0.5) / 0.5))

    if not font_groups:
        missing.append("font_options")
    if total_options and local_ratio > 0.5:
        missing.append("local font lanes dominate the Font Lab")
    if total_options and generic_ratio > 0.5:
        missing.append("generic/system default families dominate the Font Lab")
    if actual_loaded_unverified:
        missing.append("actual_loaded font preview lacks shelf/user-local proof metadata")
    if len(family_signals) < required_family_signals:
        missing.append("not enough distinct typeface signals across routes")

    sub_score = (route_range_score + local_balance_score + diversity_score + generic_score) / 4
    if sub_score >= 0.95:
        verdict = "TYPE_RANGE_HEALTHY"
    elif sub_score >= 0.75:
        verdict = "TYPE_RANGE_THIN"
    else:
        verdict = "LOCAL_FONT_BIAS"

    return {
        "key": "type_selection_referee",
        "name": "Type Selection Referee",
        "dimension": "Font Lab range — local fonts allowed, but not allowed to dominate taste",
        "score": round(sub_score, 4),
        "verdict": verdict,
        "route_groups": len(font_groups),
        "total_options": total_options,
        "local_like_options": local_like,
        "non_local_options": non_local,
        "local_like_ratio": round(local_ratio, 4) if total_options else 1.0,
        "unique_type_signals": len(family_signals),
        "generic_default_hits": generic_default_hits,
        "actual_loaded_unverified": actual_loaded_unverified,
        "missing_range": missing,
    }


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _preview(option: dict) -> dict:
    value = option.get("font_preview")
    return value if isinstance(value, dict) else {}


def _is_local_font_option(option: dict) -> bool:
    preview = _preview(option)
    return (
        _text(option.get("tier")) == "safe_local"
        or _text(preview.get("delivery")) == "local_asset"
        or _text(preview.get("status")) == "actual_loaded"
    )


def _option_has_route_rationale(option: dict) -> bool:
    chosen = _text(option.get("why_london_chose_it"))
    route_specific = _text(option.get("why_this_route_not_other_route"))
    return len(chosen) >= 24 and len(route_specific) >= 24


def _font_family_signals(option: dict) -> set[str]:
    direct_fields = (
        option.get("name"),
        option.get("headline_font"),
        option.get("body_font"),
        option.get("label_font"),
        _preview(option).get("rendered_family"),
        _preview(option).get("source_label"),
    )
    signals: set[str] = set()
    for field in direct_fields:
        for part in re.split(r"[,/+&]", _text(field)):
            normalized = _normalize_font_signal(part)
            if normalized:
                signals.add(normalized)
    fallback_signal = _primary_fallback_signal(option.get("fallback_stack"))
    if fallback_signal:
        signals.add(fallback_signal)
    return signals


def _normalize_font_signal(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.replace('"', "").replace("'", "").strip().lower())
    if not normalized or normalized in _GENERIC_FONT_FAMILIES:
        return ""
    if normalized.endswith(" fallback") or normalized.endswith(" stack"):
        return ""
    if len(normalized) < 3:
        return ""
    return normalized


def _option_has_generic_default_marker(option: dict) -> bool:
    direct_values = (
        option.get("name"),
        option.get("headline_font"),
        option.get("body_font"),
        option.get("label_font"),
        _preview(option).get("rendered_family"),
    )
    if any(_normalize_exact_family(value) in _GENERIC_FONT_FAMILIES for value in direct_values):
        return True
    fallback_stack = _text(option.get("fallback_stack"))
    return bool(fallback_stack and not _primary_fallback_signal(fallback_stack))


def _primary_fallback_signal(value: Any) -> str:
    for part in _font_stack_parts(value):
        normalized = _normalize_font_signal(part)
        if normalized:
            return normalized
    return ""


def _font_stack_parts(value: Any) -> list[str]:
    return [
        part
        for part in re.split(r"[,/+&]", _text(value))
        if part.strip()
    ]


def _normalize_exact_family(value: Any) -> str:
    return re.sub(r"\s+", " ", _text(value).replace('"', "").replace("'", "").strip().lower())


def _actual_loaded_has_proof(option: dict) -> bool:
    preview = _preview(option)
    asset_href = _text(preview.get("asset_href"))
    source_label = _text(preview.get("source_label"))
    license_note = _text(preview.get("license_note"))
    if not asset_href or not source_label or not license_note:
        return False
    if _text(preview.get("source_kind")) == "bundled_open":
        return bool(_text(preview.get("shelf_id")) and _text(preview.get("asset_sha256")))
    # User-local proof predates source_kind/hash metadata; source/license/asset are the proof.
    return True


# --- the weighted composite (D-08 — transparent, documented, re-normalised on n/a) ---------


def _composite(sub_scores: dict[str, Any], *, telemetry_available: bool) -> dict:
    """A transparent weighted roll-up of the 5 sub-scores → a 0–100 hero number.

    Documented weights live in ``COMPOSITE_WEIGHTS``. The HERO ``score`` is honest about the
    transcript:

    * ``telemetry_available=False`` (keyed/offline/fake) → the hero ``score`` is ``"n/a"`` —
      the ENGINE grade is unavailable, NOT a fabricated number (D-11 / Pitfall 2). The
      output-measurable sub-scores (distinctness, output_manifest) are still reported in
      ``sub_scores`` (they are real), but they are NOT rolled into a fake engine grade. This is
      visually DISTINCT from a captured dead engine, which scores a real near-dead LOW number.
    * ``telemetry_available=True`` → the full weighted roll-up; any ``"n/a"`` sub-score (none on
      a captured run, by construction) would be dropped and the remaining weights re-normalised.

    The block records ``telemetry_available`` so 5.1 branches "n/a / telemetry unavailable" vs a
    real low number without re-deriving it.
    """

    if not telemetry_available:
        # Honest: no transcript ⇒ no engine grade. The output-measurable sub-scores remain in
        # `sub_scores` for the detail layer, but the hero number is n/a (never fabricated).
        return {
            "score": _NA,
            "sub_scores": sub_scores,             # grounding/source_auditor are transcript-blind here
            "weights": dict(COMPOSITE_WEIGHTS),
            "telemetry_available": False,
            "method": (
                "engine grade UNAVAILABLE — telemetry not captured for this engine mode; "
                "the output-measurable sub-scores are reported but NOT rolled into a fabricated hero"
            ),
        }

    usable = {k: v for k, v in sub_scores.items() if isinstance(v, (int, float))}
    weight_sum = sum(COMPOSITE_WEIGHTS[k] for k in usable)
    if usable and weight_sum > 0:
        weighted = sum(COMPOSITE_WEIGHTS[k] * usable[k] for k in usable) / weight_sum
        score: Any = round(weighted * 100, 1)
    else:
        score = _NA

    return {
        "score": score,
        "sub_scores": sub_scores,                 # each in [0,1] or "n/a"
        "weights": dict(COMPOSITE_WEIGHTS),       # documented, inline-tunable
        "telemetry_available": True,
        "method": (
            "weighted roll-up of 5 objective sub-scores "
            "(grounding .30 + source_auditor .25 + distinctness .18 + output_manifest .15 "
            "+ type_selection .12), "
            "n/a sub-scores dropped and remaining weights re-normalised"
        ),
    }


# --- the public entry: one input, one output ----------------------------------------------


def grade(direction: dict, telemetry: RunTelemetry) -> dict:
    """Audit London's claim (``direction``) against the objective transcript (``telemetry``).

    Returns the scrubbed grader block: ``composite`` (object: score + sub-scores + weights),
    ``inspectors`` (the named verdicts), ``audit`` (claim integrity), ``telemetry`` (the
    public-safe receipts view), and the two-layer ``headline``/``detail`` copy. Defensive — a
    missing/empty region is measured-as-incomplete, never a crash (T-05-13). Every value is
    transcript-real or output-measurable; NO fake gauges.

    NOTE: this is the LOGIC + DATA contract only. The grader receipts pass through the single
    ``scrub_pack`` chokepoint in session.py before any write; this module adds NO sanitizer.
    """

    direction = direction if isinstance(direction, dict) else {}

    # 1) The objective inspectors.
    source_auditor = _source_auditor(direction, telemetry)
    grounding = _grounding_inspector(telemetry)
    distinctness = _distinctness_referee(direction)
    manifest = _output_manifest(direction)
    type_selection = _type_selection_referee(direction)

    inspectors = [source_auditor, grounding, distinctness, manifest, type_selection]

    # 2) The composite (n/a-aware re-normalisation; never a fabricated low score).
    sub_scores: dict[str, Any] = {
        "grounding": grounding["score"],
        "source_auditor": source_auditor["score"],
        "distinctness": distinctness["score"],
        "output_manifest": manifest["score"],
        "type_selection": type_selection["score"],
    }
    composite = _composite(sub_scores, telemetry_available=telemetry.captured)

    # 3) The claim-integrity audit (lifted from the Source Auditor — the single source of truth).
    audit = source_auditor["audit"]

    # 4) The public-safe telemetry receipts view (query strings + source-… IDs + counts ONLY;
    #    NEVER raw finding bodies — the tap dropped those at the boundary in Plan 02). This is
    #    the block scrub_pack walks (grader.telemetry.brain_queries[].query).
    telemetry_view = {
        "engine_mode": telemetry.engine_mode,
        "captured": telemetry.captured,
        "brain_query_count": telemetry.brain_query_count,
        "brain_total_entries": telemetry.brain_total_entries,
        "consulted_source_ids": list(telemetry.consulted_source_ids),
        "duration_ms": telemetry.duration_ms,
        "brain_queries": [
            {
                "query": trace.query,
                "tool_use_id": trace.tool_use_id,
                "returned_source_ids": list(trace.returned_source_ids),
                "result_count": trace.result_count,
            }
            for trace in telemetry.brain_queries
        ],
    }

    # 5) The two-layer copy (D-09) — a DATA shape, not CSS, not a model rewrite. The HEADLINE
    #    layer is the humanized/understandable top-line; the DETAIL layer is the raw audit a
    #    developer expands. Both are authored data printed verbatim by 5.1 (NO 2nd render model).
    headline = _headline_copy(composite, inspectors)
    detail = _detail_copy(composite, inspectors, telemetry_view)

    return {
        "composite": composite,
        "inspectors": inspectors,
        "audit": audit,
        "telemetry": telemetry_view,
        "headline": headline,
        "detail": detail,
    }


def _headline_copy(composite: dict, inspectors: list[dict]) -> dict:
    """The humanized HEADLINE layer (D-09): the hero number + one understandable line each.

    Fidelity-biased, understandable copy — the marketing-grade top-line a non-developer reads
    at a glance. It is authored DATA (the renderer prints it verbatim; no live model rewrite).
    """

    score = composite["score"]
    if score == _NA:
        summary = "Telemetry not captured for this engine mode — the engine grade is unavailable."
    elif isinstance(score, (int, float)) and score >= 90:
        summary = "A strong, well-grounded run: London consulted the brain deeply and the routes hold up."
    elif isinstance(score, (int, float)) and score >= 60:
        summary = "A workable run with soft spots — see which checks came in light below."
    else:
        summary = "A weak run: the engine barely ran or the routes/claims did not hold up."

    return {
        "score": score,
        "label": "COMPOSITE",
        "sub_label": "weighted from 5 objective checks",
        "summary": summary,
        "inspectors": [
            {
                "name": ins["name"],
                "verdict": ins["verdict"],
                "line": _inspector_headline_line(ins),
            }
            for ins in inspectors
        ],
    }


def _inspector_headline_line(ins: dict) -> str:
    """One understandable line per inspector (the humanized verdict)."""

    key = ins.get("key")
    if key == "source_auditor":
        if ins["verdict"] == "TELEMETRY_UNAVAILABLE":
            return "No transcript for this engine mode — cited-source verification unavailable."
        if ins["verdict"] == "CLAIM_OK":
            return "Every cited source checks out against the transcript."
        return f"{len(ins['audit']['claim_unverified'])} cited source(s) could NOT be verified — flagged."
    if key == "grounding_inspector":
        if ins["score"] == _NA:
            return "No transcript for this engine mode — grounding unavailable."
        count = ins["brain_query_count"]
        if count == 0:
            return "0 brain queries this run — the engine did not consult the brain."
        return f"{count} brain queries this run."
    if key == "distinctness_referee":
        if ins["verdict"] == "DISTINCT":
            return "The routes are genuinely different — not one idea in two outfits."
        if ins["verdict"] == "NOT_APPLICABLE":
            return "Only one route — distinctness is not applicable."
        if ins["verdict"] == "UNMEASURABLE":
            return "Route distinctness is unmeasurable because a palette is empty or invalid."
        return "Two routes read as the same idea (near palette / overlapping titles)."
    if key == "output_manifest":
        if ins["verdict"] == "COMPLETE":
            return "Every required region is filled at honest cardinality."
        return f"Incomplete regions: {', '.join(ins['missing_regions'])}."
    if key == "type_selection_referee":
        if ins["verdict"] == "TYPE_RANGE_HEALTHY":
            return "Font choices show enough range; local assets are proof, not the whole taste pool."
        if ins["verdict"] == "TYPE_RANGE_THIN":
            return "Font choices have some range, but London should widen the type shelf before launch."
        return "Local or generic fonts dominate the Font Lab — widen the sourceable type range."
    return ins.get("verdict", "")


def _detail_copy(composite: dict, inspectors: list[dict], telemetry_view: dict) -> dict:
    """The collapsible DETAIL layer (D-09): the raw, developer-grade audit.

    The query trace + the consulted source IDs + the sub-score math — the closer-to-real-output
    fields 5.1 collapses by default behind "Show the raw audit". A DATA shape, distinct from the
    headline layer. Carries ONLY public-safe receipts (query strings + source-… IDs + counts).
    """

    return {
        "composite_math": {
            "score": composite["score"],
            "sub_scores": composite["sub_scores"],
            "weights": composite["weights"],
            "method": composite["method"],
        },
        "inspectors": [
            {k: v for k, v in ins.items() if k != "audit"} for ins in inspectors
        ],
        "brain_queries": telemetry_view["brain_queries"],
        "consulted_source_ids": telemetry_view["consulted_source_ids"],
        "engine_mode": telemetry_view["engine_mode"],
        "brain_total_entries": telemetry_view["brain_total_entries"],
    }
