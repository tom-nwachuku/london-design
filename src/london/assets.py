from __future__ import annotations

from html import escape
from re import fullmatch
from typing import Any, Mapping, Sequence
from urllib.parse import quote

from .text import clean_brief_text, clean_title, display_text

DEFAULT_PALETTE = [
    {"role": "spark", "name": "Signal Orange", "hex": "#ff6b35"},
    {"role": "ground", "name": "Warm Paper", "hex": "#f7f1df"},
    {"role": "accent", "name": "Mint Circuit", "hex": "#56c7b6"},
    {"role": "ink", "name": "Soft Black", "hex": "#151515"},
    {"role": "glow", "name": "Hardware Yellow", "hex": "#ffd447"},
]


def slugify(value: str, fallback: str = "route") -> str:
    """Return a small stable slug for generated route and asset ids."""
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in value)
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return cleaned or fallback


def normalize_palette(raw_palette: Sequence[Any] | None = None) -> list[dict[str, str]]:
    """Normalize hex strings or color dictionaries into public palette entries."""
    if not raw_palette:
        return [dict(color) for color in DEFAULT_PALETTE]

    normalized: list[dict[str, str]] = []
    for index, color in enumerate(raw_palette):
        role = f"color {index + 1}"
        name = role.title()
        hex_value = ""

        if isinstance(color, str):
            hex_value = color.strip()
        elif isinstance(color, Mapping):
            role = str(color.get("role") or color.get("label") or role)
            name = str(color.get("name") or color.get("title") or role.title())
            hex_value = str(color.get("hex") or color.get("value") or "").strip()

        if not fullmatch(r"#[0-9a-fA-F]{6}", hex_value):
            continue

        normalized.append({"role": role, "name": name, "hex": hex_value.lower()})

    return normalized or [dict(color) for color in DEFAULT_PALETTE]


def normalize_tags(tags: Sequence[Any] | None, defaults: Sequence[str] = ()) -> list[str]:
    values = [str(tag).strip() for tag in tags or [] if str(tag).strip()]
    return values or list(defaults)


def svg_data_uri(
    title: str,
    subtitle: str = "",
    palette: Sequence[Any] | None = None,
    *,
    label: str = "London local preview",
    width: int = 1440,
    height: int = 920,
) -> str:
    """Build a deterministic SVG data URI for local fallback previews."""
    colors = normalize_palette(palette)
    c0 = colors[0]["hex"]
    c1 = colors[1]["hex"] if len(colors) > 1 else "#f7f1df"
    c2 = colors[2]["hex"] if len(colors) > 2 else "#56c7b6"
    c3 = colors[3]["hex"] if len(colors) > 3 else "#151515"
    c4 = colors[4]["hex"] if len(colors) > 4 else c0
    title_text = escape(title[:72])
    subtitle_text = escape(subtitle[:110])
    label_text = escape(label[:48])
    scene = _scene_kind(f"{title} {subtitle}")
    scene_markup = _scene_markup(scene, width, height, c0, c1, c2, c3, c4)

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
  <title id="title">{title_text}</title>
  <desc id="desc">{subtitle_text or label_text}; scene:{scene}</desc>
  <rect width="{width}" height="{height}" fill="{c1}"/>
  <metadata>london-scene:{scene}</metadata>
  {scene_markup}
  <text x="104" y="134" fill="{c1}" font-family="Arial, Helvetica, sans-serif" font-size="28" font-weight="700" letter-spacing="3">{label_text}</text>
  <text x="104" y="{height - 170}" fill="{c1}" font-family="Georgia, serif" font-size="76" font-weight="700">{title_text}</text>
  <text x="108" y="{height - 98}" fill="{c1}" font-family="Arial, Helvetica, sans-serif" font-size="30">{subtitle_text}</text>
