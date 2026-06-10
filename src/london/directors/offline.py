"""Deterministic, explicit --offline London director."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping as AbcMapping, Sequence as AbcSequence
from typing import Any

from london.assets import fallback_asset, slugify
from london.direction import (
    ConversationRead,
    CopyBlock,
    DirectionRequest,
    DirectionResult,
    FontOption,
    FontRouteGroup,
    NextStep,
    PaletteColor,
    RouteComparison,
    RouteResult,
    RouteSection,
)
from london.directors.offline_data import (
    CreativeLane,
    CategoryProfile,
    OFFLINE_ORIGIN_MARKER,
    PROFILES,
    ROUTE_SYNTHESIS_PROVIDER,
    RouteSeed,
    SessionLane,
    _PALETTE_BANK,
    _RITUAL_TERMS,
    _SURFACE_TERMS,
    _TONE_TERMS,
)
from london.telemetry import RunTelemetry, _honest_empty_telemetry
from london.text import clean_brief_text, display_text

def _brief_tokens(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-z][a-z0-9+-]*", text.lower()))


def _extract_terms(tokens: set[str], mapping: AbcMapping[str, str], *, defaults: AbcSequence[str]) -> tuple[str, ...]:
    values = [label for token, label in mapping.items() if token in tokens]
    values.extend(defaults)
    return tuple(dict.fromkeys(values))[:5]


def _extract_product_noun(title: str, normalized_text: str) -> str:
    candidate = title.lower().strip("#: \n\t")
    candidate = re.sub(r"^(design|create|build|make|concept|brief)\s+(a|an|the)?\s*", "", candidate)
    candidate = re.sub(r"\s+for\s+.+$", "", candidate).strip()
    if len(candidate.split()) > 5:
        app_match = re.search(r"([a-z ]+\b(?:app|system|product|compact|service|tool|platform|workspace|site))\b", candidate)
        if app_match:
            candidate = app_match.group(1).strip()
    if candidate and candidate != "untitled london brief":
        return candidate[:64]
    match = re.search(r"(?:design|create|build)\s+(?:a|an|the)?\s*([^.\n]+?)(?:\s+for\s+|\.|$)", normalized_text)
    return (match.group(1).strip() if match else "public product")[:64]


def _extract_audience(normalized_text: str, product_noun: str) -> str:
    match = re.search(r"\bfor\s+([^.\n,]+?)(?:\s+who\b|\s+that\b|\s+which\b|\.|,|$)", normalized_text)
    if match:
        return match.group(1).strip()
    return f"people who need {product_noun} to feel specific, useful, and designed from the current brief"


def _extract_jobs(text: str, product_noun: str, audience: str) -> tuple[str, ...]:
    candidates: list[str] = []
    for sentence in re.split(r"[\n.;]+", text):
        cleaned = _clean_phrase(sentence)
        lowered = cleaned.lower()
        if not cleaned or cleaned.startswith("#"):
            continue
        if any(marker in lowered for marker in ("need", "want", "should", "include", "support", "combine", "decide", "prove", "create", "build", "design")):
            candidates.append(cleaned)
    candidates.extend(
        [
            f"Help {audience} make a clear first decision",
            f"Show why {product_noun} deserves a fresh public surface",
            "Expose the key state, ritual, or output before decoration",
        ]
    )
    return tuple(dict.fromkeys(candidates))[:5]


def _extract_tensions(text: str, product_noun: str) -> tuple[str, ...]:
    avoid = _extract_avoid(text)
    if avoid:
        return tuple(f"Current brief wants specificity without {item.lower()}" for item in avoid[:3])
    return (
        f"{_title_case(product_noun)} needs public polish without borrowed project logic.",
        "The design has to feel new while staying explainable enough to hand off.",
    )


def _extract_avoid(text: str) -> tuple[str, ...]:
    avoid: list[str] = []
    for pattern in (r"\bwithout\s+([^.\n]+)", r"\bavoid\s+([^.\n]+)", r"\bnot\s+([^.\n]+)"):
        avoid.extend(_clean_phrase(match) for match in re.findall(pattern, text, flags=re.I))
    avoid = [item for item in avoid if item]
    avoid.extend(["borrowed project names", "generic modern clean"])
    return tuple(dict.fromkeys(avoid))[:5]


def _output_moments(product_noun: str, jobs: AbcSequence[str], rituals: AbcSequence[str], surfaces: AbcSequence[str]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            (
                f"{product_noun} first decision",
                f"{surfaces[0]} proof",
                f"{rituals[0]} loop",
                _clean_phrase(jobs[0])[:56],
                "handoff receipt",
            )
        )
    )


def _fresh_palette(digest: str, product_noun: str, rituals: AbcSequence[str], surfaces: AbcSequence[str]) -> tuple[dict[str, str], ...]:
    offset = int(digest[:2], 16) % len(_PALETTE_BANK)
    colors = _PALETTE_BANK[offset]
    noun = _title_case(product_noun.split()[0] if product_noun.split() else "Lane")
    ritual = _title_case(rituals[0].split()[0])
    surface = _title_case(surfaces[0].split()[0])
    names = (
        (f"{noun} Ink", "ink"),
        (f"{noun} Paper", "paper"),
        (f"{ritual} Signal", "signal"),
        (f"{surface} Alert", "accent"),
        ("Receipt Mark", "proof"),
    )
    return tuple({"role": role, "name": name, "hex": hex_value} for (name, role), hex_value in zip(names, colors, strict=True))


def _fresh_route_seeds(
    product_noun: str,
    audience: str,
    jobs: AbcSequence[str],
    rituals: AbcSequence[str],
    surfaces: AbcSequence[str],
    tone: AbcSequence[str],
    avoid: AbcSequence[str],
    palette: AbcSequence[AbcMapping[str, str]],
    tokens: set[str],
) -> tuple[RouteSeed, ...]:
    title_one, title_two = _fresh_route_titles(product_noun, rituals, surfaces, tokens)
    primary_job = jobs[0]
    second_job = jobs[1]
    primary_surface = surfaces[0]
    second_surface = surfaces[1] if len(surfaces) > 1 else "decision panel"
    primary_ritual = rituals[0]
    tone_line = ", ".join(tone[:3])
    avoid_line = "; ".join(avoid[:2])
    color_line = ", ".join(color["name"] for color in palette[:3])

    return (
        RouteSeed(
            title=title_one,
            headline=f"Make {_title_case(product_noun)} answer the first real decision.",
            subhead=f"A fresh-lane route for {audience}: {primary_job}.",
            tags=(product_noun, primary_surface, primary_ritual),
            lore=f"This route starts from the current brief and turns {primary_surface} into a visible point of view.",
            mood=f"{tone_line}, with enough structure to avoid {avoid_line}.",
            type_note=f"Use assertive headline type for {title_one}, with compact labels for {primary_surface} states and receipts.",
            rationale=f"London would make {primary_job.lower()} visible before selling atmosphere.",
            steal=(
                f"Steal the clarity of {primary_surface} state changes.",
                f"Make {primary_ritual} feel like a repeatable ritual, not decoration.",
            ),
            do_not_copy=(
                "Do not import another project's route names or evidence.",
                f"Do not hide {_title_case(product_noun)} under generic hero copy.",
            ),
            sections=(
                (f"{_title_case(primary_surface)} Opening", f"Lead with the exact decision {audience} has to make: {primary_job}."),
                (f"{_title_case(primary_ritual)} Proof", "Show the repeatable moment, the state change, and the receipt that makes it believable."),
                ("Handoff Moment", f"Close with palette, type, and build notes using {color_line} as current-brief states."),
            ),
        ),
        RouteSeed(
            title=title_two,
            headline=f"Turn {_title_case(product_noun)} into a route people can compare.",
            subhead=f"A second fresh-lane option built around {second_job}.",
            tags=(product_noun, second_surface, "comparison route"),
            lore="This route makes the alternate path explicit so the user can choose, not inherit London leftovers.",
            mood=f"More {tone[-1]} and system-led, but still rooted in the same current brief.",
            type_note=f"Use calmer utility type for {title_two}; reserve expressive type for route labels and user-facing moments.",
            rationale="London would separate the useful system from the more expressive route so the choice has teeth.",
            steal=(
                f"Steal the rhythm of {second_surface} as a product proof.",
                "Make constraints visible enough for a builder to keep the idea intact.",
            ),
            do_not_copy=(
                "Do not make this route a renamed version of the first.",
                "Do not treat generalized brain findings as project identity.",
            ),
            sections=(
                (f"{_title_case(second_surface)} System", f"Show the alternate structure for {second_job}."),
                ("Constraint Legend", f"Name what the route must preserve and what it refuses: {avoid_line}."),
                ("Prototype Switch", "Make the route visible in nav, tabs, prototype panels, and handoff copy."),
            ),
        ),
    )


def _fresh_route_titles(product_noun: str, rituals: AbcSequence[str], surfaces: AbcSequence[str], tokens: set[str]) -> tuple[str, str]:
    # ENG-07 / Pitfall 2: this literal keyword->name table is the memorization
    # disease. It is the OfflineDirector parity behavior and the thing
    # BANNED_TEMPLATE_NAMES (A6) guards against on the default path. It must NEVER
    # be importable into a prompt or the default/model path.
    if {"weather", "pet"} & tokens and ("weather" in tokens or "forecast" in tokens):
        return "Safe Walk Window", "Care Forecast Cards"
    if {"horoscope", "astrology", "zodiac", "chart"} & tokens:
        return "Daily Chart Briefing", "Friend Reading Cards"
    if {"fragrance", "scent", "perfume"} & tokens:
        return "Refill Scent Ritual", "Scent Note Cabinet"
    if {"lunch", "lunchbox", "snack"} & tokens:
        return "Kid Choice Kit", "Lunch Reveal Guide"
    if {"hr", "compliance", "audit", "policy"} & tokens:
        return "Proof Trail Desk", "Policy Signal Room"
    lead = _title_case(surfaces[0].replace("view", "").strip() or product_noun)
    ritual = _title_case(rituals[0].replace("check", "").strip() or "Decision")
    noun = _title_case(product_noun.split()[0] if product_noun.split() else "Product")
    return f"{lead} Decision System", f"{ritual} {noun} Studio"


def _clean_phrase(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value.strip().strip("#:- "))
    return cleaned[:180]


def _title_case(value: str) -> str:
    return " ".join(part.capitalize() for part in value.replace("-", " ").split())


def _synthesize_session_lane(brief: AbcMapping[str, Any]) -> SessionLane:
    text = str(brief["text"])
    title = str(brief["title"])
    normalized = text.lower()
    tokens = _brief_tokens(text)
    token_set = set(tokens)
    product_noun = _extract_product_noun(title, normalized)
    audience = _extract_audience(normalized, product_noun)
    jobs = _extract_jobs(text, product_noun, audience)
    rituals = _extract_terms(token_set, _RITUAL_TERMS, defaults=("intake", "daily check", "share or review"))
    surfaces = _extract_terms(token_set, _SURFACE_TERMS, defaults=("first screen", "route panel", "handoff module"))
    tensions = _extract_tensions(text, product_noun)
    tone = _extract_terms(token_set, _TONE_TERMS, defaults=("specific", "useful", "opinionated"))
    avoid = _extract_avoid(text)
    output_moments = _output_moments(product_noun, jobs, rituals, surfaces)
    slug = f"fresh-{brief['digest']}"
    palette = _fresh_palette(brief["digest"], product_noun, rituals, surfaces)
    route_seeds = _fresh_route_seeds(product_noun, audience, jobs, rituals, surfaces, tone, avoid, palette, token_set)
    route_titles = " and ".join(seed.title for seed in route_seeds)
    primary_job = jobs[0]
    primary_ritual = rituals[0]
    primary_surface = surfaces[0]
    avoid_line = "; ".join(avoid[:2]) if avoid else "borrowed project logic or generic modern-clean filler"
    color_roles = ", ".join(color["name"] for color in palette[:4])

    return SessionLane(
        slug=slug,
        label=f"{_title_case(product_noun)} Fresh Lane",
        origin="current_brief",
        product_noun=product_noun,
        audience=audience,
        jobs=jobs,
        rituals=rituals,
        surfaces=surfaces,
        tensions=tensions,
        tone=tone,
        avoid=avoid,
        output_moments=output_moments,
        aesthetic_void=(
            f"{_title_case(product_noun)} will get flattened if it behaves like a reusable project template. "
            f"The missing piece is a current-brief system for {primary_job.lower()}."
        ),
        category_assumption=(
            f"{_title_case(product_noun)} is usually treated as a familiar category surface. "
            f"This brief needs a fresh lane for {audience}, not a borrowed route from another project."
        ),
        london_reframe=(
            f"Make {_title_case(product_noun)} prove this exact brief: {primary_job}, "
            f"{jobs[1]}, and a repeatable {primary_ritual} ritual before decoration arrives."
        ),
        vessel_expression=(
            f"The public surface should behave like a {primary_surface} system with visible states, "
            f"route-specific proof, and handoff moments tied to the current brief."
        ),
        recurring_loop=" -> ".join(dict.fromkeys((primary_ritual, surfaces[0], output_moments[0], "handoff receipt"))),
        unboxing=(
            f"The first moment names the fresh lane, shows the user's next decision, and makes {route_titles} "
            "feel like separate choices rather than recycled profiles."
        ),
        anti_position=f"Not a recycled {_title_case(product_noun)} lane. Not {avoid_line}. Not any prior profile route unless the user explicitly asks.",
        voice=(
            f"London's read: be precise about {product_noun}, show why {audience} should care, "
            "and keep the evidence honest about what came from the current brief."
        ),
        aesthetic=", ".join(dict.fromkeys((product_noun, *tone[:2], *surfaces[:2], "fresh lane proof"))),
        type_system=(
            f"Use a route-specific headline stack for {route_titles}; keep labels and receipts crisp enough "
            f"to make {primary_surface} decisions legible."
        ),
        color_system=f"Use {color_roles} as product states tied to this brief, not as decoration.",
        palette=palette,
        source_terms=" ".join(dict.fromkeys((product_noun, *surfaces, *rituals, "brand system typography interface proof"))),
        image_direction=(
            f"Generate visuals from current-lane primitives: {', '.join(surfaces[:3])}, "
            f"{', '.join(rituals[:2])}, and the route thesis. Do not reuse another pack's project imagery."
        ),
        shot_list=tuple(f"{_title_case(moment)} proof" for moment in output_moments[:5]),
        generation_constraints=(
            "No previous London Pack concepts unless the user explicitly supplies them.",
            "No generic repeated system sketch as the only preview.",
            f"No borrowed route names; every route must answer {_title_case(product_noun)}.",
        ),
        motion_principles=(
            f"{_title_case(primary_surface)} state changes should expose the user's next decision.",
            f"{_title_case(primary_ritual)} moments should feel repeatable, not ornamental.",
            "Route tabs should keep every route available instead of hiding the second idea.",
        ),
        risks=(
            "The work fails if a previous project identity appears as evidence.",
            "The work fails if both routes share the same skeleton after only changing labels.",
            f"The work fails if {_title_case(product_noun)} becomes generic modern-clean filler.",
        ),
        route_seeds=route_seeds,
    )


def _classify_profile(text: str) -> CategoryProfile:
    normalized = text.lower()
    scored = [
        (sum(1 for keyword in profile.keywords if keyword in normalized), index, profile)
        for index, profile in enumerate(PROFILES)
    ]
    scored.sort(key=lambda item: (-item[0], item[1]))
    if scored[0][0] == 0:
        return next(profile for profile in PROFILES if profile.slug == "tactile-product")
    return scored[0][2]


def _routes_from_profile(profile: CreativeLane, brief: AbcMapping[str, Any], gates: AbcSequence[AbcMapping[str, Any]]) -> list[dict[str, Any]]:
    route_evidence = [] if isinstance(profile, SessionLane) else [
        str(finding.get("title"))
        for gate in gates[:3]
        for finding in gate.get("brain_findings", [])[:1]
        if isinstance(finding, AbcMapping) and finding.get("title")
    ]
    routes: list[dict[str, Any]] = []
    for index, seed in enumerate(profile.route_seeds, start=1):
        route_id = f"{slugify(profile.slug)}-{slugify(seed.title)}"
        routes.append(
            {
                "id": route_id,
                "title": seed.title,
                "headline": seed.headline,
                "subhead": seed.subhead,
                "palette": [dict(color) for color in profile.palette],
                "assets": [
                    fallback_asset(seed.title, seed.rationale, profile.palette, kind="system sketch"),
                ],
                "tags": list(seed.tags),
                "lore": seed.lore,
                "mood": seed.mood,
                "type": seed.type_note,
                "rationale": seed.rationale,
                "steal": list(seed.steal),
                "do_not_copy": list(seed.do_not_copy),
                "sections": [
                    {
                        "title": title,
                        "body": body,
                        "eyebrow": f"{brief['title']} / Route {index:02d}",
                    }
                    for title, body in seed.sections
                ],
                "source_inspiration": route_evidence[:3],
                "build_implications": [
                    "Render this route from current session-lane decisions, not another project pack.",
                    "Keep the first screen brief-specific enough to fail a borrowed skeleton test.",
                    "Attach brain and source receipts before public handoff.",
                ],
                "approval_state": "session-local-approved",
            }
        )
    return routes


def _components_for_profile(profile: CreativeLane) -> list[str]:
    if isinstance(profile, SessionLane):
        components = [surface for surface in profile.surfaces[:4] if surface]
        if len(components) < 4:
            components.extend(moment for moment in profile.output_moments if moment not in components)
        return components[:4] or ["brief proof", "route panel", "state system", "handoff receipt"]
    if profile.slug == "enterprise-compliance":
        return ["proof packet", "review queue", "audit trail", "exception state"]
    if profile.slug == "kids-lunchbox":
        return ["lid reveal", "choice map", "sticker state", "parent prep rail"]
    if profile.slug == "luxury-fragrance":
        return ["vessel macro", "note card", "refill module", "box compartment"]
    if profile.slug == "public-horoscope":
        return ["daily reading card", "chart weather", "compatibility card", "share ritual"]
    return ["object inspection", "manual panel", "packaging grid", "receipt footer"]


def _gate_summary(gate_id: str, profile: CreativeLane) -> str:
    return {
        "research": f"Name the {profile.label} void before selecting references.",
        "creative_direction": profile.london_reframe,
        "typography_color": profile.type_system,
        "image_direction": profile.image_direction,
        "layout_mockups": f"Prototype {profile.route_seeds[0].title} and {profile.route_seeds[1].title}.",
        "build_motion": f"Build static proof around {profile.route_seeds[0].sections[0][0]}.",
        "quality_review": f"Reject anything that collapses {profile.label} into generic modern-clean taste.",
    }[gate_id]


def _gate_rationale(gate_id: str, profile: CreativeLane, findings: AbcSequence[AbcMapping[str, Any]]) -> str:
    titles = [str(finding.get("title")) for finding in findings[:2] if finding.get("title")]
    suffix = f" Brain evidence: {', '.join(titles)}." if titles else " Brain evidence was queried and recorded."
    return f"{_gate_summary(gate_id, profile)}{suffix}"


# --- Stage-2 font/route banks (relocated verbatim from workbench.py) ---


def _font_presets(profile: str, route: AbcMapping[str, Any]) -> list[dict[str, str]]:
    route_mode = _route_font_mode(route)
    adjustments = _route_font_adjustments(profile, route_mode)
    presets = {
        "enterprise": [
            {
                "tier": "safe_local",
                "label": "Safe Local",
                "name": adjustments["safe_name"],
                "headline": adjustments["safe_headline"],
                "body": "Helvetica",
                "label_font": "Menlo",
                "stack": adjustments["safe_stack"],
                "best_use": adjustments["safe_best_use"],
                "why": adjustments["safe_why"],
                "route_reason": adjustments["safe_route_reason"],
                "wrong": "Wrong if the brand needs warmth before trust.",
                "import_hint": "",
            },
            {
                "tier": "open_public",
                "label": "Open Source / Public Web",
                "name": adjustments["open_name"],
                "headline": adjustments["open_headline"],
                "body": "Public Sans",
                "label_font": "IBM Plex Mono",
                "stack": adjustments["open_stack"],
                "best_use": adjustments["open_best_use"],
                "why": adjustments["open_why"],
                "route_reason": adjustments["open_route_reason"],
                "wrong": "Wrong if every surface becomes a government form.",
                "import_hint": "@import url('https://fonts.googleapis.com/css2?family=Public+Sans:wght@500;700;900&family=IBM+Plex+Mono:wght@500;700&display=swap');",
            },
            {
                "tier": "premium_inspiration",
                "label": "Premium / Inspiration",
                "name": adjustments["premium_name"],
                "headline": adjustments["premium_headline"],
                "body": "Soehne Buch",
                "label_font": "GT America Mono",
                "stack": adjustments["premium_stack"],
                "best_use": adjustments["premium_best_use"],
                "why": adjustments["premium_why"],
                "route_reason": adjustments["premium_route_reason"],
                "wrong": "Wrong if licensing or procurement friction slows the build.",
                "import_hint": "Reference only; license before use.",
            },
        ],
        "kids": [
            {
                "tier": "safe_local",
                "label": "Safe Local",
                "name": adjustments["safe_name"],
                "headline": adjustments["safe_headline"],
                "body": "Arial",
                "label_font": "Arial Rounded MT Bold",
                "stack": adjustments["safe_stack"],
                "best_use": adjustments["safe_best_use"],
                "why": adjustments["safe_why"],
                "route_reason": adjustments["safe_route_reason"],
                "wrong": "Wrong if it turns every label into classroom clip art.",
                "import_hint": "",
            },
            {
                "tier": "open_public",
                "label": "Open Source / Public Web",
                "name": adjustments["open_name"],
                "headline": adjustments["open_headline"],
                "body": "Atkinson Hyperlegible",
                "label_font": "Nunito Sans",
                "stack": adjustments["open_stack"],
                "best_use": adjustments["open_best_use"],
                "why": adjustments["open_why"],
                "route_reason": adjustments["open_route_reason"],
                "wrong": "Wrong if the rounded voice erases product utility.",
                "import_hint": "@import url('https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700&family=Nunito:wght@700;900&display=swap');",
            },
            {
                "tier": "premium_inspiration",
                "label": "Premium / Inspiration",
                "name": adjustments["premium_name"],
                "headline": adjustments["premium_headline"],
                "body": "Circular Book",
                "label_font": "Rebond Grotesque",
                "stack": adjustments["premium_stack"],
                "best_use": adjustments["premium_best_use"],
                "why": adjustments["premium_why"],
                "route_reason": adjustments["premium_route_reason"],
                "wrong": "Wrong if the premium polish makes the child moment feel secondary.",
                "import_hint": "Reference only; license before use.",
            },
        ],
        "fragrance": [
            {
                "tier": "safe_local",
                "label": "Safe Local",
                "name": adjustments["safe_name"],
                "headline": adjustments["safe_headline"],
                "body": "Helvetica",
                "label_font": "Courier New",
                "stack": adjustments["safe_stack"],
                "best_use": adjustments["safe_best_use"],
                "why": adjustments["safe_why"],
                "route_reason": adjustments["safe_route_reason"],
                "wrong": "Wrong if every moment becomes literary and the object disappears.",
                "import_hint": "",
            },
            {
                "tier": "open_public",
                "label": "Open Source / Public Web",
                "name": adjustments["open_name"],
                "headline": adjustments["open_headline"],
                "body": "Inter",
                "label_font": "IBM Plex Mono",
                "stack": adjustments["open_stack"],
                "best_use": adjustments["open_best_use"],
                "why": adjustments["open_why"],
                "route_reason": adjustments["open_route_reason"],
                "wrong": "Wrong if the contrast gets melodramatic or fake antique.",
                "import_hint": "@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@600;700&family=Inter:wght@400;600;800&display=swap');",
            },
            {
                "tier": "premium_inspiration",
                "label": "Premium / Inspiration",
                "name": adjustments["premium_name"],
                "headline": adjustments["premium_headline"],
                "body": "Neue Haas Grotesk",
                "label_font": "Akkurat Mono",
                "stack": adjustments["premium_stack"],
                "best_use": adjustments["premium_best_use"],
                "why": adjustments["premium_why"],
                "route_reason": adjustments["premium_route_reason"],
                "wrong": "Wrong if the route needs blunt utility or high-frequency commerce.",
                "import_hint": "Reference only; license before use.",
            },
        ],
        "tactile": [
            {
                "tier": "safe_local",
                "label": "Safe Local",
                "name": adjustments["safe_name"],
                "headline": adjustments["safe_headline"],
                "body": "Arial",
                "label_font": "Courier New",
                "stack": adjustments["safe_stack"],
                "best_use": adjustments["safe_best_use"],
                "why": adjustments["safe_why"],
                "route_reason": adjustments["safe_route_reason"],
                "wrong": "Wrong if the product needs elegance before energy.",
                "import_hint": "",
            },
            {
                "tier": "open_public",
                "label": "Open Source / Public Web",
                "name": adjustments["open_name"],
                "headline": adjustments["open_headline"],
                "body": "IBM Plex Sans",
                "label_font": "IBM Plex Mono",
                "stack": adjustments["open_stack"],
                "best_use": adjustments["open_best_use"],
                "why": adjustments["open_why"],
                "route_reason": adjustments["open_route_reason"],
                "wrong": "Wrong if the styling becomes sci-fi before product proof.",
                "import_hint": "@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@500;700&family=IBM+Plex+Sans:wght@400;600;800&family=Space+Grotesk:wght@700&display=swap');",
            },
            {
                "tier": "premium_inspiration",
                "label": "Premium / Inspiration",
                "name": adjustments["premium_name"],
                "headline": adjustments["premium_headline"],
                "body": "Suisse Int'l",
                "label_font": "Suisse Int'l Mono",
                "stack": adjustments["premium_stack"],
                "best_use": adjustments["premium_best_use"],
                "why": adjustments["premium_why"],
                "route_reason": adjustments["premium_route_reason"],
                "wrong": "Wrong if the wide display face overwhelms the object.",
                "import_hint": "Reference only; license before use.",
            },
        ],
    }
    return presets.get(profile, presets["tactile"])


def _route_font_mode(route: AbcMapping[str, Any]) -> str:
    # A5 TRAP (Pitfall 1): this phrase-matcher classifies routes by matching dead
    # campaign words against the route title/headline. Once the default path stops
    # using the memorized OfflineDirector titles, these matches fall through to
    # "manual" and every route gets identical default fonts. A5 must re-key font
    # choice on DirectionResult.font_options, NOT on this phrase match. It stays
    # verbatim here because the OfflineDirector titles ARE present on the offline
    # path, so offline parity holds.
    haystack = " ".join(
        [
            display_text(route.get("id")),
            display_text(route.get("title")),
            display_text(route.get("headline")),
            display_text(route.get("rationale")),
        ]
    ).lower()
    if any(term in haystack for term in ("audit", "atlas", "trail")):
        return "audit"
    if any(term in haystack for term in ("exception", "desk", "queue")):
        return "exception"
    if any(term in haystack for term in ("sticker", "ritual kit", "label", "choice kit", "kid choice")):
        return "sticker"
    if any(term in haystack for term in ("field guide", "guide", "manual", "map")):
        return "field_guide"
    if any(term in haystack for term in ("morning", "sign-in", "daily", "ephemeris", "weather", "chart briefing")):
        return "daily_ritual"
    if any(term in haystack for term in ("compatibility", "synastry", "share card", "friend", "reading cards", "forecast cards")):
        return "social_card"
    if any(term in haystack for term in ("collector", "collectible")):
        return "collector"
    if any(term in haystack for term in ("atelier", "quiet", "refill scent")):
        return "atelier"
    if any(term in haystack for term in ("night", "bottle", "ritual", "scent note")):
        return "night"
    return "manual"


_BORROWED_ROUTE_NAME_REPLACEMENTS = (
    "Sticker Ritual Kit",
    "Lunchbox Field Guide",
    "Quiet Atelier",
    "Night Bottle Ritual",
    "Morning Sign-In",
    "Compatibility Card Studio",
    "Audit Trail Atlas",
    "Calm Exception Desk",
    "Signal Object Manual",
    "Collector Utility",
)


def _fresh_lane_font_text(value: str, route_title: str) -> str:
    text = value
    for borrowed in _BORROWED_ROUTE_NAME_REPLACEMENTS:
        text = text.replace(borrowed, route_title)
    return text


def _route_font_adjustments(profile: str, mode: str) -> dict[str, str]:
    defaults = {
        "safe_name": "Manual Utility Stack",
        "safe_headline": "Arial Black",
        "safe_stack": "'Arial Black', Arial, sans-serif",
        "safe_best_use": "Bold local prototypes, labels, and inspection frames.",
        "safe_why": "It makes the object feel useful and loud enough to inspect.",
        "safe_route_reason": "This route needs blunt product labels before it needs polish.",
        "open_name": "Space Grotesk + IBM Plex Sans",
        "open_headline": "Space Grotesk",
        "open_stack": "'Space Grotesk', 'IBM Plex Sans', Arial, sans-serif",
        "open_best_use": "Retro-futurist product pages with real UI labels.",
        "open_why": "It gives the route a future-tool voice without purple gradient theater.",
        "open_route_reason": "This route needs a system voice that can carry interface and object captions.",
        "premium_name": "Druk + Suisse Int'l Direction",
        "premium_headline": "Druk Wide",
        "premium_stack": "'Druk Wide', 'Arial Black', Arial, sans-serif",
        "premium_best_use": "Collector utility launches with strong product theater.",
        "premium_why": "It lets the label system feel collectible without turning retro into wallpaper.",
        "premium_route_reason": "This route can afford a louder display face because the object is already the proof.",
    }
    by_profile_mode: dict[tuple[str, str], dict[str, str]] = {
        ("kids", "sticker"): {
            "safe_name": "Sticker Label Stack",
            "safe_headline": "Arial Rounded MT Bold",
            "safe_stack": "'Arial Rounded MT Bold', 'Trebuchet MS', Arial, sans-serif",
            "safe_best_use": "Kid-authored stickers, lunch labels, and parent-readable product states.",
            "safe_why": "Rounded letters make the sticker ritual feel owned by the child without losing legibility.",
            "safe_route_reason": "Sticker Ritual Kit needs labeling energy: names, choices, swaps, and rewards.",
            "open_name": "Nunito Stickers + Atkinson Body",
            "open_headline": "Nunito",
            "open_stack": "'Nunito', 'Atkinson Hyperlegible', Arial, sans-serif",
            "open_best_use": "Choice stickers, badge states, and approachable commerce copy.",
            "open_why": "It keeps the route playful but still useful for parents scanning lunch decisions.",
            "open_route_reason": "The sticker route needs friendly labels more than diagram authority.",
            "premium_name": "Circular + Rebond Label Direction",
            "premium_headline": "Circular",
            "premium_stack": "'Circular', 'Trebuchet MS', Arial, sans-serif",
            "premium_best_use": "A durable family product system where stickers become brand language.",
            "premium_why": "The pairing lets stickers feel collectible without licensed-character noise.",
            "premium_route_reason": "This route is about a kit of owned marks, so the premium inspiration should protect the label system.",
        },
        ("kids", "field_guide"): {
            "safe_name": "Field Guide Caption Stack",
            "safe_headline": "Trebuchet MS",
            "safe_stack": "'Trebuchet MS', Arial, sans-serif",
            "safe_best_use": "Instruction cards, lunch maps, parent notes, and daily reveal diagrams.",
            "safe_why": "It reads more like a helpful manual than a toy aisle.",
            "safe_route_reason": "Lunchbox Field Guide needs diagram/caption hierarchy before sticker personality.",
            "open_name": "Atkinson Guide + Nunito Marker",
            "open_headline": "Atkinson Hyperlegible",
            "open_stack": "'Atkinson Hyperlegible', 'Nunito', Arial, sans-serif",
            "open_best_use": "Maps, step cards, routine diagrams, and accessible kid/parent instructions.",
            "open_why": "It makes utility feel warm while keeping every instruction scannable.",
            "open_route_reason": "The field guide route is won by clarity: captions, arrows, notes, and sequence.",
            "premium_name": "Apercu + Rebond Diagram Direction",
            "premium_headline": "Apercu",
            "premium_stack": "'Apercu', 'Trebuchet MS', Arial, sans-serif",
            "premium_best_use": "A polished manual-like system for a family product line.",
            "premium_why": "It treats lunch as an everyday system, not a cartoon wrapper.",
            "premium_route_reason": "This route needs a premium manual voice that can hold diagrams and small notes.",
        },
        ("enterprise", "audit"): {
            "safe_name": "Audit Ledger Stack",
            "safe_headline": "Arial",
            "safe_stack": "Arial, Helvetica, sans-serif",
            "safe_best_use": "Evidence packets, audit trails, policy history, and compliance receipts.",
            "safe_why": "It keeps the route calm enough for proof metadata to do the authority work.",
            "safe_route_reason": "Audit Trail Atlas needs a ledger voice: stable, sortable, and receipt-first.",
            "open_name": "Public Sans Ledger + IBM Plex Mono",
            "open_headline": "Public Sans",
            "open_stack": "'Public Sans', Arial, sans-serif",
            "open_best_use": "Policy evidence, governance screens, and change-history tables.",
            "open_why": "The pair makes audit proof feel official without becoming punitive.",
            "open_route_reason": "The atlas route needs typography that can map records and make evidence feel inspected.",
            "premium_name": "Soehne Ledger + GT America Mono",
            "premium_headline": "Soehne",
            "premium_stack": "'Soehne', 'Helvetica Neue', Arial, sans-serif",
            "premium_best_use": "A mature enterprise proof system with strong audit receipts.",
            "premium_why": "It suggests institutional confidence without bank-blue theater.",
            "premium_route_reason": "Audit Trail Atlas can carry a sober premium grotesk because the route is about durable proof.",
        },
        ("enterprise", "exception"): {
            "safe_name": "Exception Desk Stack",
            "safe_headline": "Helvetica",
            "safe_stack": "Helvetica, Arial, sans-serif",
            "safe_best_use": "Review queues, risk triage, exception notes, and action states.",
            "safe_why": "It keeps the desk clear and lets status language carry urgency.",
            "safe_route_reason": "Calm Exception Desk needs a triage rhythm, not a ledger wall.",
            "open_name": "Inter Review + IBM Plex Mono",
            "open_headline": "Inter",
            "open_stack": "'Inter', Arial, sans-serif",
            "open_best_use": "Human review queues, side panels, exception messages, and decision logs.",
            "open_why": "It gives reviewers a humane SaaS surface without losing control.",
            "open_route_reason": "The desk route needs conversational status and fast scanning, so type should feel operational.",
            "premium_name": "Suisse Int'l Review + Akkurat Mono",
            "premium_headline": "Suisse Int'l",
            "premium_stack": "'Suisse Int\\'l', Helvetica, Arial, sans-serif",
            "premium_best_use": "A premium operations console where risk review feels calm and decisive.",
            "premium_why": "It reads as professional and human rather than legalistic.",
            "premium_route_reason": "Calm Exception Desk benefits from a warmer premium grotesk because people are making the calls.",
        },
        ("fragrance", "atelier"): {
            "safe_name": "Quiet Atelier Serif Stack",
            "safe_headline": "Georgia",
            "safe_stack": "Georgia, 'Times New Roman', serif",
            "safe_best_use": "Scent lore, material notes, quiet packaging copy, and refill ritual pages.",
            "safe_why": "It gives the vessel ritual restraint before premium type is licensed.",
            "safe_route_reason": "Quiet Atelier needs material calm and note-card intimacy.",
            "open_name": "Cormorant Atelier + Inter",
            "open_headline": "Cormorant Garamond",
            "open_stack": "'Cormorant Garamond', Georgia, serif",
            "open_best_use": "Luxury ritual pages with ingredient and material captions.",
            "open_why": "It separates scent lore from ingredient truth without copying perfume templates.",
            "open_route_reason": "The atelier route should feel like a studio note, not a nightclub poster.",
            "premium_name": "Canela Atelier + Neue Haas",
            "premium_headline": "Canela",
            "premium_stack": "'Canela', Georgia, serif",
            "premium_best_use": "Object-led fragrance work where the compact and refill ritual stay quiet.",
            "premium_why": "It feels expensive because it is specific, not smoky.",
            "premium_route_reason": "Quiet Atelier needs premium restraint that lets material texture lead.",
        },
        ("fragrance", "night"): {
            "safe_name": "Night Label Serif Stack",
            "safe_headline": "Times New Roman",
            "safe_stack": "'Times New Roman', Georgia, serif",
            "safe_best_use": "Batch cards, night ritual copy, compact labels, and darker product moments.",
            "safe_why": "It makes the route feel more coded and ceremonial than soft editorial.",
            "safe_route_reason": "Night Bottle Ritual needs label precision and after-dark contrast.",
            "open_name": "Fraunces Ritual + Inter",
            "open_headline": "Fraunces",
            "open_stack": "'Fraunces', Georgia, serif",
            "open_best_use": "Dramatic ritual headlines with clear commerce and ingredient copy beneath.",
            "open_why": "It gives the route curve and contrast without drifting into fake antique perfume.",
            "open_route_reason": "The night route can carry a sharper display serif because the compact is treated like a coded object.",
            "premium_name": "Noe Display + Neue Haas Ritual",
            "premium_headline": "Noe Display",
            "premium_stack": "'Noe Display', Georgia, serif",
            "premium_best_use": "A darker fragrance system with vessel-as-talisman energy.",
            "premium_why": "It turns ritual into structure rather than mist.",
            "premium_route_reason": "Night Bottle Ritual needs a more dramatic premium face than Quiet Atelier because the route is built around ceremony.",
        },
        ("horoscope", "daily_ritual"): {
            "safe_name": "Morning Ephemeris Stack",
            "safe_headline": "Georgia",
            "safe_stack": "Georgia, 'Times New Roman', serif",
            "safe_best_use": "Daily readings, transit notes, moon calendar moments, and calm first-open rituals.",
            "safe_why": "It gives the horoscope a literary voice before any custom font or live art direction exists.",
            "safe_route_reason": "Morning Sign-In needs daily reading intimacy and chart proof, not social-card loudness.",
            "open_name": "Newsreader Almanac + Inter",
            "open_headline": "Newsreader",
            "open_stack": "'Newsreader', Georgia, serif",
            "open_best_use": "Morning cards, reading modules, chart-weather notes, and onboarding explanations.",
            "open_why": "It feels editorial and trustworthy without slipping into mystical wellness fog.",
            "open_route_reason": "The daily route is won by a readable ritual card with small proof labels.",
            "premium_name": "Canela Daily + Söhne",
            "premium_headline": "Canela",
            "premium_stack": "'Canela', Georgia, serif",
            "premium_best_use": "A premium consumer ritual app where readings feel authored and specific.",
            "premium_why": "It gives the reading ceremony without pretending typography can supply belief.",
            "premium_route_reason": "Morning Sign-In can carry a warmer premium serif because the route is about private ritual.",
        },
        ("horoscope", "social_card"): {
            "safe_name": "Compatibility Card Stack",
            "safe_headline": "Trebuchet MS",
            "safe_stack": "'Trebuchet MS', Arial, sans-serif",
            "safe_best_use": "Share cards, friend prompts, compatibility receipts, and creator-friendly visual snippets.",
            "safe_why": "It keeps the social surface bright and readable without becoming a zodiac meme template.",
            "safe_route_reason": "Compatibility Card Studio needs card headlines, short snippets, and proof labels.",
            "open_name": "Space Grotesk Cards + Source Serif",
            "open_headline": "Space Grotesk",
            "open_stack": "'Space Grotesk', 'Source Serif 4', Arial, sans-serif",
            "open_best_use": "Exportable cards, social rails, compatibility moments, and app navigation.",
            "open_why": "It gives share artifacts a modern consumer-app voice while the serif keeps readings human.",
            "open_route_reason": "The social route needs graphic confidence and a second voice for intimate reading snippets.",
            "premium_name": "GT America Cards + Tiempos Text",
            "premium_headline": "GT America",
            "premium_stack": "'GT America', Arial, sans-serif",
            "premium_best_use": "A polished social astrology system with strong share-card hierarchy.",
            "premium_why": "It separates the app utility from the softer reading voice and avoids mystical novelty type.",
            "premium_route_reason": "Compatibility Card Studio can be more graphic because the route is built for sharing.",
        },
        ("tactile", "collector"): {
            "safe_name": "Collector Receipt Stack",
            "safe_headline": "Impact",
            "safe_stack": "Impact, 'Arial Black', Arial, sans-serif",
            "safe_best_use": "Collector labels, launch receipts, numbered drops, and object-status moments.",
            "safe_why": "It makes the utility feel collectible without needing a custom type license for the first pass.",
            "safe_route_reason": "Collector Utility needs ownership marks and drop logic, not just a manual voice.",
            "open_name": "Space Grotesk Collector + IBM Plex Mono",
            "open_headline": "Space Grotesk",
            "open_stack": "'Space Grotesk', 'IBM Plex Mono', Arial, sans-serif",
            "open_best_use": "Drop pages, specs, interface labels, and collectible proof modules.",
            "open_why": "It gives the route a future-object system while keeping receipts legible.",
            "open_route_reason": "The collector route needs a typographic loop between product theater and proof labels.",
            "premium_name": "Druk Condensed + Suisse Mono Collector",
            "premium_headline": "Druk Condensed",
            "premium_stack": "'Druk Condensed', Impact, sans-serif",
            "premium_best_use": "A collector launch system with loud labels and sober proof captions.",
            "premium_why": "It gives the object a limited-edition pulse without becoming pure hype.",
            "premium_route_reason": "Collector Utility can carry compressed display type because scarcity and labeling are the route logic.",
        },
    }
    return defaults | by_profile_mode.get((profile, mode), {})


def _profile_key(route: AbcMapping[str, Any], pack: AbcMapping[str, Any]) -> str:
    haystack = " ".join(
        [
            display_text(route.get("id")),
            display_text(route.get("title")),
            display_text(route.get("headline")),
            display_text(pack.get("title")),
            display_text(pack.get("category_assumption")),
        ]
    ).lower()
    if any(term in haystack for term in ("enterprise", "compliance", "audit", "policy", "hr")):
        return "enterprise"
    if any(term in haystack for term in ("kids", "lunch", "sticker", "school", "snack")):
        return "kids"
    if any(term in haystack for term in ("fragrance", "scent", "atelier", "bottle", "compact")):
        return "fragrance"
    if any(term in haystack for term in ("horoscope", "astrology", "zodiac", "birth chart", "compatibility", "moon")):
        return "horoscope"
    return "tactile"


def _offline_font_groups(pack: AbcMapping[str, Any]) -> list[dict[str, Any]]:
    """The relocated stage-2 ``build_font_options`` font-bank logic.

    Produces the same schema-valid ``fontRouteGroup``/``fontOption`` view-model
    ``enrich_workbench_pack`` emitted before A3, now sourced from the relocated
    OfflineDirector font banks (``_font_presets`` -> ``_route_font_mode`` ->
    ``_route_font_adjustments``) rather than from workbench-local copies. The
    ``why_this_route_not_other_route`` field carries the required route reason.
    """
    from london.assets import pack_routes  # local import to avoid surfacing assets at module top twice

    groups: list[dict[str, Any]] = []
    for route in pack_routes(pack):
        profile = _profile_key(route, pack)
        route_title = display_text(route.get("title"), fallback="Route")
        headline = display_text(route.get("headline") or route.get("title"), fallback=route_title)
        body = display_text(route.get("subhead") or route.get("rationale"), fallback=clean_brief_text(pack))
        presets = _font_presets(profile, route)
        groups.append(
            {
                "route_id": display_text(route.get("id"), fallback=slugify(route_title)),
                "route_title": route_title,
                "options": [
                    {
                        "id": f"{slugify(route_title)}-{preset['tier']}",
                        "tier": preset["tier"],
                        "label": preset["label"],
                        "name": _fresh_lane_font_text(preset["name"], route_title),
                        "headline_font": preset["headline"],
                        "body_font": preset["body"],
                        "label_font": preset["label_font"],
                        "fallback_stack": preset["stack"],
                        "sample_headline": headline,
                        "sample_body": body,
                        "best_use": preset["best_use"],
                        "why_london_chose_it": f"{preset['why']} It supports {route_title} without pretending a font choice can replace art direction.",
                        "why_this_route_not_other_route": _fresh_lane_font_text(preset["route_reason"], route_title),
                        "what_makes_it_wrong": preset["wrong"],
                        "import_hint": preset["import_hint"],
                    }
                    for preset in presets
                ],
            }
        )
    return groups


def _offline_first_font_stack(route: AbcMapping[str, Any], pack: AbcMapping[str, Any]) -> str:
    """Relocated ``_first_font_stack``: the safe-local stack for a route, sourced
    from the OfflineDirector font banks. ``workbench.build_copy_blocks`` delegates
    here so CSS-variable copy blocks keep the same offline output."""

    profile = _profile_key(route, pack)
    return _font_presets(profile, route)[0]["stack"]


# --- OfflineDirector: implements CreativeDirector by running the relocated banks ---


class OfflineDirector:
    """The labeled ``--offline`` deterministic director (ENG-04 / D-04..D-06).

    Houses the relocated stage-1 + stage-2 banks and produces FULL 7-gate parity
    output. ``isinstance(OfflineDirector(), CreativeDirector)`` holds. The default
    model path NEVER constructs or calls this (D-03); it survives only as the
    explicit offline demo/test surface and as the parity oracle A5 flips against.

    Three delegate methods keep ``session.py``/``workbench.py`` green during A3
    (the temporary direct call the plan sanctions); ``direct()`` is the real
    Protocol contract, returning a schema-valid full-parity ``DirectionResult``.
    """

    origin = OFFLINE_ORIGIN_MARKER

    # --- stage-1 delegates (session.py calls these on the offline path) ---

    def synthesize_lane(self, brief: AbcMapping[str, Any]) -> SessionLane:
        return _synthesize_session_lane(brief)

    def routes_from_lane(
        self,
        lane: CreativeLane,
        brief: AbcMapping[str, Any],
        gates: AbcSequence[AbcMapping[str, Any]],
    ) -> list[dict[str, Any]]:
        return _routes_from_profile(lane, brief, gates)

    def components_for_lane(self, lane: CreativeLane) -> list[str]:
        return _components_for_profile(lane)

    def gate_summary(self, gate_id: str, lane: CreativeLane) -> str:
        return _gate_summary(gate_id, lane)

    def gate_rationale(self, gate_id: str, lane: CreativeLane, findings: AbcSequence[AbcMapping[str, Any]]) -> str:
        return _gate_rationale(gate_id, lane, findings)

    # --- stage-2 delegates (workbench.py calls these on the offline path) ---

    def font_groups(self, pack: AbcMapping[str, Any]) -> list[dict[str, Any]]:
        return _offline_font_groups(pack)

    def first_font_stack(self, route: AbcMapping[str, Any], pack: AbcMapping[str, Any]) -> str:
        return _offline_first_font_stack(route, pack)

    # --- the Protocol contract: one structured call returns full-parity output ---

    def direct(self, request: DirectionRequest) -> DirectionResult:
        """Run the relocated deterministic synthesis and return a schema-valid,
        full-parity ``DirectionResult`` (D-06): lane + 2 routes + per-gate
        conversation + 3-tier fonts + route comparison + copy + next steps.

        The offline origin marker lives on ``OfflineDirector.origin`` (receipts
        only); it is never written into any ``DirectionResult`` prose field.
        """

        from london.persona import GATE_IDS, GATE_NAMES

        brief = dict(request.brief)
        brief.setdefault("title", str(brief.get("title", "")) or "Untitled London brief")
        brief.setdefault("text", str(brief.get("text", "")))
        brief.setdefault("digest", hashlib.sha256(str(brief.get("text", "")).encode("utf-8")).hexdigest()[:12])

        lane = _synthesize_session_lane(brief)

        # Build the stage-1 route dicts (no brain gates available offline -> empty).
        route_dicts = _routes_from_profile(lane, brief, [])
        lane_palette = [PaletteColor(**color) for color in lane.palette]

        routes: list[RouteResult] = []
        for route in route_dicts:
            routes.append(
                RouteResult(
                    title=route["title"],
                    headline=route["headline"],
                    subhead=route["subhead"],
                    palette=[PaletteColor(**color) for color in route["palette"]],
                    tags=list(route.get("tags", [])),
                    lore=route["lore"],
                    mood=route["mood"],
                    type_note=route["type"],
                    rationale=route["rationale"],
                    steal=list(route.get("steal", [])),
                    do_not_copy=list(route.get("do_not_copy", [])),
                    sections=[
                        RouteSection(title=section["title"], body=section["body"])
                        for section in route.get("sections", [])
                    ],
                )
            )

        # Stage-2 font groups need a pack-shaped dict; assemble the minimal view.
        offline_pack = {
            "title": brief["title"],
            "category_assumption": lane.category_assumption,
            "routes": route_dicts,
        }
        font_groups_raw = _offline_font_groups(offline_pack)
        font_options = [
            FontRouteGroup(
                route_title=group["route_title"],
                options=[
                    FontOption(
                        tier=option["tier"],
                        name=option["name"],
                        headline_font=option["headline_font"],
                        body_font=option["body_font"],
                        label_font=option["label_font"],
                        fallback_stack=option["fallback_stack"],
                        best_use=option["best_use"],
                        why_london_chose_it=option["why_london_chose_it"],
                        why_this_route_not_other_route=option["why_this_route_not_other_route"],
                        what_makes_it_wrong=option["what_makes_it_wrong"],
                        import_hint=option["import_hint"],
                    )
                    for option in group["options"]
                ],
            )
            for group in font_groups_raw
        ]

        conversation = [
            ConversationRead(
                gate=GATE_NAMES.get(gate_id, gate_id),
                decision=_gate_summary(gate_id, lane),
                rationale=_gate_rationale(gate_id, lane, []),
                critique=f"Reject anything that collapses {lane.label} into generic modern-clean taste.",
                answer=_gate_summary(gate_id, lane),
            )
            for gate_id in GATE_IDS
        ]

        route_comparison = [
            RouteComparison(
                title=route.title,
                thesis=route.headline,
                best_for=f"{lane.audience} when the first build needs {route.sections[0].title.lower() if route.sections else 'a clear product proof'}.",
                visual_world=route.mood,
                type=route.type_note,
                palette_logic="; ".join(f"{color.role}: {color.name} {color.hex}" for color in route.palette),
                steal=route.steal[0] if route.steal else "Steal the structural idea, not the surface.",
                do_not_copy=route.do_not_copy[0] if route.do_not_copy else "Do not copy exact styling, assets, or source composition.",
                first_build_move=(route.sections[0].body if route.sections else route.rationale),
                risk=lane.risks[index % len(lane.risks)] if lane.risks else "The route gets weaker if it becomes generic decoration.",
            )
            for index, route in enumerate(routes)
        ]

        copy_blocks = [
            CopyBlock(
                kind="route_summary",
                label=f"{route.title} Summary",
                text=f"{route.title}: {route.headline}\n\n{route.rationale}",
            )
            for route in routes
        ]

        next_steps = [
            NextStep(
                label=f"Build {route.title}",
                description=f"Start with {route.headline} and prove {route.sections[0].title if route.sections else route.title}.",
                action_type="prototype",
            )
            for route in routes
        ]

        return DirectionResult(
            category_assumption=lane.category_assumption,
            aesthetic_void=lane.aesthetic_void,
            london_reframe=lane.london_reframe,
            vessel_expression=lane.vessel_expression,
            recurring_loop=lane.recurring_loop,
            unboxing=lane.unboxing,
            anti_position=lane.anti_position,
            product_noun=lane.product_noun,
            audience=lane.audience,
            jobs=list(lane.jobs),
            rituals=list(lane.rituals),
            surfaces=list(lane.surfaces),
            tensions=list(lane.tensions),
            tone=list(lane.tone),
            avoid=list(lane.avoid),
            output_moments=list(lane.output_moments),
            source_terms=lane.source_terms,
            label=lane.label,
            voice=lane.voice,
            type_system=lane.type_system,
            color_system=lane.color_system,
            palette=lane_palette,
            routes=routes,
            # Honest keyless floor (D-04): the machine reference = the lead route, never a
            # faked ranking; the recommendation PROSE = "" (the offline path never argues a
            # case — only the host model writes a verbatim argument).
            recommended_route_ref=routes[0].title or "Route 01",
            recommended_route="",
            # Honest keyless default (GATE-02 / RESEARCH Pitfall 3): the deterministic keyless
            # path cannot truthfully infer a specific type, so it defaults to "generic" —
            # never a faked specific type. Only the host model / flag / brief may assert one.
            artifact_type="generic",
            conversation=conversation,
            font_options=font_options,
            route_comparison=route_comparison,
            copy_blocks=copy_blocks,
            next_steps=next_steps,
        )

    def direct_with_telemetry(
        self, request: DirectionRequest
    ) -> tuple[DirectionResult, RunTelemetry]:
        # The offline path queries no brain MCP — emit HONEST captured=False telemetry
        # (engine_mode="offline"), never a faked capture (D-11 / T-05-08).
        return self.direct(request), _honest_empty_telemetry("offline")

__all__ = [
    "OfflineDirector",
    "ROUTE_SYNTHESIS_PROVIDER",
    "OFFLINE_ORIGIN_MARKER",
    "RouteSeed",
    "CategoryProfile",
    "SessionLane",
    "CreativeLane",
    "PROFILES",
    "_offline_first_font_stack",
]