</svg>"""
    return "data:image/svg+xml;charset=utf-8," + quote(svg, safe="(),;:#%/=?&\"'")


def visual_direction_board_data_uri(
    title: str,
    prompt: str,
    palette: Sequence[Any] | None = None,
    *,
    type_note: str = "",
    brain_cues: Sequence[str] = (),
    source_cues: Sequence[str] = (),
    width: int = 1440,
    height: int = 920,
) -> str:
    """Build an honest local board: visual direction, not generated concept art."""

    colors = normalize_palette(palette)
    c0 = colors[0]["hex"]
    c1 = colors[1]["hex"] if len(colors) > 1 else "#f7f1df"
    c2 = colors[2]["hex"] if len(colors) > 2 else "#56c7b6"
    c3 = colors[3]["hex"] if len(colors) > 3 else "#151515"
    c4 = colors[4]["hex"] if len(colors) > 4 else c0
    title_text = escape((title or "London route")[:70])
    type_text = escape(board_label(type_note or "Route headline, label, body rhythm.", max_chars=74))
    thesis_lines = _svg_text_lines(board_prompt_summary(prompt), 48, 2)
    cue_values = [board_cue(cue) for cue in [*brain_cues, *source_cues] if board_cue(cue)]
    cue_values = cue_values[:5]
    cue_lines = cue_values or ["Route evidence remains in the prompt and receipts."]
    swatches = "\n".join(
        f'<g transform="translate({90 + index * 120} 690)">'
        f'<rect width="92" height="92" rx="14" fill="{escape(color["hex"])}" stroke="#151515" stroke-width="3"/>'
        f'<text x="0" y="122" fill="#151515" font-family="Arial, Helvetica, sans-serif" font-size="18">{escape(color["hex"])}</text>'
        f'<text x="0" y="146" fill="#151515" font-family="Arial, Helvetica, sans-serif" font-size="14">{escape(color["role"][:16])}</text>'
        "</g>"
        for index, color in enumerate(colors[:5])
    )
    thesis_markup = _svg_multiline(thesis_lines, 790, 238, 28, "#151515", size=24, family="Arial, Helvetica, sans-serif")
    cue_markup = _svg_bullet_lines(cue_lines, 790, 536, 25, "#151515")

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
  <title id="title">{title_text} visual direction board</title>
  <desc id="desc">Visual direction board. Not generated concept art.</desc>
  <rect width="{width}" height="{height}" fill="{c1}"/>
  <rect x="56" y="54" width="{width - 112}" height="{height - 108}" rx="28" fill="#f8f4eb" stroke="#151515" stroke-width="4"/>
  <rect x="90" y="92" width="{width - 180}" height="92" rx="18" fill="{c3}"/>
  <text x="122" y="132" fill="{c1}" font-family="Arial, Helvetica, sans-serif" font-size="20" font-weight="700" letter-spacing="2">VISUAL DIRECTION BOARD - NOT GENERATED ART</text>
  <text x="122" y="166" fill="{c1}" font-family="Georgia, serif" font-size="34" font-weight="700">{title_text}</text>
  <g transform="translate(90 224)">
    <rect x="0" y="0" width="610" height="380" rx="20" fill="{c3}"/>
    <rect x="34" y="34" width="256" height="142" rx="18" fill="{c0}"/>
    <rect x="320" y="34" width="222" height="142" rx="18" fill="{c2}"/>
    <rect x="34" y="206" width="508" height="118" rx="18" fill="{c4}"/>
    <path d="M64 354 H526" stroke="{c1}" stroke-width="14" stroke-linecap="round"/>
    <circle cx="94" cy="354" r="20" fill="{c0}"/><circle cx="252" cy="354" r="20" fill="{c2}"/><circle cx="410" cy="354" r="20" fill="{c4}"/>
  </g>
  <text x="790" y="232" fill="#151515" font-family="Arial, Helvetica, sans-serif" font-size="18" font-weight="700" letter-spacing="2">ROUTE THESIS</text>
  {thesis_markup}
  <text x="790" y="422" fill="#151515" font-family="Georgia, serif" font-size="46" font-weight="700">Aa</text>
  <text x="856" y="418" fill="#151515" font-family="Arial, Helvetica, sans-serif" font-size="22">{type_text}</text>
  <text x="790" y="506" fill="#151515" font-family="Arial, Helvetica, sans-serif" font-size="18" font-weight="700" letter-spacing="2">EVIDENCE CUES</text>
  {cue_markup}
  <text x="90" y="666" fill="#151515" font-family="Arial, Helvetica, sans-serif" font-size="18" font-weight="700" letter-spacing="2">PALETTE SWATCHES</text>
  {swatches}
</svg>"""
    return "data:image/svg+xml;charset=utf-8," + quote(svg, safe="(),;:#%/=?&\"'")


def _clip_words(text: str, max_chars: int) -> str:
    cleaned = " ".join(str(text or "").replace("\n", " ").split())
    if len(cleaned) <= max_chars:
        return cleaned
    clipped = cleaned[: max(0, max_chars - 3)].rstrip(" ,.;:-")
    return f"{clipped}..."


def board_label(text: str, max_chars: int = 48) -> str:
    return _clip_words(text, max_chars)


def board_cue(text: str, max_chars: int = 90) -> str:
    return _clip_words(text, max_chars)


def board_prompt_summary(prompt: str, max_chars: int = 140) -> str:
    return _clip_words(prompt, max_chars) or "Visual system summary lives in the route prompt."


def _svg_text_lines(text: str, line_length: int, max_lines: int) -> list[str]:
    words = (text or "").replace("\n", " ").split()
    lines: list[str] = []
    current = ""
    for word in words:
        next_line = f"{current} {word}".strip()
        if len(next_line) > line_length and current:
            lines.append(current)
            current = word
        else:
            current = next_line
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if words and len(lines) == max_lines and " ".join(words) != " ".join(lines):
        lines[-1] = lines[-1].rstrip(".") + "..."
    return lines or [""]


def _svg_multiline(
    lines: Sequence[str],
    x: int,
    y: int,
    line_height: int,
    fill: str,
    *,
    size: int,
    family: str,
) -> str:
    return "\n".join(
        f'<text x="{x}" y="{y + index * line_height}" fill="{fill}" font-family="{family}" font-size="{size}">{escape(line)}</text>'
        for index, line in enumerate(lines)
        if line
    )


def _svg_bullet_lines(lines: Sequence[str], x: int, y: int, line_height: int, fill: str) -> str:
    return "\n".join(
        f'<text x="{x}" y="{y + index * line_height}" fill="{fill}" font-family="Arial, Helvetica, sans-serif" font-size="19">'
        f'<tspan font-weight="700">{index + 1}.</tspan> {escape(line)}</text>'
        for index, line in enumerate(lines)
        if line
    )


def _scene_kind(text: str) -> str:
    lower = text.lower()
    if any(term in lower for term in ("weather", "forecast", "walk", "alert", "pet owner")):
        return "weather-decision"
    if any(term in lower for term in ("horoscope", "astrology", "zodiac", "chart", "reading")):
        return "chart-briefing"
    if any(term in lower for term in ("fragrance", "scent", "perfume", "compact", "refill")):
        return "vessel-ritual"
    if any(term in lower for term in ("lunch", "snack", "school", "sticker")):
        return "object-kit"
    if any(term in lower for term in ("compliance", "audit", "policy", "proof")):
        return "proof-desk"
    if any(term in lower for term in ("app", "mobile", "dashboard", "card")):
        return "app-system"
    return "artifact-system"


def _scene_markup(scene: str, width: int, height: int, c0: str, c1: str, c2: str, c3: str, c4: str) -> str:
    if scene == "weather-decision":
        return f"""
  <rect x="72" y="72" width="{width - 144}" height="{height - 144}" rx="36" fill="{c3}"/>
  <g transform="translate(160 170)">
    <rect x="0" y="0" width="340" height="570" rx="46" fill="{c1}" stroke="{c4}" stroke-width="10"/>
    <circle cx="250" cy="118" r="58" fill="{c0}"/>
    <path d="M86 154 C118 92 210 102 232 170 C288 166 322 205 318 252 L76 252 C48 224 50 178 86 154Z" fill="{c2}"/>
    <path d="M74 350 C150 294 232 418 306 348" fill="none" stroke="{c3}" stroke-width="18" stroke-linecap="round"/>
    <circle cx="104" cy="352" r="20" fill="{c0}"/><circle cx="302" cy="348" r="20" fill="{c4}"/>
  </g>
  <g transform="translate(600 190)">
    <rect x="0" y="0" width="620" height="112" rx="24" fill="{c1}"/><rect x="0" y="150" width="500" height="112" rx="24" fill="{c2}"/><rect x="0" y="300" width="560" height="112" rx="24" fill="{c0}"/>
    <path d="M24 504 L560 504" stroke="{c4}" stroke-width="18" stroke-linecap="round"/>
    <circle cx="110" cy="504" r="34" fill="{c1}"/><circle cx="300" cy="504" r="34" fill="{c2}"/><circle cx="490" cy="504" r="34" fill="{c0}"/>
  </g>"""
    if scene == "chart-briefing":
        return f"""
  <rect x="72" y="72" width="{width - 144}" height="{height - 144}" rx="36" fill="{c3}"/>
  <circle cx="{int(width * 0.34)}" cy="{int(height * 0.42)}" r="220" fill="none" stroke="{c1}" stroke-width="22"/>
  <circle cx="{int(width * 0.34)}" cy="{int(height * 0.42)}" r="132" fill="none" stroke="{c2}" stroke-width="10"/>
  <path d="M490 175 L490 600 M270 388 L710 388 M334 232 L646 544 M646 232 L334 544" stroke="{c4}" stroke-width="8"/>
  <circle cx="490" cy="388" r="54" fill="{c0}"/>
  <g transform="translate(790 170)">
    <rect x="0" y="0" width="330" height="430" rx="34" fill="{c1}" stroke="{c4}" stroke-width="10"/>
    <circle cx="166" cy="128" r="70" fill="{c2}"/>
    <rect x="58" y="250" width="214" height="22" rx="11" fill="{c3}"/><rect x="58" y="304" width="160" height="22" rx="11" fill="{c0}"/>
  </g>"""
    if scene == "vessel-ritual":
        return f"""
  <rect x="72" y="72" width="{width - 144}" height="{height - 144}" rx="22" fill="{c3}"/>
  <g transform="translate(270 170)">
    <rect x="0" y="80" width="350" height="350" rx="72" fill="{c1}" stroke="{c4}" stroke-width="14"/>
    <rect x="86" y="0" width="178" height="128" rx="30" fill="{c0}"/>
    <circle cx="176" cy="256" r="82" fill="{c2}"/>
    <path d="M102 482 L250 482" stroke="{c4}" stroke-width="18" stroke-linecap="round"/>
  </g>
  <g transform="translate(760 200)">
    <rect x="0" y="0" width="390" height="118" rx="18" fill="{c1}"/><rect x="0" y="158" width="320" height="118" rx="18" fill="{c4}"/><rect x="0" y="316" width="360" height="118" rx="18" fill="{c2}"/>
  </g>"""
    if scene == "proof-desk":
        return f"""
  <rect x="72" y="72" width="{width - 144}" height="{height - 144}" rx="28" fill="{c3}"/>
  <g transform="translate(170 165)">
    <rect x="0" y="0" width="450" height="540" rx="24" fill="{c1}" stroke="{c4}" stroke-width="10"/>
    <rect x="50" y="72" width="250" height="28" rx="14" fill="{c0}"/><rect x="50" y="146" width="350" height="20" rx="10" fill="{c3}"/>
    <rect x="50" y="220" width="350" height="70" rx="14" fill="{c2}"/><rect x="50" y="330" width="350" height="70" rx="14" fill="{c4}"/>
  </g>
  <path d="M760 230 L1160 230 M760 350 L1120 350 M760 470 L1190 470 M760 590 L1080 590" stroke="{c1}" stroke-width="24" stroke-linecap="round"/>"""
    if scene == "object-kit":
        return f"""
  <rect x="72" y="72" width="{width - 144}" height="{height - 144}" rx="38" fill="{c3}"/>
  <g transform="translate(230 190)">
    <rect x="0" y="0" width="520" height="360" rx="46" fill="{c1}" stroke="{c4}" stroke-width="12"/>
    <rect x="36" y="42" width="210" height="130" rx="28" fill="{c0}"/><rect x="276" y="42" width="204" height="130" rx="28" fill="{c2}"/>
    <rect x="36" y="202" width="444" height="110" rx="28" fill="{c4}"/>
  </g>
  <g transform="translate(840 210)">
    <circle cx="70" cy="70" r="58" fill="{c0}"/><circle cx="210" cy="70" r="58" fill="{c2}"/><circle cx="350" cy="70" r="58" fill="{c4}"/>
    <rect x="0" y="210" width="430" height="72" rx="36" fill="{c1}"/>
  </g>"""
    if scene == "app-system":
        return f"""
  <rect x="72" y="72" width="{width - 144}" height="{height - 144}" rx="36" fill="{c3}"/>
  <g transform="translate(210 150)">
    <rect x="0" y="0" width="330" height="610" rx="48" fill="{c1}" stroke="{c4}" stroke-width="10"/>
    <rect x="36" y="72" width="258" height="126" rx="26" fill="{c0}"/><rect x="36" y="236" width="258" height="86" rx="22" fill="{c2}"/><rect x="36" y="356" width="258" height="158" rx="26" fill="{c3}"/>
  </g>
  <g transform="translate(660 180)">
    <rect x="0" y="0" width="560" height="130" rx="30" fill="{c1}"/><rect x="0" y="172" width="430" height="130" rx="30" fill="{c2}"/><rect x="0" y="344" width="520" height="130" rx="30" fill="{c0}"/>
  </g>"""
    return f"""
  <rect x="72" y="72" width="{width - 144}" height="{height - 144}" rx="42" fill="{c3}"/>
  <circle cx="{int(width * 0.78)}" cy="{int(height * 0.24)}" r="{int(height * 0.14)}" fill="{c0}"/>
  <circle cx="{int(width * 0.18)}" cy="{int(height * 0.72)}" r="{int(height * 0.1)}" fill="{c2}"/>
  <path d="M180 {int(height * 0.33)} C360 118 525 228 650 158 S945 105 1175 250" fill="none" stroke="{c4}" stroke-width="22" stroke-linecap="round"/>
  <g transform="translate({int(width * 0.5)} {int(height * 0.56)})">
    <rect x="-220" y="-150" width="440" height="300" rx="42" fill="{c1}" stroke="{c4}" stroke-width="10"/>
    <rect x="-154" y="-78" width="308" height="156" rx="30" fill="{c3}"/>
    <circle cx="-82" cy="0" r="35" fill="{c0}"/>
    <circle cx="0" cy="0" r="35" fill="{c2}"/>
    <circle cx="82" cy="0" r="35" fill="{c4}"/>
  </g>"""


def fallback_asset(
    title: str,
    subtitle: str = "",
    palette: Sequence[Any] | None = None,
    *,
    kind: str = "preview",
) -> dict[str, Any]:
    safe_title = title.strip() or "London local preview"
    normalized_kind = kind.strip().lower().replace("_", "-")
    if normalized_kind in {"preview", "system-sketch", "local-system-sketch", "fixture-system-sketch"}:
        kind_label = "system sketch"
    elif normalized_kind in {"generated-concept", "generated-concept-image"}:
        kind_label = "generated concept"
    else:
        kind_label = f"{kind.strip()} preview"
    return {
        "id": slugify(safe_title, fallback="asset"),
        "title": safe_title,
        "alt": f"{safe_title} deterministic {kind_label}",
        "caption": subtitle.strip() or "Local deterministic image generated from pack text.",
        "kind": kind,
        "src": svg_data_uri(safe_title, subtitle, palette, label=kind_label.title()),
    }


def route_assets(route: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_assets = route.get("assets") or route.get("previews") or []
    assets: list[dict[str, Any]] = []
    for index, asset in enumerate(raw_assets):
        if not isinstance(asset, Mapping):
            continue
        title = display_text(asset.get("title") or asset.get("name"), fallback=f"Preview {index + 1}")
        src = display_text(asset.get("src") or asset.get("url")).strip()
        kind = display_text(asset.get("kind"), fallback="preview")
        prompt_only = kind in {"manual-prompt-card", "generation-unavailable", "visual-direction-board"}
        if not src and not prompt_only:
            src = svg_data_uri(
                title,
                str(asset.get("caption") or route.get("rationale") or ""),
                route.get("palette"),
                label="Route preview",
            )
        asset_row: dict[str, Any] = {
            "id": str(asset.get("id") or slugify(title, fallback=f"asset-{index + 1}")),
            "title": title,
            "alt": display_text(asset.get("alt"), fallback=f"{title} preview"),
            "caption": display_text(asset.get("caption")),
            "kind": kind,
        }
        if src:
            asset_row["src"] = src
        for key in (
            "provider",
            "requested_provider",
            "resolved_provider",
            "generation_status",
            "generation_mode",
            "model",
            "receipt_id",
            "prompt",
            "prompt_ref",
            "copy_label",
            "evidence_class",
            "board_sections",
            "deterministic",
            "live_artifact",
        ):
            if key in asset:
                asset_row[key] = asset[key]
        assets.append(asset_row)

    if assets:
        return assets

    title = display_text(route.get("title") or route.get("name"), fallback="London route")
    rationale = display_text(route.get("rationale") or route.get("thesis"))
    return [fallback_asset(title, rationale, route.get("palette"))]


def fallback_routes(pack: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Create deterministic route content when providers or upstream phases are absent."""
    title = clean_title(pack, fallback="Untitled London Pack")
    brief = clean_brief_text(pack, fallback="A tactile product needs a public visual system.")
    base_id = slugify(title, fallback="london-pack")

    route_one = {
        "id": f"{base_id}-joy-object",
        "title": "Joy Object System",
        "headline": f"{title}: make the object feel kept, not consumed.",
        "subhead": "A bright hardware language with tactile cues, generous product scale, and a little retail theater.",
        "palette": DEFAULT_PALETTE,
        "tags": ["tactile hardware", "retro future", "postable packaging"],
        "lore": "The product behaves like a desk companion: practical enough to earn its footprint, odd enough to start a conversation.",
        "mood": "Optimistic, crisp, slightly strange, and merchandised like the box is part of the product.",
        "type": "Wide grotesk for utility, soft serif moments for collector-grade warmth.",
        "rationale": "London would give the hero one large object truth, then let color and packaging carry the shareability.",
        "steal": [
            "Use the packaging grid as the page grid.",
            "Make one tactile detail enormous before showing the whole object.",
            "Let color name the feature states instead of decorating them.",
        ],
        "do_not_copy": [
            "Do not turn retro into nostalgia wallpaper.",
            "Do not hide the product inside generic lifestyle haze.",
        ],
        "sections": [
            {"title": "Hero Object", "body": brief},
            {"title": "Feature Ritual", "body": "Show the hand, the click, the light, and the reason to keep it nearby."},
            {"title": "Retail Proof", "body": "Close with the box, the insert, the sticker, and the tiny reason someone posts it."},
        ],
        "approval_state": "fixture-only",
    }
    route_one["assets"] = [fallback_asset(route_one["title"], route_one["rationale"], route_one["palette"])]

    route_two_palette = [
        {"role": "signal", "name": "Cobalt Switch", "hex": "#2457ff"},
        {"role": "ground", "name": "Bone Plastic", "hex": "#f4ead8"},
        {"role": "accent", "name": "Tomato Button", "hex": "#e8412f"},
        {"role": "ink", "name": "Graphite", "hex": "#202124"},
        {"role": "glow", "name": "Acid Lime", "hex": "#c7f464"},
    ]
    route_two = {
        "id": f"{base_id}-utility-wink",
        "title": "Utility With A Wink",
        "headline": f"{title}: useful first, collectible second, boring never.",
        "subhead": "A more graphic route built from interface labels, instruction-sheet rhythm, and confident negative space.",
        "palette": route_two_palette,
        "tags": ["instruction sheet", "collector utility", "graphic restraint"],
        "lore": "The product arrives with the confidence of a tool and the charm of a toy you are allowed to keep on your desk.",
        "mood": "Precise, playful, calmer than the palette suggests.",
        "type": "Condensed utility labels paired with readable body copy.",
        "rationale": "This route makes restraint feel expensive by treating every label, shadow, and color hit as part of the product behavior.",
        "steal": [
            "Borrow the discipline of manuals, then break it once per screen.",
            "Use labels as composition, not annotation.",
        ],
        "do_not_copy": [
            "Do not make it look like a SaaS dashboard.",
            "Do not over-explain the joke.",
        ],
        "sections": [
            {"title": "Interface Hero", "body": brief},
            {"title": "Manual Rhythm", "body": "Turn setup and use states into art-directed panels."},
            {"title": "Shelf Finish", "body": "End with the whole kit arranged like a product photo from a sharper future."},
        ],
        "approval_state": "fixture-only",
    }
    route_two["assets"] = [fallback_asset(route_two["title"], route_two["rationale"], route_two["palette"])]

    return [route_one, route_two]


def pack_routes(pack: Mapping[str, Any]) -> list[dict[str, Any]]:
    routes = pack.get("routes") if isinstance(pack, Mapping) else None
    if isinstance(routes, Sequence) and not isinstance(routes, (str, bytes)):
        cleaned = [dict(route) for route in routes if isinstance(route, Mapping)]
        if cleaned:
            return cleaned
    return fallback_routes(pack)
