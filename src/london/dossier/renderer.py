from __future__ import annotations

import json
import re
from html import escape as _html_escape
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..assets import normalize_palette, pack_routes, slugify
from ..font_preview import font_face_css_for_groups, resolve_font_preview
from ..navigation import NavLink, Navigation, build_navigation
from ..persona import VOICE_TEMPLATES
from ..route_refs import resolve_route_ref
from ..safe_urls import safe_href
from ..text import clean_brief_text, clean_title, display_text
from .sections import SECTIONS as _SECTIONS
from .shared import (
    _as_mappings,
    _clip_detail,
    _prepared_pack,
    _public_type_rationale,
    _render_type_roles,
)


def humanize_public_text(value: Any) -> str:
    """Normalize punctuation in rendered public copy without changing meaning."""
    text = str(value)
    text = re.sub(r"\s*(?:—|–|&mdash;|&#8212;|&#x2014;|--)\s*", ": ", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


def escape(value: Any, quote: bool = True) -> str:
    return _html_escape(str(value), quote=quote)


def escape_prose(value: Any, quote: bool = True) -> str:
    return _html_escape(humanize_public_text(value), quote=quote)


def _as_strings(value: Any, fallback: Sequence[str] = ()) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else list(fallback)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        strings = [display_text(item) for item in value if display_text(item)]
        return strings or list(fallback)
    text = display_text(value)
    return [text] if text else list(fallback)


def _paragraph(value: Any, *, class_name: str) -> str:
    text = display_text(value)
    return f'<p class="{escape(class_name, quote=True)}">{escape(text)}</p>' if text else ""


def _scan_read(value: Any) -> str:
    text = " ".join(display_text(value).split())
    if not text:
        return ""
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    if len(parts) < 3 or len(text) < 220:
        return _paragraph(text, class_name="command-center-read")
    lead = parts[0]
    bullets = parts[1:5]
    if len(parts) > 5:
        bullets[-1] = " ".join([bullets[-1], *parts[5:]])
    items = "".join(f"<li>{escape(item)}</li>" for item in bullets)
    return f"""
        <p class="command-center-read-lead">{escape(lead)}</p>
        <ul class="command-center-read-list">{items}</ul>"""


def _route_id(route: Mapping[str, Any], fallback: str) -> str:
    return display_text(route.get("id"), fallback=slugify(display_text(route.get("title"), fallback=fallback), fallback=fallback))


def _route_font_option(pack: Mapping[str, Any], route_id: str) -> Mapping[str, Any]:
    for group in _as_mappings(pack.get("font_options")):
        if display_text(group.get("route_id")) != route_id:
            continue
        options = _as_mappings(group.get("options"))
        for option in options:
            if resolve_font_preview(option).is_actual_loaded:
                return option
        for option in options:
            if display_text(option.get("tier")) == "safe_local":
                return option
        return options[0] if options else {}
    return {}


def _font_type_read(route: Mapping[str, Any], option: Mapping[str, Any], preview) -> tuple[str, str, str, str]:
    family = display_text(
        option.get("name") if isinstance(option, Mapping) else "",
        fallback=display_text(preview.rendered_family, fallback="Type system"),
    )
    direction = display_text(
        route.get("type") or route.get("typography"),
        fallback=display_text(option.get("sample_headline") if isinstance(option, Mapping) else "", fallback=family),
    )
    rationale = _public_type_rationale(
        option.get("why_london_chose_it") if isinstance(option, Mapping) else "",
        option.get("why_this_route_not_other_route") if isinstance(option, Mapping) else "",
    )
    best_use = display_text(option.get("best_use") if isinstance(option, Mapping) else "")
    return family, direction, rationale, best_use


def _type_read_paragraphs(rationale: str, best_use: str, *, class_name: str = "specimen-note") -> str:
    paragraphs = []
    if rationale:
        paragraphs.append(f'<p class="{escape(class_name, quote=True)}">{escape(rationale)}</p>')
    if best_use:
        paragraphs.append(f'<p class="{escape(class_name, quote=True)} is-muted">{escape(best_use)}</p>')
    return "".join(paragraphs)


def _font_proof_details(preview) -> str:
    source = display_text(preview.source_label)
    license_note = display_text(preview.license_note)
    display_state = display_text(getattr(preview, "display_state", ""))
    font_file_href = display_text(getattr(preview, "font_file_href", ""))
    if not source and not license_note and not display_state and not font_file_href:
        return ""
    detail_rows = []
    if display_state:
        detail_rows.append(("Display state", display_state))
    if source:
        detail_rows.append(("Source", source))
    if license_note:
        detail_rows.append(("License / proof", license_note))
    if font_file_href:
        detail_rows.append(("Font file", font_file_href))
    rows = "".join(
        f"<div><dt>{escape(label)}</dt><dd>{escape(value)}</dd></div>"
        for label, value in detail_rows
    )
    return f"""
      <details class="receipt-detail is-receipt-detail">
        <summary>Source/license details</summary>
        <dl>{rows}</dl>
      </details>"""


def _swatches(palette: Sequence[Mapping[str, Any]]) -> str:
    # TPL-05 / D-06 swatch-on-white: the chip ground is WHITE (--card), the color shows as an
    # inner .swatch-chip sample. Hex values remain in the CSS variable for rendering; public
    # first-read text shows role/name only so palette does not read like debug output. One
    # invert here covers every dossier swatch site because both call sites route through this
    # helper. Escape discipline preserved (T-04-10): hex is escaped with quote=True in the
    # attribute context; role/name are escaped in text content.
    rows = []
    for color in palette:
        role = _public_handoff_text(color["role"])
        name = _public_handoff_text(color["name"])
        if role.lower() == "evidence" and name.lower().startswith("evidence note"):
            name = "Evidence Mark"
        rows.append(
            f"""<span class="swatch" style="--swatch:{escape(color['hex'], quote=True)}">
          <span class="swatch-chip"></span><b>{escape(role)}</b><small>{escape(name)}</small>
        </span>"""
        )
    return "".join(rows)


_SECTION_GUIDANCE: dict[str, dict[str, str]] = {
    "moodboard": {
        "one_line": "Start with the visual read: the hero, palette, type, and tension pairs should reveal the route before the prose explains it.",
        "what": "A route-specific board of concept imagery, palette, type, product moments, and constraints.",
        "how_to_use": "Scan the hero and tension pair first, then inspect the supporting tiles for what must stay in or out.",
    },
    "routes": {
        "one_line": "The route dossier is the decision layer; choose the lane with the clearest object case, not the prettiest surface.",
        "what": "A full route view with preview, palette, tags, type specimen, rationale, and build constraints.",
        "how_to_use": "Switch routes and compare what each route asks the product to prove on the first screen.",
    },
    "comparison": {
        "one_line": "This is where taste becomes a tradeoff: if two routes feel close, the risk and first build move should break the tie.",
        "what": "A side-by-side matrix of route thesis, fit, visual world, type, palette logic, and risk.",
        "how_to_use": "Read across one row at a time and pick the route whose tradeoff you can defend.",
    },
    "font-lab": {
        "one_line": "Type is a behavior choice here; the right stack should make the route easier to use, not just better dressed.",
        "what": "Three type lanes per route: local-safe, open/public, and premium inspiration.",
        "how_to_use": "Compare why London chose each stack and where it becomes wrong for the route.",
    },
    "conversation": {
        "one_line": "The conversation shows London’s actual decisions in order, so sparse cards are signal rather than missing ceremony.",
        "what": "London’s variable-length decision trail, with optional rationale and source notes folded only when present.",
        "how_to_use": "Read the decision first; open the fold only when you need the reasoning or source trail behind it.",
    },
    "constraints": {
        "one_line": "These constraints protect the work from sliding back into generic polish after the route choice feels settled.",
        "what": "The non-negotiables the build must obey: product evidence, source honesty, route specificity, and anti-position.",
        "how_to_use": "Use this as the check before designing, presenting, or handing the pack to a builder.",
    },
    "evidence": {
        "one_line": "The source trail separates what London read from what still needs fetching; planned sources are not completed references.",
        "what": "Brain findings, source targets, live assets, and run records split into honest drawers.",
        "how_to_use": "Open the drawer for the claim you need to defend and verify whether it is local, planned, or live.",
    },
    "grader": {
        "one_line": "This panel checks whether the pack is ready to trust without making London grade her own taste.",
        "what": "A source-trail, route-distance, type-range, and pack-completeness check.",
        "how_to_use": "Use this only to spot what needs another pass before handoff; London’s creative direction remains the lead.",
    },
    "handoff": {
        "one_line": "The handoff turns London's route into a buildable brief while keeping internal support artifacts behind details.",
        "what": "A selected-route build brief, session summary, and internal support artifacts for the selected route.",
        "how_to_use": "Read the route brief first; open internal details only when a builder needs the underlying artifacts.",
    },
    "receipts": {
        "one_line": "Run records are the source trail: useful for trust checks, never the creative story the user has to read first.",
        "what": "Local run records and source details emitted by the pack run.",
        "how_to_use": "Open this when you need to inspect mode, source, or local-run details.",
    },
}


def _template_source(template_id: str) -> str:
    """Return a stable public-safe template handle from persona.VOICE_TEMPLATES."""

    return VOICE_TEMPLATES[template_id].id


def _route_match(pack: Mapping[str, Any], routes: Sequence[Mapping[str, Any]]) -> tuple[Mapping[str, Any] | None, str]:
    ref = display_text(pack.get("recommended_route_ref"))
    matched = resolve_route_ref(ref, routes)
    return matched, display_text(matched.get("title")) if matched else ref


def _authored_section_read(pack: Mapping[str, Any] | None, anchor: str) -> str:
    """Return a model-authored section read if the pack explicitly carries one."""

    if not isinstance(pack, Mapping):
        return ""
    keys = (anchor, anchor.replace("-", "_"))
    containers = (
        pack.get("curated_guidance"),
        pack.get("guidance"),
        pack.get("londons_read"),
    )
    for container in containers:
        if not isinstance(container, Mapping):
            continue
        sections = container.get("sections")
        if not isinstance(sections, Mapping):
            sections = container
        for key in keys:
            entry = sections.get(key)
            if isinstance(entry, Mapping):
                for field in ("londons_read", "read", "one_line", "text"):
                    text = display_text(entry.get(field))
                    if text:
                        return text
            else:
                text = display_text(entry)
                if text:
                    return text
    return ""


def _section_heading(
    anchor: str,
    kicker: str,
    title: str,
    summary: str = "",
    *,
    pack: Mapping[str, Any] | None = None,
) -> str:
    guide = _SECTION_GUIDANCE[anchor]
    tooltip = f"{guide['what']} {guide['how_to_use']}".strip()
    summary_html = f"<p>{escape_prose(summary)}</p>" if summary else ""
    authored_read = _authored_section_read(pack, anchor)
    if authored_read:
        guidance_kind = "londons-read"
        guidance_source = _template_source("londons_read")
        guidance_kicker = "London&#x27;s read"
        guidance_copy = authored_read
    else:
        guidance_kind = "reader-guide"
        guidance_source = "static_reader_guide"
        guidance_kicker = "Reader guide"
        guidance_copy = guide["one_line"]
    return f"""
      <div class="section-heading">
        <div class="section-title-row" data-section-intro-source="{escape(_template_source('section_intro'), quote=True)}">
          <div>
            <p class="kicker">{escape(kicker)}</p>
            <h2>{escape(title)}</h2>
          </div>
          <button class="section-help" type="button" aria-label="{escape(tooltip, quote=True)}" title="{escape(tooltip, quote=True)}" data-tooltip-source="{escape(_template_source('tooltip'), quote=True)}" data-guidance-static="true">ⓘ</button>
        </div>
        {summary_html}
        <aside class="section-guidance" data-guidance-kind="{escape(guidance_kind, quote=True)}" data-guidance-source="{escape(guidance_source, quote=True)}" data-guidance-section="{escape(anchor, quote=True)}" data-guidance-static="true">
          <p class="section-guidance-kicker">{guidance_kicker}</p>
          <p>{escape_prose(guidance_copy)}</p>
        </aside>
      </div>"""


def _executive_summary(pack: Mapping[str, Any], routes: Sequence[Mapping[str, Any]]) -> str:
    matched, recommended = _route_match(pack, routes)
    comparisons = _as_mappings(pack.get("route_comparison"))
    matched_id = display_text(matched.get("id")) if isinstance(matched, Mapping) else ""
    matched_comparison = next(
        (
            row
            for row in comparisons
            if display_text(row.get("route_id")) == matched_id
            or display_text(row.get("title")) == recommended
        ),
        {},
    )
    read = _public_handoff_text(pack.get("london_reframe"))
    why = _public_handoff_text(pack.get("recommended_route"))
    if _is_promptish_route_line(read, pack) and not why:
        read = ""
    elif _is_promptish_route_line(read, pack):
        read = _public_handoff_text(
            matched_comparison.get("thesis")
            or (matched.get("rationale") if isinstance(matched, Mapping) else "")
            or read
        )
    has_authored_read = bool(read or why)
    read = read or "No executive read recorded."
    why = why or "No route rationale recorded."
    guidance_kind = "exec-summary" if has_authored_read else "exec-guide"
    guidance_source = _template_source("exec_summary") if has_authored_read else "static_exec_guide"
    guidance_kicker = "London&#x27;s read" if has_authored_read else "Executive guide"
    return f"""
    <section class="guidance-exec" aria-label="Route decision" data-guidance-kind="{escape(guidance_kind, quote=True)}" data-guidance-source="{escape(guidance_source, quote=True)}" data-guidance-static="true">
      <div class="guidance-exec-copy">
        <p class="guidance-kicker">{guidance_kicker}</p>
        <h2>Route decision</h2>
        <p>Use this as the selected path after you have read London's opening take.</p>
      </div>
      <dl class="guidance-exec-facts">
        <div>
          <dt>Ship this route</dt>
          <dd>{escape(recommended or "No route selected")}</dd>
        </div>
        <div>
          <dt>Why it holds</dt>
          <dd>{escape(why)}</dd>
        </div>
      </dl>
    </section>"""


# --- Shared navigation surfaces (TPL-06 / NAV-01..05) ----------------------------
# The dossier is the SECOND consumer of the shared navigation model (the prototype
# is the first). These helpers PORT the proven prototype nav surfaces
# (prototype.py:153-295) into the dossier, renaming the prototype-* classes/ids to
# dossier-* and authoring dossier-appropriate CSS in _style(). The inline JS
# (setDrawer/openPalette/closePalette + ⌘K/Ctrl+K/"/"/Esc/outside-click/select-close
# + ONE IntersectionObserver scroll-spy) is ported into _script(). Every
# interpolated string is escaped (T-04-06).


def _nav_href(link: NavLink) -> str:
    if link.kind in {"route", "section", "route-section"}:
        return "routes"
    return link.id


def _public_nav_label(link: NavLink) -> str:
    if link.id == "receipts":
        return "Audit"
    return link.label


def _public_nav_eyebrow(link: NavLink) -> str:
    if link.kind == "global" and link.eyebrow.lower() == "dossier":
        return ""
    return link.eyebrow




def _render_nav_group(title: str, links: Sequence[NavLink]) -> str:
    rendered_links = "".join(
        (
            f"""
        <a href="#{escape(_nav_href(link), quote=True)}" data-nav-link="{escape(link.id, quote=True)}" data-nav-route="{escape(link.route_id, quote=True)}" data-nav-kind="{escape(link.kind, quote=True)}">
          {f'<span>{escape(eyebrow)}</span>' if (eyebrow := _public_nav_eyebrow(link)) else ''}
          <b>{escape(_public_nav_label(link))}</b>
        </a>"""
        )
        for link in links
    )
    return f"""
      <section class="dossier-nav-group">
        <p>{escape(title)}</p>
        {rendered_links}
      </section>"""


def _render_command_item(link: NavLink) -> str:
    eyebrow = _public_nav_eyebrow(link)
    key = " ".join(part for part in (eyebrow, _public_nav_label(link), link.route_title) if part).lower()
    return f"""
        <a href="#{escape(_nav_href(link), quote=True)}" data-command-item data-nav-link="{escape(link.id, quote=True)}" data-nav-route="{escape(link.route_id, quote=True)}" data-nav-kind="{escape(link.kind, quote=True)}" data-command-key="{escape(key, quote=True)}">
          {f'<span>{escape(eyebrow)}</span>' if eyebrow else ''}
          <b>{escape(_public_nav_label(link))}</b>
        </a>"""


def _render_nav_map(navigation: Navigation) -> str:
    groups = [_render_nav_group("Sections", navigation.primary_sections)]
    for index, route in enumerate(navigation.routes, start=1):
        groups.append(_render_nav_group(f"Route {index:02d}", (route.panel, *route.sections)))
    return "\n".join(groups)


def _render_left_rail(navigation: Navigation) -> str:
    return f"""
    <nav class="dossier-left-rail" aria-label="Dossier section and route map">
      {_render_nav_map(navigation)}
    </nav>"""


def _render_mobile_drawer(navigation: Navigation) -> str:
    return f"""
    <div class="dossier-mobile-drawer" id="dossier-mobile-drawer" data-mobile-drawer hidden>
      <button class="drawer-close" type="button" data-mobile-close aria-label="Close navigation">Close</button>
      <nav aria-label="Mobile dossier section and route map">
        {_render_nav_map(navigation)}
      </nav>
    </div>"""


def _render_command_palette(navigation: Navigation) -> str:
    items = "".join(_render_command_item(link) for link in navigation.all_links)
    return f"""
    <div class="dossier-command-palette" id="dossier-command-palette" data-command-palette role="dialog" aria-modal="true" aria-label="Dossier command palette" hidden>
      <div class="dossier-command-panel">
        <div class="dossier-command-search">
          <input id="dossier-command-input" data-command-search type="search" autocomplete="off" placeholder="Jump to a route or section…">
          <button type="button" data-command-close>Close</button>
        </div>
        <div class="dossier-command-list" data-command-list>{items}</div>
        <p class="dossier-command-empty" data-command-empty hidden>No matches. Clear the search to see everything.</p>
      </div>
    </div>"""


def _render_route_switcher(navigation: Navigation) -> str:
    # The shared route switcher (NAV-03). Each tab carries the shared-model nav
    # parity attrs (data-nav-route-tab / data-nav-link, role=tab, aria-selected) AND
    # the dossier's existing data-route-button so it ALSO drives the in-page route
    # panel show/hide via selectRoute() (the dossier shows one route panel at a time).
    tabs = "".join(
        f"""
        <button type="button" class="dossier-route-tab" role="tab" aria-selected="{str(route.id == navigation.current_route_id).lower()}" data-route-button="{escape(route.id, quote=True)}" data-nav-route-tab="{escape(route.id, quote=True)}">
          <span>Route {index:02d}</span>
          <b>{escape(route.title)}</b>
        </button>"""
        for index, route in enumerate(navigation.routes, start=1)
    )
    return f"""
    <nav class="dossier-route-switcher-nav" aria-label="Route switcher">
      <div class="dossier-route-switcher" role="tablist" aria-label="Visual routes">{tabs}</div>
    </nav>"""


def _dossier_header(pack: Mapping[str, Any], routes: Sequence[Mapping[str, Any]]) -> str:
    # The light overview band (TPL-01 / 04-UI-SPEC §Section Order Contract): the
    # essential overview facts relocate to a supporting band directly UNDER the
    # dark command-center console (see _command_center + render_dossier). It is
    # NOT a nav section — no `id="overview"`, no `data-nav-section` — so the
    # standalone overview anchor is dropped and the visual-first moodboard leads.
    # The voiced exec-summary is Phase 5; this stays a neutral facts band.
    next_step = _as_mappings(pack.get("next_steps"))[0] if _as_mappings(pack.get("next_steps")) else {}
    route_names = ", ".join(display_text(route.get("title"), fallback=f"Route {index}") for index, route in enumerate(routes, start=1))
    category = _clip_detail(display_text(pack.get("category_assumption"), fallback="Not recorded"), 190)
    void = _clip_detail(display_text(pack.get("aesthetic_void"), fallback="Not recorded"), 190)
    anti = _clip_detail(display_text(pack.get("anti_position"), fallback="Not recorded"), 170)
    next_label = display_text(next_step.get("label"), fallback="Compare routes")
    next_description = _clip_detail(display_text(next_step.get("description"), fallback="Use the route matrix before building."), 150)
    return f"""
    <section class="dossier-header" aria-label="Brief overview">
      <div class="dossier-header-copy">
        <p class="kicker">Brief context</p>
        <h2>What London is solving</h2>
        <ul class="brief-context-list">
          <li><b>Assumption</b><span>{escape(category)}</span></li>
          <li><b>Void</b><span>{escape(void)}</span></li>
          <li><b>Not this</b><span>{escape(anti)}</span></li>
        </ul>
      </div>
      <aside class="fact-panel" aria-label="Overview facts">
        <dl>
          <div><dt>Routes</dt><dd>{escape(route_names)}</dd></div>
          <div><dt>Primary Next Action</dt><dd>{escape(next_label)}: {escape(next_description)}</dd></div>
        </dl>
      </aside>
    </section>"""


def _confidence_word(score: Any) -> str:
    # RENDER-06 re-source: confidence is bucketed from the REAL grader composite
    # roll-up (pack["grader"]["composite"]["score"]), a 0–100 weighted number, NOT
    # the dead status=='approved' ratio (the deleted fossil floored to 0/N because
    # no real run emits a status). The (approved, total) signature is GONE. The
    # honest-absence value "n/a" (string) passes straight through — telemetry not
    # captured means the ENGINE grade is unavailable, never a fabricated word. A
    # real captured number buckets High/Developing/Early; nothing is invented.
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        return "n/a"
    if score >= 70:
        return "High"
    if score >= 40:
        return "Developing"
    return "Early"


def _count_word(count: int) -> str:
    words = {
        0: "No",
        1: "One",
        2: "Two",
        3: "Three",
        4: "Four",
        5: "Five",
        6: "Six",
        7: "Seven",
        8: "Eight",
        9: "Nine",
        10: "Ten",
    }
    return words.get(count, str(count))


def _live_visual_count(pack: Mapping[str, Any], routes: Sequence[Mapping[str, Any]]) -> int:
    route_ids: set[str] = set()
    for route in routes:
        route_id = display_text(route.get("id") or route.get("title"))
        for asset in _as_mappings(route.get("assets")):
            if asset.get("live_artifact") is True or display_text(asset.get("generation_status")) == "generated_live":
                route_ids.add(route_id or display_text(asset.get("src")) or display_text(asset.get("id")))
    for receipt in _as_mappings(pack.get("receipts")):
        if display_text(receipt.get("kind")) == "image-generation" and display_text(receipt.get("status")) == "generated_live":
            route_ids.add(display_text(receipt.get("route_id")) or display_text(receipt.get("asset_src")) or display_text(receipt.get("receipt_id")))
    return len({item for item in route_ids if item})


def _command_center(pack: Mapping[str, Any], routes: Sequence[Mapping[str, Any]]) -> str:
    # The command center is the first-read workbench header. It leads with London's
    # route read and keeps operational run metadata in a collapsed audit detail.
    title = clean_title(pack, fallback="London Pack")
    convo = _as_mappings(pack.get("conversation"))
    total = len(convo)
    grader = pack.get("grader") if isinstance(pack.get("grader"), Mapping) else {}
    composite = grader.get("composite") if isinstance(grader.get("composite"), Mapping) else {}
    composite_score = composite.get("score")
    if composite.get("telemetry_available") is False:
        confidence = "n/a"
    else:
        confidence = _confidence_word(composite_score)
    ref = display_text(pack.get("recommended_route_ref"))
    matched = resolve_route_ref(ref, routes)
    recommended = display_text(matched.get("title")) if matched else ref
    comparisons = _as_mappings(pack.get("route_comparison"))
    matched_id = display_text(matched.get("id")) if matched else ""
    matched_comparison = next(
        (
            row
            for row in comparisons
            if display_text(row.get("route_id")) == matched_id
            or display_text(row.get("title")) == recommended
        ),
        {},
    )
    accent_source = matched or (routes[0] if routes else {})
    accent_palette = normalize_palette(accent_source.get("palette")) if accent_source else []
    accent = display_text(accent_palette[0]["hex"]) if accent_palette else "#1A1A1A"
    reframe = _public_handoff_text(pack.get("london_reframe") or pack.get("summary") or clean_brief_text(pack))
    if _is_promptish_route_line(reframe, pack):
        reframe = _public_handoff_text(
            matched_comparison.get("thesis")
            or (matched.get("rationale") if isinstance(matched, Mapping) else "")
            or reframe
        )
    recommendation = display_text(pack.get("recommended_route"))
    recommendation_html = (
        f'<p class="command-center-recommendation">{escape(recommendation)}</p>'
        if recommendation
        else ""
    )
    live_visuals = _live_visual_count(pack, routes)
    decision_fact = f"{_count_word(total)} design {'decision' if total == 1 else 'decisions'} shaped the pack."
    score_fact = "No readiness check captured." if confidence == "n/a" else f"Readiness check reads {confidence.lower()}."
    route_count_fact = (
        f"London turned your brief into {_count_word(len(routes)).lower()} {'route' if len(routes) == 1 else 'routes'} you can compare."
        if routes
        else "London turned your brief into a route to inspect."
    )
    route_recommendation_fact = (
        f"Start with {recommended}, then use the alternates to pressure-test the direction."
        if recommended
        else "Start with the recommended route before comparing alternatives."
    )
    return f"""
    <section class="command-center" aria-label="Pack command center" style="--accent:{escape(accent, quote=True)}">
      <div class="command-center-head">
        <p class="command-center-kicker">London&#x27;s read</p>
        <h1 class="display-title command-center-title">{escape(title)}</h1>
        {_scan_read(reframe)}
        <p class="command-center-route"><span>Current route</span><b>{escape(recommended or "No route selected")}</b></p>
        {recommendation_html}
        <div class="command-center-next">
          <a class="command-center-link" href="#moodboard">Inspect moodboard</a>
          <a class="command-center-link" href="#routes">Open route</a>
        </div>
      </div>
      <div class="command-center-meta">
        <div class="command-center-trust" aria-label="How to read this">
          <h2>How to read this</h2>
          <ul class="trust-list">
            <li>{escape(route_count_fact)}</li>
            <li>{escape(route_recommendation_fact)}</li>
            <li>The route visuals, type notes, and handoff are grouped so you can choose and build.</li>
            <li>Open the audit note only when you need the source trail.</li>
          </ul>
          <details class="command-center-details" data-persist="command-center-run">
            <summary>Audit note</summary>
            <dl class="command-center-stats">
              <div class="command-stat">
                <dt>Source trail</dt>
                <dd>Available in the audit files.</dd>
              </div>
              <div class="command-stat">
                <dt>Visuals</dt>
                <dd>{escape(f'{_count_word(live_visuals)} route visual source records are available.' if live_visuals else 'Route visual source state is available in audit.')}</dd>
              </div>
              <div class="command-stat">
                <dt>Decision path</dt>
                <dd>{escape(decision_fact)}</dd>
              </div>
              <div class="command-stat">
                <dt>Readiness check</dt>
                <dd>{escape(score_fact)}</dd>
              </div>
            </dl>
          </details>
        </div>
        <div class="command-center-actions">
          <button class="command-open" type="button" data-command-open aria-keyshortcuts="Meta+K Control+K" aria-controls="dossier-command-palette" aria-label="Open command palette">⌘K</button>
        </div>
      </div>
    </section>"""


def _recommendation_panel(pack: Mapping[str, Any], routes: Sequence[Mapping[str, Any]]) -> str:
    # RENDER-01 / UI-SPEC Surface 1: London's recommendation, rendered AS GIVEN with an
    # HONEST empty floor. The route is resolved by the machine reference
    # recommended_route_ref (id OR title equality — read AS GIVEN, NO re-rank, NO
    # `title == prose` match). The verbatim prose (recommended_route) is rendered
    # COMPLETE-IN-DOM with NO `max_length` and NO ellipsis — anti-flatten core. The
    # rendering is bimodal by prose length, but BOTH non-empty branches emit the full
    # string; only a persisted `<details>` (reusing the existing data-persist handler,
    # NO new JS) folds the long case. The empty floor (offline/Fake: recommended_route
    # = "") emits the title + the ref-anchored badge with NO prose region and NO
    # fabricated prose — absence renders as absence (same principle as the grader n/a).
    # Accent reads from the resolved route's OWN palette[0].hex (carried pattern,
    # render.py:258-260), never derived. Escape discipline (T-05.1-01): every
    # interpolated string passes escape() (text) / escape(..., quote=True) (attribute).
    matched, resolved_title = _route_match(pack, routes)
    prose = pack.get("recommended_route") or ""  # read AS GIVEN — NO fallback that invents prose
    if not isinstance(prose, str):
        prose = display_text(prose)
    accent_source = matched or (routes[0] if routes else {})
    accent_palette = normalize_palette(accent_source.get("palette")) if accent_source else []
    accent = display_text(accent_palette[0]["hex"]) if accent_palette else "#1A1A1A"

    badge = (
        f'<p class="recommendation-badge">Recommended &rarr; '
        f'<b>{escape(resolved_title)}</b></p>'
    )

    # Bimodal verbatim rendering (UI-SPEC §"Bimodal rendering rule"). Every non-empty
    # branch emits the COMPLETE verbatim prose; the length only chooses the chrome.
    if not prose.strip():
        prose_region = ""  # honest absence — NO prose region, NO "No recommendation"
    elif len(prose) <= 40:
        prose_region = f'<p class="recommendation-prose recommendation-prose--short">{escape(prose)}</p>'
    elif len(prose) <= 280:
        prose_region = f'<p class="recommendation-prose">{escape(prose)}</p>'
    else:
        # Long case: verbatim + complete-in-DOM, folded into the EXISTING persisted
        # <details data-persist=...> mechanic (render.py handler) — NO new JS.
        prose_region = (
            '<details class="recommendation-fold" data-persist="recommendation">'
            '<summary>Read London&#x27;s full case</summary>'
            f'<p class="recommendation-prose">{escape(prose)}</p>'
            "</details>"
        )

    return f"""
    <section class="recommendation-panel" aria-label="London's recommendation" style="border-left:3px solid var(--accent); --accent:{escape(accent, quote=True)}">
      <p class="recommendation-kicker">London&#x27;s recommendation</p>
      {badge}
      {prose_region}
    </section>"""


def _debug_source_ref(finding: Mapping[str, Any]) -> str:
    debug = finding.get("debug") if isinstance(finding.get("debug"), Mapping) else {}
    source_ref = display_text(debug.get("source_ref") or finding.get("source_ref"))
    if not source_ref:
        return ""
    return (
        '<details class="source-ref-detail is-receipt-detail">'
        '<summary>Source reference</summary>'
        f'<code>{escape(source_ref)}</code>'
        "</details>"
    )


def _finding_item(finding: Mapping[str, Any]) -> str:
    terms = "".join(
        f"<span>{escape(term)}</span>"
        for term in _as_strings(finding.get("matched_terms"), fallback=())[:5]
    )
    chips = f'<div class="mini-tags">{terms}</div>' if terms else ""
    return f"""
      <li class="brain-finding">
        <div class="primary-evidence-label">
          <b>{escape(display_text(finding.get("insight_title") or finding.get("title")))}</b>
          <em>{escape(display_text(finding.get("evidence_class"), fallback="London Brain Finding"))}</em>
          <span>{escape(display_text(finding.get("why_london_used_this") or finding.get("body")))}</span>
          {chips}
        </div>
        {_debug_source_ref(finding)}
      </li>"""


def _evidence_class_summary(entry: Mapping[str, Any]) -> str:
    classes = entry.get("evidence_classes") if isinstance(entry.get("evidence_classes"), Mapping) else {}
    brain = int(classes.get("london_brain_findings") or 0)
    sources = int(classes.get("source_targets") or 0)
    live = int(classes.get("live_artifacts") or 0)
    return f"{brain} London Brain Findings + {sources} Source Targets + {live} Live Assets"


def _conversation(pack: Mapping[str, Any]) -> str:
    # RENDER-02 (cardinality axis) + RENDER-02b (field-presence axis). The conversation
    # renders London's N as-authored decisions AS GIVEN: count = len(conversation), in
    # document order, never padded / sliced / index-mapped (cardinality is honest by
    # construction — _as_mappings returns exactly the list given). Each card always shows
    # the model's OWN gate label + decision (both schema-required, minLength:1); every
    # optional field renders ONLY when non-empty (honest absence — no empty container, no
    # null/None/N/A/— placeholder, no fabricated default). No GATE_NAMES lookup, no
    # template-bank _gate_question/_gate_critique text. Read AS GIVEN. (PATTERNS.md §2)
    entries = _as_mappings(pack.get("conversation"))
    rendered = []
    for index, entry in enumerate(entries):
        gate = display_text(entry.get("gate"))  # required (schema:294) — NO fabricating fallback
        decision = _public_handoff_text(entry.get("decision"))  # required (schema:295)

        # First-read reasoning: London's own answer/rationale/critique/question are visible
        # on the card so Tom can grade the decision without opening proof machinery. Run
        # status, evidence, sources, and receipts stay in collapsed provenance details.
        reasoning_regions = []
        for field, label in (
            ("question", "Question"),
            ("answer", "Answer"),
            ("rationale", "Rationale"),
            ("critique", "London push"),
        ):
            value = _public_handoff_text(entry.get(field))
            if value:
                reasoning_regions.append(
                    f'<div class="decision-read"><b>{escape(label)}</b>'
                    f'<p>{escape(value)}</p></div>'
                )

        fold_regions = []
        status = display_text(entry.get("status"))
        if status:
            fold_regions.append(
                f'<div class="decision-region"><b>Status</b><p>{escape(status)}</p></div>'
            )

        # Evidence sub-block — guarded so it NEVER forces an empty fold when the entry
        # carries no evidence (read AS GIVEN; absence renders as absence).
        queries = "".join(
            f"<li><b>{escape(display_text(query.get('intent')))}</b><span>{escape(display_text(query.get('query')))}</span></li>"
            for query in _as_mappings(entry.get("brain_queries"))
        )
        findings = "".join(_finding_item(finding) for finding in _as_mappings(entry.get("brain_findings")))
        sources = "".join(
            f"""<li class="source-target"><b>{escape(display_text(source.get('title')))}</b>
            <em>{escape(display_text(source.get('evidence_class'), fallback='Source Target'))} / {escape(display_text(source.get('status'), fallback='planned-reference'))}</em>
            <span>{escape(_public_source_target_note(source.get('why_london_used_this')))}</span>
            <small>{escape(display_text(source.get('source_id')))}</small></li>"""
            for source in _as_mappings(entry.get("sources"))
        )
        receipts = "".join(
            f"<li><b>{escape(display_text(receipt.get('kind')))}</b><span>{escape(display_text(receipt.get('receipt_id')))}</span></li>"
            for receipt in _as_mappings(entry.get("receipts"))
        )
        if queries or findings or sources or receipts:
            fold_regions.append(
                f"""<div class="decision-region decision-evidence">
                  <b>{escape(_evidence_class_summary(entry))}</b>
                  <div class="evidence-columns">
                    <div><h4>Brain queries</h4><ul>{queries}</ul></div>
                    <div><h4>London Brain Findings</h4><ul class="primary-evidence">{findings}</ul></div>
                    <div><h4>Source Targets</h4><ul>{sources}</ul></div>
                    <div><h4>Run records</h4><ul>{receipts}</ul></div>
                  </div>
                </div>"""
            )

        if fold_regions:
            # Persisted <details> keyed on the loop index (int, not raw entry data — T-05.1-03).
            # Reuses the existing data-persist handler verbatim (render.py:1421) — NO new JS.
            reasoning = (
                f'<details class="decision-fold" data-persist="decision-{index}">'
                "<summary>Decision source trail</summary>"
                f'{"".join(fold_regions)}'
                "</details>"
            )
        else:
            reasoning = ""  # all optionals + evidence empty → NO <details> at all

        rendered.append(
            f"""
            <article class="decision-card" data-jump-target data-filter-item>
              <p class="kicker">{escape(gate)}</p>
              <p class="decision-body">{escape(decision)}</p>
              {f'<div class="decision-public-reasoning">{"".join(reasoning_regions)}</div>' if reasoning_regions else ''}
              {reasoning}
            </article>"""
        )
    return f"""
    <section class="dossier-section" id="conversation" data-nav-section data-nav-label="Conversation" data-jump-target>
      {_section_heading("conversation", "Decision trail", "The conversation", "Each card keeps London's own gate label and the decision he made; his reasoning folds away under each.", pack=pack)}
      <div class="decision-list">{''.join(rendered)}</div>
    </section>"""


_PUBLIC_IMAGE_COPY_BLOCKLIST = (
    "asset_sha256",
    "debug",
    "fallback",
    "fixture",
    "generated_live",
    "manual_prompt",
    "manual-prompt",
    "provider",
    "provider-generated",
    "receipt",
    "schema",
    "sha256",
)


def _public_image_alt(value: Any, *, fallback: str) -> str:
    text = display_text(value)
    lowered = text.lower()
    if not text or any(marker in lowered for marker in _PUBLIC_IMAGE_COPY_BLOCKLIST):
        text = fallback
    text = re.sub(r"\bconcept image\b", "product view", text, flags=re.I)
    text = re.sub(r"\bconcept\b", "product view", text, flags=re.I)
    text = re.sub(r"\bgenerated\b", "", text, flags=re.I)
    text = re.sub(r"\bproduct view\s+product view\b", "product view", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" -:") or fallback
    return _public_handoff_text(text)


def _visual_slot(tile: Mapping[str, Any], *, lightbox: bool = True) -> str:
    """Render exactly one of the five honest visual states (D-04/D-05/D-06, HON-03).

    The state is chosen EXPLICITLY from ``tile["kind"]`` — never from ``asset_src``
    presence — so a deterministic SVG (which is wired into ``asset_src`` even for a
    keyless ``visual-direction-board`` or legacy ``manual-prompt-card`` hero) NEVER
    renders as a routine generated image.

    State 1 (``generated-concept-image``): real provider-backed ``<img>`` + honest
    caption. The ONLY state that renders ``asset_src`` as a concept image.
    State 2 (``fixture-system-sketch``): SVG labeled "system sketch" — reachable
    ONLY under ``--fixture``.
    State 3 (``visual-direction-board``): local board labeled as direction, not generated art.
    State 4 (``generation-unavailable``): genuine provider failure — honest copy + prompt.
    State 5 (``manual-prompt-card``): legacy prompt card labeled as a prompt, not a mockup.
    Fall-through defaults to State 5 so a deterministic SVG never escapes as concept art.
    """

    kind = display_text(tile.get("kind"))
    title = display_text(tile.get("title"), fallback="Route concept")
    caption = display_text(tile.get("caption"))
    asset_src = safe_href(tile.get("asset_src"))
    asset_alt = _public_image_alt(tile.get("asset_alt"), fallback=f"{title} product view")
    lightbox_title = _public_image_alt(title, fallback=f"{title} product view")
    prompt = display_text(tile.get("prompt")) or caption
    prompt_summary = _clip_detail(prompt, 150)
    copy_label = display_text(tile.get("copy_label"), fallback="Copy image prompt")
    caption_html = f'<figcaption class="visual-caption">{escape(caption)}</figcaption>' if caption else ""
    honesty_note = display_text(tile.get("honesty_note"))
    honesty_html = f'<p class="visual-honesty-note">{escape(honesty_note)}</p>' if honesty_note else ""
    # HERO-03: the artifact TYPE label is descriptive metadata (what is being designed),
    # strictly ORTHOGONAL to the visual STATE. It is a SEPARATE line from the state
    # `visual-label`, and it NEVER influences `data-visual-state` (keyed only on `kind`).
    artifact_label = display_text(tile.get("artifact_label"))
    type_label_html = f'<p class="visual-type-label">{escape(artifact_label)}</p>' if artifact_label else ""

    # State 1 — Generated (live): the normal output. A real <img> is shown ONLY when the
    # model actually generated a provider-backed concept image.
    if kind == "generated-concept-image" and asset_src:
        trigger = (
            f"""<button class="peek-trigger" type="button" data-lightbox-src="{escape(asset_src, quote=True)}" data-lightbox-title="{escape(lightbox_title, quote=True)}">
              <img src="{escape(asset_src, quote=True)}" alt="{escape(asset_alt, quote=True)}">
            </button>"""
            if lightbox
            else f'<img src="{escape(asset_src, quote=True)}" alt="{escape(asset_alt, quote=True)}">'
        )
        return f"""
          <figure class="visual-slot visual-slot--generated" data-visual-state="generated">
            {type_label_html}
            {trigger}
            {caption_html}
          </figure>"""

    # State 2 — Fixture system sketch: explicit --fixture only. The SVG IS shown, but
    # labeled honestly so it can never be mistaken for a provider-generated image.
    if kind == "fixture-system-sketch" and asset_src:
        trigger = (
            f"""<button class="peek-trigger" type="button" data-lightbox-src="{escape(asset_src, quote=True)}" data-lightbox-title="{escape(lightbox_title, quote=True)}">
              <img src="{escape(asset_src, quote=True)}" alt="{escape(asset_alt, quote=True)}">
            </button>"""
            if lightbox
            else f'<img src="{escape(asset_src, quote=True)}" alt="{escape(asset_alt, quote=True)}">'
        )
        return f"""
          <figure class="visual-slot visual-slot--system-sketch" data-visual-state="system-sketch">
            {type_label_html}
            <p class="visual-label">System sketch</p>
            {trigger}
            <figcaption class="visual-caption">Internal system sketch for this route.</figcaption>
          </figure>"""

    # State 3 — Visual direction board: the keyless/local floor. It is visible and useful
    # but is not provider-generated concept art.
    if kind == "visual-direction-board" and asset_src:
        summary = caption or title
        return f"""
          <figure class="visual-slot visual-slot--direction-summary" data-visual-state="visual-direction-board">
            {type_label_html}
            <div class="visual-summary-panel">
              <p class="visual-label">Visual direction</p>
              <h4>{escape(title)}</h4>
              {f'<p>{escape(summary)}</p>' if summary else ''}
              {honesty_html}
            </div>
            <details class="prompt-detail is-receipt-detail">
              <summary>Source details</summary>
              <p>The local direction board is retained as an audit artifact; the public first layer uses London route copy so scaffold text does not become the product visual.</p>
              <p><a href="{escape(asset_src, quote=True)}">Open local visual source</a></p>
            </details>
          </figure>"""

    # State 4 — Honest unavailable: a genuine provider failure for this run.
    if kind == "generation-unavailable":
        summary = caption or title or "London kept the visual direction available without claiming generated concept art."
        return f"""
          <figure class="visual-slot visual-slot--generation-unavailable prompt-card" data-visual-state="generation-unavailable">
            {type_label_html}
            <p class="visual-label">Image direction unavailable</p>
            <p class="visual-copy">{escape(summary)}</p>
            <details class="prompt-detail is-receipt-detail"><summary>Prompt details</summary><pre class="prompt-text">{escape(prompt)}</pre><button type="button" class="copy-button" data-copy="{escape(prompt, quote=True)}">{escape(copy_label)}</button></details>
            {caption_html}
          </figure>"""

    # State 5 (fall-through) — Manual prompt card (legacy/manual lane): no ready generator.
    # Labeled a prompt, never dressed as a mockup. Fall-through for any unrecognized kind so
    # a deterministic SVG never escapes as routine concept art.
    summary = caption or title or prompt_summary
    return f"""
      <figure class="visual-slot visual-slot--manual-prompt-card prompt-card" data-visual-state="manual-prompt-card">
        {type_label_html}
        <p class="visual-label">Image direction</p>
        <p class="visual-copy">{escape(summary)}</p>
        <details class="prompt-detail is-receipt-detail"><summary>Prompt details</summary><pre class="prompt-text">{escape(prompt)}</pre><button type="button" class="copy-button" data-copy="{escape(prompt, quote=True)}">{escape(copy_label)}</button></details>
        {caption_html}
      </figure>"""


def _route_dossiers(
    pack: Mapping[str, Any],
    routes: Sequence[Mapping[str, Any]],
    comparisons: Sequence[Mapping[str, Any]],
    tile_groups: Sequence[Mapping[str, Any]],
    navigation: Navigation,
) -> str:
    comparison_by_route = {display_text(row.get("route_id")): row for row in comparisons}
    hero_by_route = {
        display_text(group.get("route_id")): (_as_mappings(group.get("tiles"))[0] if _as_mappings(group.get("tiles")) else {})
        for group in tile_groups
    }
    route_panels = []
    for index, route in enumerate(routes):
        route_id = _route_id(route, f"route-{index + 1}")
        palette = normalize_palette(route.get("palette"))
        # Accent is the route's own dominant palette colour (UI-SPEC §Color). The
        # deterministic parity oracle can hand two routes byte-identical palettes, which
        # would collapse the "two routes read with different accents" mechanic; rotate the
        # pick by route position so each route still reads distinctly from its OWN palette
        # (never re-derived model data — same palette list, different reserved slot).
        accent = display_text(palette[index % len(palette)]["hex"]) if palette else "#1A1A1A"
        cmp = comparison_by_route.get(route_id, {})
        hero_tile = hero_by_route.get(route_id, {})
        tags = "".join(f"<span>{escape(tag)}</span>" for tag in _as_strings(route.get("tags"), fallback=("route",)))
        specimen_direction = display_text(route.get("type") or route.get("typography"))
        route_title = display_text(route.get("title"), fallback=f"Route {index + 1}")
        public_thesis = _public_route_thesis(route, pack, fallback=route_title)
        specimen_sample = _public_route_specimen(route, pack, fallback=route_title)
        font_option = _route_font_option(pack, route_id) or {
            "tier": "safe_local",
            "fallback_stack": "var(--serif)",
            "headline_font": "Dossier serif",
        }
        preview = resolve_font_preview(font_option)
        type_family, specimen_direction, type_rationale, type_best_use = _font_type_read(route, font_option, preview)
        steal = _public_handoff_text(cmp.get("steal") or route.get("steal"))
        do_not_copy = _public_handoff_text(cmp.get("do_not_copy") or route.get("do_not_copy"))
        route_rationale = _public_handoff_text(route.get("rationale"))
        hidden = "" if index == 0 else " hidden"
        route_panels.append(
            f"""
            <article class="route-dossier" data-route-panel="{escape(route_id, quote=True)}" style="--accent:{escape(accent, quote=True)}"{hidden}>
              <header class="route-dossier-head">
                <p class="kicker">Selected Route</p>
                <h3>{escape(route_title)}</h3>
                <p class="route-thesis">{escape(public_thesis)}</p>
              </header>
              <div class="dossier-workspace">
                <div class="dossier-preview-column">
                  {_visual_slot(hero_tile)}
                  <div class="type-specimen">
                    <p class="kicker">Type specimen</p>
                    <h4>{escape(type_family)}</h4>
                    <p class="route-specimen" style="font-family:{escape(preview.css_stack, quote=True)}" data-font-preview-status="{escape(preview.status, quote=True)}" data-font-preview-family="{escape(preview.rendered_family, quote=True)}">{escape(specimen_sample)}</p>
                    {_type_read_paragraphs(type_rationale, type_best_use)}
                    {_render_type_roles(_public_handoff_text(specimen_direction), wrap=True)}
                    {_font_proof_details(preview)}
                  </div>
                </div>
                <div class="dossier-meta-rail">
                  <div class="rail-block palette-rail">
                    <p class="kicker">Palette rail</p>
                    <div class="swatch-strip">{_swatches(palette)}</div>
                  </div>
                  <div class="rail-block route-tags-block">
                    <p class="kicker">Route tags</p>
                    <div class="tag-line">{tags}</div>
                  </div>
                  <div class="rail-block callout callout--steal">
                    <p class="kicker">Steal this principle</p>
                    <p>{escape(steal)}</p>
                  </div>
                  <div class="rail-block callout callout--avoid">
                    <p class="kicker">Do not copy</p>
                    <p>{escape(do_not_copy)}</p>
                  </div>
                  <div class="rail-block rationale-block">
                    <p class="kicker">Brain rationale</p>
                    <p>{escape(route_rationale)}</p>
                  </div>
                </div>
              </div>
            </article>"""
        )
    return f"""
    <section class="dossier-section route-switcher" id="routes" data-nav-section data-nav-label="Routes" data-jump-target>
      {_section_heading("routes", "Route Switcher", "Where The Pack Can Go", "Each route is a full dossier — a real preview, a type specimen, its own palette, what to steal, what not to copy, and London's rationale. No two routes read the same.", pack=pack)}
      {_render_route_switcher(navigation)}
      <div class="route-dossier-stack">{''.join(route_panels)}</div>
    </section>"""


def _public_route_thesis(route: Mapping[str, Any], pack: Mapping[str, Any], *, fallback: str) -> str:
    for value in (
        route.get("headline"),
        route.get("thesis"),
        route.get("visual_read"),
        route.get("visualRead"),
        route.get("rationale"),
        route.get("subhead"),
    ):
        text = display_text(value)
        if text and not _is_promptish_route_line(text, pack):
            return _public_handoff_text(text)
    sections = _as_mappings(route.get("sections"))
    for section in sections:
        text = display_text(section.get("body") or section.get("title"))
        if text and not _is_promptish_route_line(text, pack):
            return _public_handoff_text(text)
    return fallback


def _public_route_specimen(route: Mapping[str, Any], pack: Mapping[str, Any], *, fallback: str) -> str:
    for value in (
        route.get("title"),
        route.get("type"),
        route.get("typography"),
        route.get("headline"),
    ):
        text = display_text(value, fallback=fallback)
        if text and not _is_promptish_route_line(text, pack):
            return _public_handoff_text(text)
    return fallback


def _is_promptish_route_line(value: Any, pack: Mapping[str, Any]) -> bool:
    text = display_text(value)
    if not text:
        return False
    lowered = " ".join(text.lower().split())
    brief_title = display_text(pack.get("title") or (pack.get("brief") if isinstance(pack.get("brief"), str) else "")).lower()
    brief_title = re.sub(r"[^a-z0-9]+", " ", brief_title).strip()
    normalized = re.sub(r"[^a-z0-9]+", " ", lowered).strip()
    promptish_start = normalized.startswith(("make ", "turn "))
    briefish = "product brief" in normalized or (brief_title and brief_title in normalized)
    harness_tail = "answer the first real decision" in normalized or "into a route people can compare" in normalized
    return promptish_start and (briefish or harness_tail)


def _comparison(pack: Mapping[str, Any]) -> str:
    cards = []
    for row in _as_mappings(pack.get("route_comparison")):
        route_id = display_text(row.get("route_id"))
        title = display_text(row.get("title"))
        thesis = _public_handoff_text(row.get("thesis"))
        best_for = _public_handoff_text(row.get("best_for"))
        visual_world = _public_handoff_text(row.get("visual_world"))
        type_direction = _public_handoff_text(row.get("type"))
        palette_logic = _public_handoff_text(row.get("palette_logic"))
        steal = _public_handoff_text(row.get("steal"))
        do_not_copy = _public_handoff_text(row.get("do_not_copy"))
        first_build_move = _public_handoff_text(row.get("first_build_move"))
        risk = _public_handoff_text(row.get("risk"))
        route_attr = f' data-nav-route="{escape(route_id)}"' if route_id else ""
        route_cta = (
            f'<a class="comparison-inspect-link" href="#routes" data-nav-link="comparison-{escape(route_id)}"'
            f'{route_attr} data-nav-kind="route">Inspect route</a>'
            if route_id
            else '<a class="comparison-inspect-link" href="#routes">Inspect routes</a>'
        )
        cards.append(
            f"""
            <article class="comparison-card" data-filter-item>
              <div class="comparison-card-head">
                <p class="comparison-card-kicker">Route choice</p>
                <h3>{escape(title)}</h3>
              </div>
              <p class="comparison-thesis">{escape(thesis)}</p>
              <dl class="comparison-priority-list">
                <div><dt>Best for</dt><dd>{escape(best_for)}</dd></div>
                <div><dt>Visual cue</dt><dd>{escape(visual_world)}</dd></div>
                <div><dt>Type cue</dt><dd>{escape(type_direction)}</dd></div>
                <div><dt>Risk</dt><dd>{escape(risk)}</dd></div>
              </dl>
              <div class="comparison-card-actions">
                {route_cta}
                <details class="comparison-detail">
                  <summary>Build details</summary>
                  <dl>
                    <div><dt>Palette logic</dt><dd>{escape(palette_logic)}</dd></div>
                    <div><dt>Steal</dt><dd>{escape(steal)}</dd></div>
                    <div><dt>Do not copy</dt><dd>{escape(do_not_copy)}</dd></div>
                    <div><dt>First build move</dt><dd>{escape(first_build_move)}</dd></div>
                  </dl>
                </details>
              </div>
            </article>"""
        )
    return f"""
    <section class="dossier-section" id="comparison" data-nav-section data-nav-label="Comparison" data-jump-target>
      {_section_heading("comparison", "Route Decision Comparison", "Tradeoffs Before Taste", pack=pack)}
      <div class="comparison-cards">{''.join(cards)}</div>
    </section>"""


def _public_moodboard_copy(value: Any) -> str:
    text = display_text(value)
    if not text:
        return ""
    lowered = text.lower()
    blocked = (
        "actual font loaded",
        "asset_sha256",
        "copy the prompt",
        "fallback",
        "fixture",
        "generated_live",
        "image generation was disabled",
        "local_fallback",
        "manual prompt",
        "manual-prompt",
        "provider",
        "public proof",
        "receipt",
        "requested:",
        "sha256",
    )
    if any(marker in lowered for marker in blocked):
        return ""
    return _public_handoff_text(text)


def _public_constraint_tag(value: Any) -> str:
    text = display_text(value)
    if not text:
        return ""
    translations = {
        "object proof": "product cue",
        "proof moment": "product cue",
        "visual proof": "visual cue",
    }
    return translations.get(text.lower(), _public_handoff_text(text))


def _mood_tile(tile: Mapping[str, Any], *, is_primary: bool = False) -> str:
    """One route-board panel. The HERO tile (span=hero) routes its visual through the shared
    EXPLICIT 4-state ``_visual_slot`` so a deterministic SVG never escapes as routine
    concept art; supporting tiles render their swatches / specimen / annotation."""

    span = display_text(tile.get("span"), fallback="small")
    kind = display_text(tile.get("kind"))
    colors = normalize_palette(tile.get("colors"))
    swatches = (
        f"""<details class="mood-tile-audit">
            <summary>Color notes</summary>
            <div class="swatch-strip mini">{_swatches(colors)}</div>
          </details>"""
        if colors
        else ""
    )
    annotation = _public_moodboard_copy(tile.get("annotation"))
    tension = tile.get("tension_pair") if isinstance(tile.get("tension_pair"), Mapping) else {}
    constraints = "".join(
        f"<span>{escape(tag)}</span>"
        for tag in (_public_constraint_tag(item) for item in _as_strings(tile.get("constraint_tags"), fallback=()))
        if tag
    )
    type_sample = display_text(tile.get("sample"))
    specimen = (
        f'<p class="mood-specimen">{escape(type_sample)}</p>' if kind == "type-specimen" and type_sample else ""
    )

    # Only the hero tile carries a generated/honest visual. Supporting tiles describe
    # board DNA (palette, type, product/interface/object/motion) and never show the SVG.
    visual = _visual_slot(tile) if span == "hero" else ""
    caption = _public_moodboard_copy(tile.get("caption"))
    title_text = _public_moodboard_copy(tile.get("title"))
    title_html = "" if is_primary else f"<h3>{escape(title_text)}</h3>"
    caption_html = "" if is_primary or not caption else f'<p class="mood-caption">{escape(caption)}</p>'

    tension_html = (
        f"""<div class="tension-pair">
          <span class="tension-item">Want: {escape(display_text(tension.get("wants")))}</span>
          <span class="tension-item avoid">Avoid: {escape(display_text(tension.get("avoid")))}</span>
        </div>"""
        if tension
        else ""
    )
    detail_parts = []
    if constraints:
        detail_parts.append(f'<div class="constraint-tags">{constraints}</div>')
    if tension_html:
        detail_parts.append(tension_html)
    if annotation:
        detail_parts.append(f'<div class="tile-annotation">{escape(annotation)}</div>')
    details = (
        f"""<details class="mood-tile-detail">
            <summary>Details</summary>
            {''.join(detail_parts)}
          </details>"""
        if detail_parts
        else ""
    )
    role_class = "mood-tile--visual" if is_primary else "mood-tile--support"
    return f"""
        <article class="mood-tile mood-tile--{escape(span, quote=True)} {role_class}" data-tile-kind="{escape(kind, quote=True)}" data-filter-item>
          <p class="tile-kind">{escape(_public_tile_kind_label(kind))}</p>
          {visual}
          {specimen}
          {swatches}
          {title_html}
          {caption_html}
          {details}
        </article>"""


def _mood_tile_by_kind(tiles: Sequence[Mapping[str, Any]], kind: str) -> Mapping[str, Any]:
    return next((tile for tile in tiles if display_text(tile.get("kind")) == kind), {})


def _mood_tile_title(tile: Mapping[str, Any], fallback: str) -> str:
    return _public_moodboard_copy(tile.get("title")) or fallback


def _mood_tile_caption(tile: Mapping[str, Any], fallback: str = "") -> str:
    return _public_moodboard_copy(tile.get("caption")) or fallback


def _short_text(value: Any, limit: int) -> str:
    text = _public_moodboard_copy(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _mood_asset_src(tile: Mapping[str, Any]) -> str:
    return safe_href(tile.get("asset_src"))


def _mood_crop_view(hero_tile: Mapping[str, Any], *, route_title: str) -> str:
    src = _mood_asset_src(hero_tile)
    label = "Detail view"
    caption = _mood_tile_caption(hero_tile, "A closer crop from the route image for material, interaction, and object detail.")
    crop = (
        f"""<button class="mood-crop-frame peek-trigger" type="button" data-lightbox-src="{escape(src, quote=True)}" data-lightbox-title="{escape(route_title)} detail crop">
              <img src="{escape(src, quote=True)}" alt="{escape(route_title)} detail crop">
            </button>"""
        if src
        else '<div class="mood-crop-frame mood-crop-frame--empty" aria-hidden="true"></div>'
    )
    return f"""
      <article class="mood-view mood-view--detail" data-view-role="detail">
        <p class="tile-kind">{label}</p>
        {crop}
        <p class="mood-caption">{escape(caption)}</p>
      </article>"""


def _mood_web_view(
    *,
    route_title: str,
    hero_tile: Mapping[str, Any],
    product_tile: Mapping[str, Any],
    palette_tile: Mapping[str, Any],
    type_tile: Mapping[str, Any],
) -> str:
    src = _mood_asset_src(hero_tile)
    title = _mood_tile_title(product_tile, route_title)
    caption = _mood_tile_caption(product_tile, _mood_tile_caption(hero_tile, "Landing page structure for the route."))
    colors = normalize_palette(palette_tile.get("colors"))
    accent = colors[0]["hex"] if colors else "#ff6a2b"
    secondary = colors[1]["hex"] if len(colors) > 1 else "#16140f"
    type_sample = display_text(type_tile.get("sample"), fallback=route_title)
    image = f'<img src="{escape(src, quote=True)}" alt="" aria-hidden="true">' if src else ""
    return f"""
      <article class="mood-view mood-view--web" data-view-role="web" style="--view-accent:{escape(accent, quote=True)}; --view-secondary:{escape(secondary, quote=True)}">
        <p class="tile-kind">Website view</p>
        <div class="web-mockup" aria-label="{escape(route_title)} web composition">
          <div class="web-mockup-bar"><span></span><span></span><span></span></div>
          <div class="web-mockup-body">
            <div>
              <p>{escape(type_sample)}</p>
              <h4>{escape(title)}</h4>
              <span>{escape(_short_text(caption, 96))}</span>
            </div>
            <figure>{image}</figure>
          </div>
        </div>
      </article>"""


def _mood_phone_view(
    *,
    route_title: str,
    hero_tile: Mapping[str, Any],
    interface_tile: Mapping[str, Any],
    palette_tile: Mapping[str, Any],
) -> str:
    src = _mood_asset_src(hero_tile)
    title = _mood_tile_title(interface_tile, route_title)
    caption = _mood_tile_caption(interface_tile, "Compact interface rhythm for the route.")
    colors = normalize_palette(palette_tile.get("colors"))
    accent = colors[0]["hex"] if colors else "#ff6a2b"
    surface = colors[2]["hex"] if len(colors) > 2 else "#f4efe6"
    image = f'<img src="{escape(src, quote=True)}" alt="" aria-hidden="true">' if src else ""
    return f"""
      <article class="mood-view mood-view--phone" data-view-role="phone" style="--view-accent:{escape(accent, quote=True)}; --view-surface:{escape(surface, quote=True)}">
        <p class="tile-kind">Phone view</p>
        <div class="phone-mockup" aria-label="{escape(route_title)} phone composition">
          <div class="phone-screen">
            <div class="phone-image">{image}</div>
            <h4>{escape(title)}</h4>
            <p>{escape(_short_text(caption, 86))}</p>
            <div class="phone-controls"><span></span><span></span><span></span></div>
          </div>
        </div>
      </article>"""


def _mood_palette_view(tile: Mapping[str, Any]) -> str:
    colors = normalize_palette(tile.get("colors"))
    caption = _mood_tile_caption(tile, "Color reads as product state, not decoration.")
    def palette_label(value: Any, fallback: str) -> str:
        label = display_text(value, fallback=fallback)
        label = re.sub(r"\bproof\b", "source", label, flags=re.I)
        label = re.sub(r"\breceipt\b", "record", label, flags=re.I)
        label = re.sub(r"\bprovider\b", "source", label, flags=re.I)
        return label

    swatches = "".join(
        f"""<div class="palette-block" style="--swatch:{escape(color['hex'], quote=True)}">
              <span>{escape(palette_label(color.get("role"), "Color"))}</span>
              <b>{escape(palette_label(color.get("name"), "Palette"))}</b>
            </div>"""
        for color in colors
    )
    return f"""
      <article class="mood-view mood-view--palette" data-view-role="palette">
        <p class="tile-kind">Palette</p>
        <div class="palette-board">{swatches}</div>
        <p class="mood-caption">{escape(caption)}</p>
      </article>"""


def _mood_type_view(tile: Mapping[str, Any], *, route_title: str) -> str:
    sample = display_text(tile.get("sample"), fallback=route_title)
    caption = _mood_tile_caption(tile, "Type sets the route's pace and temperature.")
    return f"""
      <article class="mood-view mood-view--type" data-view-role="type">
        <p class="tile-kind">Type</p>
        <p class="mood-specimen mood-specimen--board">{escape(sample)}</p>
        <p class="mood-caption">{escape(caption)}</p>
      </article>"""


def _mood_cue_view(tile: Mapping[str, Any], *, role: str, label: str, fallback: str) -> str:
    title = _mood_tile_title(tile, label)
    caption = _mood_tile_caption(tile, fallback)
    return f"""
      <article class="mood-view mood-view--cue" data-view-role="{escape(role, quote=True)}">
        <p class="tile-kind">{escape(label)}</p>
        <h4>{escape(title)}</h4>
        <p class="mood-caption">{escape(caption)}</p>
      </article>"""


def _public_tile_kind_label(kind: str) -> str:
    labels = {
        "generated-concept-image": "Concept image",
        "visual-direction-board": "Visual direction",
        "manual-prompt-card": "Image direction",
        "generation-unavailable": "Image direction",
        "fixture-system-sketch": "System sketch",
        "palette-strip": "Palette",
        "type-specimen": "Type",
        "product-moment": "Product moment",
        "interface-frame": "Interface frame",
        "object-packaging": "Object cue",
        "motion-idea": "Motion",
    }
    return labels.get(kind, kind.replace("-", " "))


def _moodboard(pack: Mapping[str, Any]) -> str:
    groups = []
    for index, group in enumerate(_as_mappings(pack.get("moodboard_tiles"))):
        route_id = display_text(group.get("route_id"), fallback=f"route-{index + 1}")
        hidden = "" if index == 0 else " hidden"
        raw_tiles = _as_mappings(group.get("tiles"))
        primary_index = next(
            (tile_index for tile_index, tile in enumerate(raw_tiles) if display_text(tile.get("span")) == "hero"),
            0,
        )
        primary_tile = raw_tiles[primary_index] if raw_tiles else {}
        support_tiles = [tile for tile_index, tile in enumerate(raw_tiles) if tile_index != primary_index]
        palette_tile = _mood_tile_by_kind(raw_tiles, "palette-strip")
        type_tile = _mood_tile_by_kind(raw_tiles, "type-specimen")
        product_tile = _mood_tile_by_kind(raw_tiles, "product-moment")
        interface_tile = _mood_tile_by_kind(raw_tiles, "interface-frame")
        object_tile = _mood_tile_by_kind(raw_tiles, "object-packaging")
        motion_tile = _mood_tile_by_kind(raw_tiles, "motion-idea")
        primary = _mood_tile(primary_tile, is_primary=True) if primary_tile else ""
        multi_views = "".join(
            view
            for view in (
                _mood_crop_view(primary_tile, route_title=display_text(group.get("route_title"), fallback="Route")),
                _mood_web_view(
                    route_title=display_text(group.get("route_title"), fallback="Route"),
                    hero_tile=primary_tile,
                    product_tile=product_tile,
                    palette_tile=palette_tile,
                    type_tile=type_tile,
                ),
                _mood_phone_view(
                    route_title=display_text(group.get("route_title"), fallback="Route"),
                    hero_tile=primary_tile,
                    interface_tile=interface_tile,
                    palette_tile=palette_tile,
                ),
                _mood_palette_view(palette_tile) if palette_tile else "",
                _mood_type_view(type_tile, route_title=display_text(group.get("route_title"), fallback="Route")) if type_tile else "",
                _mood_cue_view(object_tile, role="material", label="Material cue", fallback="Material, packaging, and scale cues for the route.") if object_tile else "",
                _mood_cue_view(motion_tile, role="motion", label="Movement", fallback="One motion beat should prove the product ritual.") if motion_tile else "",
            )
            if view
        )
        support = "".join(_mood_tile(tile) for tile in support_tiles)
        groups.append(
            f"""
            <div class="moodboard-route" data-route-panel="{escape(route_id, quote=True)}"{hidden}>
              <div class="moodboard-title">
                <p class="kicker">Moodboard Canvas</p>
                <h3>{escape(display_text(group.get("route_title")))}</h3>
              </div>
              <div class="moodboard-legend" aria-label="Board rules">
                <span class="legend-item"><span class="legend-color in"></span>In-bounds</span>
                <span class="legend-item"><span class="legend-color out"></span>Out-of-bounds</span>
              </div>
              <div class="moodboard-canvas--dark">
                <div class="moodboard-grid">
                  <div class="moodboard-primary">{primary}</div>
                  <div class="moodboard-view-grid">{multi_views}</div>
                  <details class="moodboard-support-detail">
                    <summary>Route notes</summary>
                    <div class="moodboard-support-stack">{support}</div>
                  </details>
                </div>
              </div>
            </div>"""
        )
    return f"""
    <section class="dossier-section" id="moodboard" data-nav-section data-nav-label="Moodboard" data-jump-target>
      {_section_heading("moodboard", "Studio Mode", "Creative Moodboard Workbench", "Large previews, palette rails, type specimens, product moments, motion ideas, and tension pairs stay route-specific.", pack=pack)}
      {''.join(groups)}
    </section>"""


def _font_lab(pack: Mapping[str, Any]) -> str:
    groups = []
    for index, group in enumerate(_as_mappings(pack.get("font_options"))):
        route_id = display_text(group.get("route_id"), fallback=f"route-{index + 1}")
        hidden = "" if index == 0 else " hidden"
        options = []
        for option in _as_mappings(group.get("options")):
            import_hint = display_text(option.get("import_hint"))
            preview = resolve_font_preview(option)
            public_rationale = _public_type_rationale(
                option.get("why_london_chose_it"),
                option.get("why_this_route_not_other_route"),
            )
            reference_card = _font_reference_card(preview.reference_preview)
            specimen = reference_card if preview.status == "reference_capture" and reference_card else _font_specimen_board(option, preview)
            proof_rows = "".join(
                f"<div><dt>{escape(label)}</dt><dd>{escape(value)}</dd></div>"
                for label, value in (
                    ("Rendered Family", preview.rendered_family),
                    ("Preview Source", preview.source_label),
                    ("Stack", display_text(option.get("fallback_stack"))),
                    ("Asset", preview.asset_href),
                )
                if value
            )
            proof_detail = (
                f"""
                  <details class="receipt-detail is-receipt-detail">
                    <summary>Font source details</summary>
                    <dl>{proof_rows}</dl>
                  </details>"""
                if proof_rows
                else ""
            )
            options.append(
                f"""
                <article class="font-option font-option--{escape(preview.status, quote=True)}" data-filter-item data-font-preview-status="{escape(preview.status, quote=True)}" data-font-preview-delivery="{escape(preview.delivery, quote=True)}" data-font-preview-family="{escape(preview.rendered_family, quote=True)}"{f' data-font-asset-href="{escape(preview.asset_href, quote=True)}"' if preview.asset_href else ''}>
                  <p class="badge">{escape(display_text(option.get("label")))}</p>
                  <h3>{escape(display_text(option.get("name")))}</h3>
                  {specimen}
                  <div class="font-preview-meta">
                    <p><b>London recommends</b> {escape(display_text(option.get("headline_font")))} headlines, {escape(display_text(option.get("body_font")))} body, {escape(display_text(option.get("label_font")))} labels.</p>
                    <p>{escape(public_rationale)}</p>
                  </div>
                  <dl>
                    <div><dt>Best Use</dt><dd>{escape(display_text(option.get("best_use")))}</dd></div>
                    <div><dt>London Choice</dt><dd>{escape(public_rationale)}</dd></div>
                    <div><dt>Wrong If</dt><dd>{escape(display_text(option.get("what_makes_it_wrong")))}</dd></div>
                  </dl>
                  {proof_detail}
                  {_font_proof_details(preview)}
                  {reference_card if preview.status != "reference_capture" else ""}
                  {f'<button class="copy-button" type="button" data-copy="{escape(import_hint, quote=True)}">Copy import note</button>' if import_hint else ''}
                </article>"""
            )
        groups.append(
            f"""
            <div class="font-route" data-route-panel="{escape(route_id, quote=True)}"{hidden}>
              <h3>{escape(display_text(group.get("route_title")))}</h3>
              <div class="font-grid">{''.join(options)}</div>
            </div>"""
        )
    return f"""
    <section class="dossier-section" id="font-lab" data-nav-section data-nav-label="Font Lab" data-jump-target>
      {_section_heading("font-lab", "Font Lab", "Type Choices With Consequences", "Each route carries a local-safe stack, a public web direction, and a premium inspiration lane.", pack=pack)}
      {''.join(groups)}
    </section>"""


def _font_specimen_board(option: Mapping[str, Any], preview) -> str:
    role_stacks = preview.role_css_stacks if isinstance(getattr(preview, "role_css_stacks", None), Mapping) else {}
    if preview.status == "reference_only":
        headline_stack = body_stack = label_stack = "system-ui, sans-serif"
    else:
        headline_stack = display_text(role_stacks.get("headline"), fallback=preview.css_stack)
        body_stack = display_text(role_stacks.get("body"), fallback=safe_css_stack_for_render(option.get("fallback_stack")))
        label_stack = display_text(role_stacks.get("label"), fallback=safe_css_stack_for_render(option.get("fallback_stack")))
    headline = display_text(option.get("sample_headline"), fallback=display_text(option.get("name"), fallback="Route specimen"))
    body = display_text(option.get("sample_body"), fallback=display_text(option.get("best_use")))
    label = display_text(option.get("sample_label"), fallback=display_text(option.get("label_font")))
    reference_note = (
        '<p class="font-reference-note">Reference only: needs an official specimen capture before this card can claim visual fidelity.</p>'
        if preview.status == "reference_only"
        else ""
    )
    return f"""
                  <div class="font-specimen-board font-specimen-board--{escape(preview.status, quote=True)}">
                    <p class="font-specimen-role">Headline</p>
                    <p class="font-specimen" style="font-family:{escape(headline_stack, quote=True)}" data-font-preview-family="{escape(preview.rendered_family, quote=True)}">{escape(headline)}</p>
                    <p class="font-specimen-role">Body</p>
                    <p class="font-specimen-body" style="font-family:{escape(body_stack, quote=True)}">{escape(body)}</p>
                    <p class="font-specimen-role">Label</p>
                    <p class="font-specimen-label" style="font-family:{escape(label_stack, quote=True)}">{escape(label)} / {escape(display_text(option.get("tier")).replace("_", " "))}</p>
                    {reference_note}
                  </div>"""


def safe_css_stack_for_render(value: Any) -> str:
    stack = display_text(value, fallback="system-ui, sans-serif")
    if any(token in stack for token in ("{", "}", ";", "<", ">", "@import", "url(")):
        return "system-ui, sans-serif"
    return stack


def _font_reference_card(reference_preview: Mapping[str, Any] | None) -> str:
    if not isinstance(reference_preview, Mapping):
        return ""
    url = _safe_external_reference_url(reference_preview.get("url") or reference_preview.get("src"))
    license_url = _safe_external_reference_url(reference_preview.get("buy_or_license_url")) or url
    image_src = _safe_reference_image_src(reference_preview.get("specimen_image_src") or reference_preview.get("image_src"))
    source = display_text(reference_preview.get("source_label"), fallback="Public specimen")
    note = display_text(
        reference_preview.get("license_or_terms_note"),
        fallback="Visual reference, font not loaded.",
    )
    alt = display_text(reference_preview.get("alt"), fallback="Open public type specimen")
    open_link = (
        f'<a href="{escape(url, quote=True)}" rel="noreferrer" target="_blank">Open specimen</a>'
        if url
        else ""
    )
    license_link = (
        f'<a href="{escape(license_url, quote=True)}" rel="noreferrer" target="_blank">Buy/license</a>'
        if license_url and license_url != url
        else ""
    )
    image = (
        f'<img src="{escape(image_src, quote=True)}" alt="{escape(alt, quote=True)}">'
        if image_src
        else ""
    )
    return f"""
                  <figure class="font-reference-card" data-font-reference="reference_capture">
                    {image}
                    <figcaption><b>{escape(source)}</b><span>{escape(alt)}</span></figcaption>
                    <details class="receipt-detail is-receipt-detail">
                      <summary>Reference source details</summary>
                      <p>{escape(note)}</p>
                      <div class="reference-links">{open_link}{license_link}</div>
                    </details>
                  </figure>"""


def _safe_external_reference_url(value: Any) -> str:
    url = safe_href(value)
    return url if url.startswith("https://") else ""


def _safe_reference_image_src(value: Any) -> str:
    return safe_href(value, allow_parent_assets=True)


def _constraint_legend(pack: Mapping[str, Any]) -> str:
    constraints = [
        ("No Fake Evidence", "Source registry items are labeled as planned unless evidence confirms extraction."),
        ("Route Specific", "Palettes, type notes, prototypes, prompts, and next steps must change with the brief."),
        ("Product Cue", display_text(pack.get("vessel_interface_expression"), fallback="The product behavior must be visible.")),
        ("Anti-Position", display_text(pack.get("anti_position"), fallback="Reject generic modern-clean filler.")),
    ]
    items = "".join(f"<li><b>{escape(title)}</b><span>{escape(_public_handoff_text(body))}</span></li>" for title, body in constraints)
    return f"""
    <section class="dossier-section" id="constraints" data-nav-section data-nav-label="Constraints" data-jump-target>
      {_section_heading("constraints", "Constraint Legend", "What The Work Must Obey", pack=pack)}
      <ul class="constraint-list">{items}</ul>
    </section>"""


def _evidence(pack: Mapping[str, Any]) -> str:
    summary = pack.get("evidence_summary") if isinstance(pack.get("evidence_summary"), Mapping) else {}
    brain_groups = []
    for group in _as_mappings(summary.get("brain") if isinstance(summary, Mapping) else []):
        findings = "".join(_finding_item(finding) for finding in _as_mappings(group.get("findings")))
        brain_groups.append(
            f"""<article class="evidence-group" data-filter-item>
              <h4>{escape(display_text(group.get('gate')))}</h4>
              <p>{escape(str(group.get('finding_count', 0)))} {escape(display_text(group.get('evidence_class'), fallback='London Brain Finding'))} records</p>
              <ul class="primary-evidence">{findings}</ul>
            </article>"""
        )
    sources = "".join(
        f"""<li class="source-target"><b>{escape(display_text(source.get("title")))}</b>
        <em>{escape(display_text(source.get("evidence_class"), fallback="Source Target"))} / {escape(display_text(source.get("status"), fallback="planned-reference"))}</em>
        <span>{escape(_public_source_target_note(source.get("claim") or source.get("why_london_used_this")))}</span>
        <small>{escape(display_text(source.get("path")))}</small></li>"""
        for source in _as_mappings(summary.get("sources") if isinstance(summary, Mapping) else [])
    )
    providers = "".join(
        f"<li><b>{escape(display_text(provider.get('provider')))}</b><span>{escape(display_text(provider.get('status')))}</span></li>"
        for provider in _as_mappings(summary.get("providers") if isinstance(summary, Mapping) else [])
    )
    live_artifacts = "".join(
        f"""<li><b>{escape(display_text(artifact.get("kind"), fallback="Live Artifact"))}</b>
        <span>{escape(display_text(artifact.get("provider")))} / {escape(display_text(artifact.get("summary")))}</span></li>"""
        for artifact in _as_mappings(summary.get("live_artifacts") if isinstance(summary, Mapping) else [])
    ) or "<li><b>No Live Assets</b><span>No completed image asset is present in this deterministic pack.</span></li>"
    return f"""
    <section class="dossier-section" id="evidence" data-nav-section data-nav-label="Evidence" data-jump-target>
      {_section_heading("evidence", "Evidence Drawer", "What London Used", _public_source_claim(summary.get("source_claim") if isinstance(summary, Mapping) else ""), pack=pack)}
      <details class="drawer" data-persist="evidence-brain">
        <summary>Why London believes this</summary>
        <div class="evidence-grid">{''.join(brain_groups)}</div>
      </details>
      <details class="drawer" data-persist="evidence-sources">
        <summary>Source Targets</summary>
        <ul class="source-list">{sources}</ul>
      </details>
      <details class="drawer" data-persist="evidence-live">
        <summary>Live route assets</summary>
        <ul class="source-list">{live_artifacts}</ul>
      </details>
      <details class="drawer" data-persist="evidence-providers">
        <summary>Run source trail</summary>
        <ul class="source-list">{providers}</ul>
      </details>
    </section>"""


def _public_grader_name(value: Any) -> str:
    labels = {
        "Source Auditor": "Source Check",
        "Claim Integrity Auditor": "Source Check",
        "Grounding Inspector": "Grounding Check",
        "Distinctness Referee": "Route Distance",
        "Route Distinctness Inspector": "Route Distance",
        "Output Manifest": "Pack Completeness",
        "Output Manifest Inspector": "Pack Completeness",
        "Type Selection Referee": "Type Range",
    }
    text = display_text(value)
    return labels.get(text, text)


def _grader_colophon(inspectors: Sequence[Mapping[str, Any]]) -> str:
    # RENDER-05 / UI-SPEC Surface 4: the named inspectors as a Team.html-style
    # colophon — one .inspector-track per inspector at count = len(inspectors)
    # (NOT a fixed 4-slot grid; render whatever N the grader emits). This block is
    # LIGHT (--surface/--text), NOT a 4th dark zone; no Google Fonts, no grain
    # canvas, no cyan #00E5FF, no mousemove parallax — system fonts + render.py's
    # own :root tokens only. The verdict bar fill is the REAL sub-score
    # (inspector["score"], 0..1) emitted as a static inline width — never a
    # data-level fiction and never an animated gauge. score == "n/a" renders an
    # honest empty/n/a bar (a transcript-blind inspector), NOT a 0% bar dressed as
    # a measurement. A failing inspector (CLAIM_UNVERIFIED / DEAD_ENGINE /
    # THIN_GROUNDING / ROUTES_TOO_NEAR / INCOMPLETE) marks the track --danger.
    _failing_verdicts = {
        "CLAIM_UNVERIFIED",
        "DEAD_ENGINE",
        "THIN_GROUNDING",
        "ROUTES_TOO_NEAR",
        "INCOMPLETE",
        "TELEMETRY_UNAVAILABLE",
    }

    def public_verdict(value: Any) -> str:
        labels = {
            "CLAIM_OK": "Sources align",
            "CLAIM_UNVERIFIED": "Needs source check",
            "TELEMETRY_UNAVAILABLE": "Open check",
            "DEAD_ENGINE": "Needs another pass",
            "THIN_GROUNDING": "Needs more grounding",
            "ROUTES_TOO_NEAR": "Routes are too close",
            "INCOMPLETE": "Pack is incomplete",
            "DISTINCT": "Distinct",
            "COMPLETE": "Complete",
            "TYPE_RANGE_HEALTHY": "Type range healthy",
            "OBSERVED": "Observed",
        }
        text = display_text(value)
        return labels.get(text, text.replace("_", " ").title() if text else "")

    tracks = []
    for inspector in inspectors:
        name = _public_grader_name(inspector.get("name"))
        dimension = _public_grader_copy(inspector.get("dimension"))
        verdict = display_text(inspector.get("verdict"))
        score = inspector.get("score")
        failing = verdict in _failing_verdicts
        is_na = not isinstance(score, (int, float)) or isinstance(score, bool)
        if is_na:
            # Honest absence bar: an empty meter labelled as open, not a 0% measurement.
            fill_pct = 0.0
            bar = (
                '<div class="verdict-bar verdict-bar--na" role="img" '
                'aria-label="readiness detail open">'
                '<span class="verdict-bar-na">Open check</span></div>'
            )
        else:
            fill_pct = max(0.0, min(1.0, float(score))) * 100.0
            bar = (
                f'<div class="verdict-bar{" verdict-bar--danger" if failing else ""}" '
                f'role="img" aria-label="readiness detail {fill_pct:.0f} percent">'
                f'<span class="verdict-bar-fill" style="width:{fill_pct:.1f}%"></span></div>'
            )
        tracks.append(
            f"""
            <li class="inspector-track{' inspector-track--danger' if failing else ''}">
              <div class="inspector-track-meta">
                <p class="track-title">{escape(name)}</p>
                <p class="track-id">{escape_prose(dimension)}</p>
              </div>
              {bar}
              <p class="track-verdict">{escape(public_verdict(verdict))}</p>
            </li>"""
        )
    return f"""
      <div class="inspector-colophon">
        <div class="section-heading">
          <p class="kicker">Checks</p>
          <p class="inspector-sublabel">supporting checks, not London judging her own taste</p>
        </div>
        <ul class="inspector-track-list">{''.join(tracks)}</ul>
      </div>"""


def _public_grader_label(value: Any) -> str:
    labels = {
        "COMPOSITE": "Readiness check",
        "TELEMETRY_UNAVAILABLE": "Open check",
        "CLAIM_OK": "Sources align",
        "CLAIM_UNVERIFIED": "Needs source check",
        "DEAD_ENGINE": "Needs another pass",
        "BRAIN QUERIES // TRACE": "London library checks",
        "SOURCES CONSULTED": "Sources checked",
        "OUTPUT MANIFEST": "Pack contents",
        "CLAIM INTEGRITY // AUDIT": "Source consistency",
        "SOURCES MATRIX": "Source coverage",
        "TYPE_RANGE_HEALTHY": "Type range healthy",
        "DISTINCT": "Distinct",
        "COMPLETE": "Complete",
    }
    text = display_text(value)
    return labels.get(text, text.replace("_", " ").title() if text else "")


def _public_grader_copy(value: Any) -> str:
    text = display_text(value)
    if not text:
        return ""
    exact = {
        "weighted from 5 objective checks": "Source and structure checks",
        "Every cited source verified against the real MCP transcript": "Saved sources align with the source trail.",
        "Every cited source checks out against the transcript.": "Listed sources align with the source trail.",
        "No transcript for this engine mode — cited-source verification unavailable.": "Saved-source check stays open in this mode.",
        "Telemetry not captured; no transcript to verify cited sources against.": "Saved-source check stays open in this mode.",
        "No transcript for this engine mode — grounding unavailable.": "Grounding could not be checked in this mode.",
        "No transcript for this engine mode: grounding unavailable.": "Grounding could not be checked in this mode.",
        "Telemetry not captured for this engine mode — the engine grade is unavailable.": "The Workbench leaves this verdict open for this mode.",
        "Telemetry not captured for this engine mode: the engine grade is unavailable.": "The Workbench leaves this verdict open for this mode.",
        "No engine score captured for this engine mode; the output-measurable sub-scores are reported but NOT rolled into a fabricated hero": "The Workbench leaves this verdict open for this mode; measurable checks remain available below.",
        "Font choices show enough range; local assets are proof, not the whole taste pool.": "Font choices show enough range; local assets support the type surface, but they are not the whole taste pool.",
        "Font Lab range: local fonts allowed, but not allowed to dominate taste": "Font Lab shows enough range; local-safe options do not dominate the taste read.",
        "Font Lab range — local fonts allowed, but not allowed to dominate taste": "Font Lab shows enough range; local-safe options do not dominate the taste read.",
        "Every required region is filled at honest cardinality.": "Every required region is filled with the pack's honest route count.",
        "Every required region filled at honest cardinality, no padded slots": "Every required section is filled without padded slots.",
        "Real brain-query depth (target ~ 4)": "London library depth for this pass.",
        "Real brain-query depth (target ≈ 8)": "London library depth for this pass.",
    }
    if text in exact:
        return exact[text]
    return re.sub(r"\s+", " ", text).strip()


def _grader_section(pack: Mapping[str, Any]) -> str:
    # RENDER-03 / RENDER-04 / RENDER-05 — UI-SPEC Surface 3 + 4. The system-monitor
    # aesthetic mapped onto London's REAL pack["grader"] metrics. The grader block
    # is OPTIONAL (schema:7-32) — guard it defensively the same way _evidence guards
    # its summary mapping (render.py:869). Absent grader → an honest "no grade"
    # state (no crash, no fabricated grade). Every gauge (hero number, lit sensor
    # opacity, spark-bar width, verdict-bar fill) is a STATIC inline value computed
    # in Python from the grader block — NO setInterval, NO Math.random(), NO runtime
    # gauge compute (the Math.random() inversion; T-05.1-07). Every interpolated
    # string passes escape() (T-05.1-05); numeric style values are computed
    # ints/floats. The dark hero band reuses the command-center literal
    # #0E0E0E/#F4F4F2 via a NEW .grader-zone--dark class — NOT .command-center, NOT
    # .moodboard-canvas--dark, NOT #171717, NOT #000.
    grader = pack.get("grader") if isinstance(pack.get("grader"), Mapping) else {}
    if not grader:
        # Honest "no grade" — the pack never ran the grader. Render an honest empty
        # state (still a registered #grader anchor so the nav does not dangle), never
        # a fabricated grade.
        return f"""
    <section class="dossier-section" id="grader" data-nav-section data-nav-label="Quality Check" data-jump-target>
      {_section_heading("grader", "Readiness Check", "No readiness check is available for this pack", "No independent source check is available, so the Workbench leaves this surface empty instead of fabricating one.", pack=pack)}
    </section>"""

    composite = grader.get("composite") if isinstance(grader.get("composite"), Mapping) else {}
    headline = grader.get("headline") if isinstance(grader.get("headline"), Mapping) else {}
    audit = grader.get("audit") if isinstance(grader.get("audit"), Mapping) else {}
    telemetry = grader.get("telemetry") if isinstance(grader.get("telemetry"), Mapping) else {}
    detail = grader.get("detail") if isinstance(grader.get("detail"), Mapping) else {}
    inspectors = _as_mappings(grader.get("inspectors"))

    score = composite.get("score")
    captured = composite.get("telemetry_available")
    # The documented branch (grader.py:387 records telemetry_available precisely so
    # 5.1 does NOT re-derive it): n/a / telemetry-unavailable vs a captured number
    # (which may be a near-dead ~27 — a REAL low grade, distinct from "no grade").
    unavailable = (score == "n/a") or (captured is False)

    # --- Hero band (the dark zone) -------------------------------------------------
    hero_label = _public_grader_label(headline.get("label") or "COMPOSITE")
    hero_sub = _public_grader_copy(headline.get("sub_label") or "weighted from 5 objective checks")
    hero_summary = _public_grader_copy(headline.get("summary"))
    if unavailable:
        # Honest engine-grade absence, visually and semantically distinct from a
        # captured low number. The sensor matrix is dimmed.
        hero_number_html = (
            '<p class="grader-hero-number grader-hero-number--na">Open check</p>'
            '<p class="grader-hero-state">The Workbench leaves this verdict open for this mode.</p>'
        )
    else:
        hero_value = display_text(headline.get("score")) or display_text(score)
        hero_number_html = f'<p class="grader-hero-number">{escape(hero_value)}</p>'

    # The lit sensor matrix: len(consulted_source_ids) lit out of brain_total_entries.
    # The lit set is computed in Python and emitted as static per-dot opacity — no
    # animation. We cap the rendered dot grid at a readable ceiling (the matrix is a
    # proportion readout, not a 3439-node render); the lit COUNT and the live
    # denominator are printed verbatim alongside so the proportion stays honest.
    consulted = telemetry.get("consulted_source_ids")
    consulted_count = len(consulted) if isinstance(consulted, Sequence) and not isinstance(consulted, (str, bytes)) else 0
    total_entries = telemetry.get("brain_total_entries")
    total_entries = total_entries if isinstance(total_entries, int) and total_entries > 0 else 0
    _MATRIX_DOTS = 48
    if total_entries:
        lit_dots = min(_MATRIX_DOTS, round(_MATRIX_DOTS * consulted_count / total_entries)) if consulted_count else 0
        # A consulted-but-tiny proportion still lights at least one dot so a real
        # (non-zero) consultation never reads as a dead 0-lit matrix.
        if consulted_count and lit_dots == 0:
            lit_dots = 1
    else:
        lit_dots = 0
    matrix_dimmed = " grader-data-matrix--dimmed" if unavailable else ""
    sensor_dots = "".join(
        f'<span class="sensor-node" style="opacity:{1.0 if i < lit_dots else 0.12}"></span>'
        for i in range(_MATRIX_DOTS)
    )
    denom_text = f"{consulted_count}/{total_entries}" if total_entries else f"{consulted_count}/open check"
    matrix_caption = (
        "readiness check left open for this mode" if unavailable
        else f"{consulted_count} of {total_entries} London library entries checked" if total_entries
        else f"{consulted_count} London library entries checked"
    )

    accent_for_hero = "#F4F4F2"
    hero_band = f"""
      <div class="grader-zone--dark"{' data-grader-state="unavailable"' if unavailable else ''} style="--accent:{escape(accent_for_hero, quote=True)}">
        <div class="grader-hero">
          <p class="grader-hero-kicker">{escape(hero_label)}</p>
          {hero_number_html}
          <p class="grader-hero-sub">{escape_prose(hero_sub)}</p>
          {f'<p class="grader-hero-summary">{escape_prose(hero_summary)}</p>' if hero_summary else ''}
        </div>
        <div class="grader-sensor">
          <p class="grader-sensor-kicker">{escape(_public_grader_label("SOURCES MATRIX"))} <span class="grader-sensor-denom">{escape(denom_text)}</span></p>
          <div class="grader-data-matrix{matrix_dimmed}" aria-label="{escape(matrix_caption, quote=True)}">{sensor_dots}</div>
          <p class="grader-sensor-caption">{escape(matrix_caption)}</p>
        </div>
      </div>"""

    # --- The four trace columns (each open at count = len) -------------------------
    brain_queries = _as_mappings(telemetry.get("brain_queries"))
    if brain_queries:
        query_items = "".join(
            f'<li class="grader-trace-item"><code>{escape(display_text(q.get("query")))}</code>'
            f'<span class="grader-trace-meta">{escape(str(q.get("result_count", 0)))} hits</span></li>'
            for q in brain_queries
        )
    else:
        query_items = '<li class="grader-trace-empty">No London library lookups available here.</li>'

    grounded = audit.get("grounded_source_ids")
    grounded = list(grounded) if isinstance(grounded, Sequence) and not isinstance(grounded, (str, bytes)) else []
    if grounded:
        source_items = "".join(
            f'<li class="grader-trace-item"><code>{escape(display_text(sid))}</code></li>'
            for sid in grounded
        )
    else:
        source_items = '<li class="grader-trace-empty">No completed source references available here.</li>'

    # OUTPUT MANIFEST spark-bars: real cardinalities → static inline width. The fill
    # is honest — a region at its cardinality, never padded to 100%. We scale each
    # bar against a small reference ceiling per region so the bar is readable, and
    # always print the raw count verbatim so the number is the source of truth.
    routes = _as_mappings(pack.get("routes"))
    convo = _as_mappings(pack.get("conversation"))
    copy_blocks = _as_mappings(pack.get("copy_blocks"))
    next_steps = _as_mappings(pack.get("next_steps"))
    swatch_total = sum(len(normalize_palette(r.get("palette"))) for r in routes)
    manifest_rows = [
        ("routes", len(routes), 4),
        ("decisions", len(convo), 8),
        ("swatches", swatch_total, 24),
        ("copy blocks", len(copy_blocks), 12),
        ("next steps", len(next_steps), 8),
    ]
    manifest_items = "".join(
        f'<li class="spark-row"><span class="spark-label">{escape(label)}</span>'
        f'<span class="spark-bar"><span class="spark-bar-fill" style="width:{min(100.0, (count / ref * 100.0) if ref else 0.0):.1f}%"></span></span>'
        f'<span class="spark-count">{count}</span></li>'
        for label, count, ref in manifest_rows
    )

    # CLAIM INTEGRITY // AUDIT (RENDER-04): CLAIM_UNVERIFIED renders in --danger;
    # grounded_source_ids is the verified rail (show-verified-only); claim_unverified
    # LIGHTS the flag but NEVER hard-fails a legit run — the flag renders, never blocks.
    verdict = display_text(audit.get("verdict"))
    unverified = audit.get("claim_unverified")
    unverified = list(unverified) if isinstance(unverified, Sequence) and not isinstance(unverified, (str, bytes)) else []
    is_unverified = verdict == "CLAIM_UNVERIFIED"
    if is_unverified:
        flagged = "".join(
            f'<li class="grader-claim-flagged"><code>{escape(display_text(sid))}</code></li>'
            for sid in unverified
        ) or '<li class="grader-claim-flagged">cited sources could not be verified</li>'
        integrity_body = (
            f'<p class="grader-claim-verdict grader-claim-verdict--danger">{escape(_public_grader_label("CLAIM_UNVERIFIED"))}</p>'
            f'<ul class="grader-claim-list">{flagged}</ul>'
        )
    else:
        integrity_body = (
            f'<p class="grader-claim-verdict">{escape(_public_grader_label(verdict or "CLAIM_OK"))}</p>'
            '<p class="grader-trace-empty">Cited sources align with the available source trail.</p>'
        )

    columns = f"""
      <div class="grader-data-columns">
        <div class="grader-column">
          <p class="grader-column-head">{escape(_public_grader_label("BRAIN QUERIES // TRACE"))}</p>
          <ul class="grader-trace-list">{query_items}</ul>
        </div>
        <div class="grader-column">
          <p class="grader-column-head">{escape(_public_grader_label("SOURCES CONSULTED"))}</p>
          <ul class="grader-trace-list">{source_items}</ul>
        </div>
        <div class="grader-column">
          <p class="grader-column-head">{escape(_public_grader_label("OUTPUT MANIFEST"))}</p>
          <ul class="grader-spark-list">{manifest_items}</ul>
        </div>
        <div class="grader-column{' grader-column--danger' if is_unverified else ''}">
          <p class="grader-column-head">{escape(_public_grader_label("CLAIM INTEGRITY // AUDIT"))}</p>
          {integrity_body}
        </div>
      </div>"""

    # The humanized per-inspector one-liners (printed verbatim from headline).
    headline_inspectors = _as_mappings(headline.get("inspectors"))
    inspector_lines = "".join(
        f'<li class="grader-verdict-line"><b>{escape(_public_grader_name(h.get("name")))}</b>'
        f'<span class="grader-verdict-token">{escape(_public_grader_label(h.get("verdict")))}</span>'
        f'<span class="grader-verdict-copy">{escape_prose(_public_grader_copy(h.get("line")))}</span></li>'
        for h in headline_inspectors
    )
    verdict_summary = (
        f'<ul class="grader-verdict-lines">{inspector_lines}</ul>' if inspector_lines else ''
    )

    # The two-layer raw-audit drawer (reuses the existing persisted-<details>
    # handler verbatim — NO _script() change, NO new JS).
    try:
        raw_audit = json.dumps(_humanized_audit_keys(detail), indent=2, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        raw_audit = ""
    raw_drawer = (
        f"""
      <details class="drawer grader-detail-drawer" data-persist="grader-detail">
        <summary>Show technical detail</summary>
        <pre class="grader-raw-audit">{escape(raw_audit)}</pre>
      </details>"""
        if raw_audit
        else ""
    )

    return f"""
    <section class="dossier-section" id="grader" data-nav-section data-nav-label="Quality Check" data-jump-target>
      {_section_heading("grader", "Readiness Check", "How the pack holds together", "A source-trail check reads the pack structure and keeps technical records folded behind details.", pack=pack)}
      {hero_band}
      {verdict_summary}
      {columns}
      {raw_drawer}
      {_grader_colophon(inspectors)}
    </section>"""


def _humanized_audit_keys(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            display_text(key).replace("_", " "): _humanized_audit_keys(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_humanized_audit_keys(item) for item in value]
    return value


def _copy_console(pack: Mapping[str, Any]) -> str:
    blocks_by_route: dict[str, list[Mapping[str, Any]]] = {}
    global_blocks: list[Mapping[str, Any]] = []
    for block in _as_mappings(pack.get("copy_blocks")):
        route_id = display_text(block.get("route_id"))
        if route_id:
            blocks_by_route.setdefault(route_id, []).append(block)
        else:
            global_blocks.append(block)
    route_panels = []
    routes = pack_routes(pack)
    for index, route in enumerate(routes):
        route_id = _route_id(route, f"route-{index + 1}")
        hidden = "" if index == 0 else " hidden"
        route_blocks = blocks_by_route.get(route_id, [])
        title = display_text(route.get("title"), fallback=f"Route {index + 1}")
        route_summary = _public_handoff_text(route.get("rationale") or route.get("subhead") or route.get("headline"))
        sections = _as_mappings(route.get("sections"))
        section_rows = "".join(
            f"<li><b>{escape(display_text(section.get('title'), fallback=f'Moment {section_index}'))}</b><span>{escape(_public_handoff_text(section.get('body')))}</span></li>"
            for section_index, section in enumerate(sections[:3], start=1)
        )
        visual_read = _public_handoff_text(
            route.get("visual_read")
            or route.get("visualRead")
            or route.get("image_direction")
            or route_summary
        )
        typography_color = pack.get("typography_color") if isinstance(pack.get("typography_color"), Mapping) else {}
        type_direction = _public_handoff_text(
            route.get("type"),
            fallback=display_text(typography_color.get("type_system")),
        )
        first_build = display_text(sections[0].get("title") if sections else "", fallback="First build moment")
        route_brief = "\n\n".join(
            part
            for part in (
                title,
                route_summary,
                f"First build moment: {first_build}",
                f"Visual read: {visual_read}" if visual_read else "",
                f"Type direction: {type_direction}" if type_direction else "",
            )
            if part
        )
        primary = (
            f'<button class="copy-button primary-copy" type="button" data-copy="{escape(route_brief, quote=True)}">Copy route brief</button>'
            if route_brief
            else ""
        )
        details = []
        for block in route_blocks:
            text = display_text(block.get("text"))
            kind = display_text(block.get("kind"))
            label = _internal_copy_label(block)
            details.append(
                f"""
                <details class="copy-block is-receipt-detail" data-copy-kind="{escape(kind, quote=True)}" data-filter-item>
                  <summary>{escape(label)}</summary>
                  <pre>{escape(text)}</pre>
                  <button class="copy-button" type="button" data-copy="{escape(text, quote=True)}">Copy internal text</button>
                </details>"""
            )
        route_panels.append(
            f"""
            <section class="route-copy-panel" data-route-panel="{escape(route_id, quote=True)}"{hidden}>
              <div class="selected-route-handoff">
                <p class="kicker">Selected route brief</p>
                <h3>{escape(title)}</h3>
                <p>{escape(route_summary)}</p>
                {f'<ul class="handoff-route-moments">{section_rows}</ul>' if section_rows else ''}
                <dl class="handoff-direction-list">
                  <div><dt>First build</dt><dd>{escape(first_build)}</dd></div>
                  {f'<div><dt>Visual read</dt><dd>{escape(visual_read)}</dd></div>' if visual_read else ''}
                  {f'<div><dt>Type direction</dt><dd>{escape(type_direction)}</dd></div>' if type_direction else ''}
                </dl>
                <div class="primary-copy-row">{primary}</div>
              </div>
              <div class="copy-console">{''.join(details)}</div>
            </section>"""
        )
    global_rendered = []
    for block in global_blocks:
        text = display_text(block.get("text"))
        label = _internal_copy_label(block)
        global_rendered.append(
            f"""
            <details class="copy-block global-copy-block is-receipt-detail" data-copy-kind="{escape(display_text(block.get("kind")), quote=True)}" data-filter-item>
              <summary>{escape(label)}</summary>
              <pre>{escape(text)}</pre>
              <button class="copy-button" type="button" data-copy="{escape(text, quote=True)}">Copy internal text</button>
            </details>"""
        )
    # HGW-01: each next_step renders as a next-step SELECTOR with copyable handoff text
    # (D-03) and the Local-view-only honesty label (D-02). These are honest local UI — the
    # page never re-runs the director; the user pastes the handoff into a London session.
    step_selectors = []
    for step in _as_mappings(pack.get("next_steps")):
        label = display_text(step.get("label"))
        description = display_text(step.get("description"))
        handoff = (
            f"Next step for London: {label}\n\n{description}\n\n"
            "Paste this into a London session to act on it."
        ).strip()
        step_selectors.append(
            f"""
            <li class="next-step-selector" data-filter-item>
              <div class="next-step-body">
                <b>{escape(label)}</b>
                <span>{escape(description)}</span>
              </div>
              <button class="copy-button next-step-copy" type="button" data-copy="{escape(handoff, quote=True)}">Copy handoff</button>
              <p class="next-step-note">Local view only: not saved, not sent to London.</p>
            </li>"""
        )
    steps = "".join(step_selectors)
    session_summary = """
      <section class="session-summary-link" aria-label="London session summary">
        <p class="kicker">London session summary</p>
        <h3>Decisions And Evidence Companion</h3>
        <p>Open the human-readable session summary for London’s decisions, reasoning, and compact provenance.</p>
        <a class="toolbar-action" href="london-session.json">Open session summary</a>
      </section>"""
    return f"""
    <section class="dossier-section" id="handoff" data-nav-section data-nav-label="Handoff" data-jump-target>
      {_section_heading("handoff", "Copy / Handoff Console", "Route Briefs And Next Moves", pack=pack)}
      <p class="honesty-note">Local view only: not saved, not sent to London. Paste the handoff text into a London session to act.</p>
      <div class="handoff-layout">
        <aside class="next-action-dock">
          <h3>Next Steps</h3>
          <ul class="next-step-list">{steps}</ul>
        </aside>
        <div>
          {session_summary}
          {''.join(route_panels)}
          <section class="global-copy-console">
            <h3>Internal Support Artifacts</h3>
            <div class="copy-console">{''.join(global_rendered)}</div>
          </section>
        </div>
      </div>
    </section>"""


def _internal_copy_label(block: Mapping[str, Any]) -> str:
    kind = display_text(block.get("kind"))
    if kind == "image_prompt":
        return "Internal image direction artifact"
    if kind == "builder_prompt":
        return "Internal prototype build artifact"
    if kind == "critique_prompt":
        return "Internal critique artifact"
    if kind == "source_research":
        return "Internal source research artifact"
    if kind == "ask_london":
        return "Ask London follow-up"
    if kind == "css_variables":
        return display_text(block.get("label"), fallback="Route CSS variables")
    if kind == "route_summary":
        return display_text(block.get("label"), fallback="Route summary")
    return display_text(block.get("label"), fallback="Internal support artifact")


def _public_handoff_text(value: Any, *, fallback: str = "") -> str:
    text = display_text(value, fallback=fallback)
    if not text:
        return ""
    replacements = {
        "receipts": "evidence notes",
        "receipt": "evidence note",
        "proof": "evidence",
        "proofs": "evidence",
        "provider": "source",
        "hashes": "audit ids",
        "hash": "audit id",
    }
    return replacements.get(text.lower(), text)


def _public_source_target_note(value: Any) -> str:
    text = _public_handoff_text(value)
    if not text:
        return ""
    text = re.sub(
        r"not treated as live evidence without an? evidence note",
        "stays planned until the source trail confirms it",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"not treated as live evidence without an? source-trail record",
        "stays planned until the source trail confirms it",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"source browsing evidence note not present",
        "source trail not completed yet",
        text,
        flags=re.I,
    )
    return text


def _public_source_claim(value: Any) -> str:
    text = _public_handoff_text(value)
    if not text:
        return ""
    if "Live Artifacts" in text and "Source targets are planned" in text:
        return (
            "This pack separates London Brain Findings, Source Targets, and live route assets. "
            "Source targets stay planned until the source trail confirms a completed reference or image asset."
        )
    replacements = {
        "Live Artifacts": "live route assets",
        "Live Artifact": "live route asset",
        "live artifact": "live route asset",
        "live evidence note": "completed source note",
        "generated work": "completed image asset",
        "fetched": "completed",
    }
    for old, new in replacements.items():
        text = re.sub(rf"\b{re.escape(old)}\b", new, text, flags=re.IGNORECASE)
    return text


def _receipts(pack: Mapping[str, Any]) -> str:
    receipts = "".join(
        f"<li><b>{escape(display_text(receipt.get('kind')))}</b><span>{escape(display_text(receipt.get('provider')))} / {escape(display_text(receipt.get('summary')))}</span></li>"
        for receipt in _as_mappings(pack.get("receipts"))
    )
    return f"""
    <section class="dossier-section" id="receipts" data-nav-section data-nav-label="Audit" data-jump-target>
      {_section_heading("receipts", "Run Records", "Source Trail", pack=pack)}
      <details class="drawer" data-persist="receipts-debug">
        <summary>Open run records</summary>
        <ul class="source-list">{receipts}</ul>
      </details>
    </section>"""


def _dossier_toolbar(pack: Mapping[str, Any]) -> str:
    title = clean_title(pack, fallback="London Pack")
    return f"""
    <header class="dossier-toolbar" aria-label="Pack toolbar">
      <div class="toolbar-left">
        <a class="toolbar-control" href="#moodboard" aria-label="Back to top" title="Back to top">&lsaquo;</a>
        <span class="toolbar-title">{escape(title)}</span>
      </div>
      <div class="toolbar-actions">
        <button class="toolbar-action" type="button" data-command-open aria-controls="dossier-command-palette" aria-keyshortcuts="Meta+K Control+K">Jump ⌘K</button>
        <button class="toolbar-action toolbar-menu-button" type="button" data-mobile-toggle aria-controls="dossier-mobile-drawer" aria-expanded="false" aria-label="Open navigation">☰ Menu</button>
        <a class="toolbar-action" href="#routes" data-toolbar-action="routes">Routes</a>
        <a class="toolbar-action" href="#handoff" data-toolbar-action="handoff">Handoff</a>
      </div>
    </header>"""


def _dossier_subnav() -> str:
    links = "".join(
        f"""<a class="subnav-link" href="#{escape(anchor, quote=True)}" data-nav-section="{escape(anchor, quote=True)}" data-nav-label="{escape(label, quote=True)}">{escape(label)}</a>"""
        for anchor, label in _SECTIONS
    )
    return f"""
    <nav class="dossier-subnav" aria-label="Section navigation">
      <div class="subnav-row">{links}</div>
    </nav>"""


def _resource_text(name: str) -> str:
    return files(__package__).joinpath(name).read_text(encoding="utf-8")


def _style(extra_css: str = "") -> str:
    css = _resource_text("style.css")
    font_css = f"{extra_css}\n" if extra_css else ""
    css = css.replace("__LONDON_FONT_FACE_CSS__", font_css, 1)
    return f"""
    <style>
{css.rstrip()}
    </style>"""


def _script() -> str:
    js = _resource_text("script.js").rstrip()
    return f"""
    <script>
{js}
    </script>"""


def render_dossier(pack: Mapping[str, Any]) -> str:
    """Render a static Pack Reader / Creative Moodboard Workbench."""

    prepared = _prepared_pack(pack)
    title = clean_title(prepared, fallback="London Pack")
    persist_prefix = slugify(display_text(prepared.get("pack_id")) or title) or "pack"
    routes = pack_routes(prepared)

    # Build the shared navigation model ONCE (TPL-06 / NAV-01) — the same builder the
    # prototype consumes, with surface="dossier" so the primary sections match the
    # visual-first _SECTIONS order. The left rail, ⌘K palette, mobile drawer, and
    # route switcher are all derived from this one model.
    navigation = build_navigation(routes, routes[0], surface="dossier") if routes else build_navigation(routes, {}, surface="dossier")

    # Build the section DOM strictly in _SECTIONS order so the two order sources
    # (the _SECTIONS metadata that drives the subnav/scroll-spy AND the rendered
    # DOM) cannot drift (TPL-01 / 04-RESEARCH Pitfall 1). Each anchor maps to its
    # section helper; the loop emits them in _SECTIONS order. The "routes" anchor
    # is the route-dossiers block (it carries id="routes"); "handoff" is the copy
    # console (id="handoff"). The command-center console + light overview band sit
    # ABOVE the loop and are NOT in _SECTIONS (the console header is not a nav
    # section; the overview band's facts relocated there).
    _section_helpers = {
        "moodboard": lambda: _moodboard(prepared),
        "routes": lambda: _route_dossiers(
            prepared,
            routes,
            _as_mappings(prepared.get("route_comparison")),
            _as_mappings(prepared.get("moodboard_tiles")),
            navigation,
        ),
        "comparison": lambda: _comparison(prepared),
        "font-lab": lambda: _font_lab(prepared),
        "conversation": lambda: _conversation(prepared),
        "constraints": lambda: _constraint_legend(prepared),
        "evidence": lambda: _evidence(prepared),
        "grader": lambda: _grader_section(prepared),
        "handoff": lambda: _copy_console(prepared),
        "receipts": lambda: _receipts(prepared),
    }
    sections_html = "\n        ".join(_section_helpers[anchor]() for anchor, _ in _SECTIONS)
    font_face_css = font_face_css_for_groups(_as_mappings(prepared.get("font_options")))

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} - London Pack Reader</title>
  {_style(font_face_css)}
</head>
<body data-persist-prefix="{escape(persist_prefix, quote=True)}">
  <a class="dossier-skip-link" href="#moodboard">Skip to moodboard</a>
  <main class="dossier-shell">
    {_dossier_toolbar(prepared)}
    {_dossier_subnav()}
    <div class="dossier-layout">
      {_render_left_rail(navigation)}
      <div class="dossier-content">
        {_command_center(prepared, routes)}
        {_executive_summary(prepared, routes)}
        {_dossier_header(prepared, routes)}
        {_recommendation_panel(prepared, routes)}
        {sections_html}
      </div>
    </div>
  </main>
  {_render_mobile_drawer(navigation)}
  {_render_command_palette(navigation)}
  <div class="lightbox" id="lightbox" hidden role="dialog" aria-modal="true" aria-hidden="true" aria-label="System sketch preview">
    <div class="lightbox-inner">
      <button class="lightbox-close" type="button" aria-label="Close preview">Close</button>
      <figure>
        <img alt="">
        <figcaption>System sketch</figcaption>
      </figure>
    </div>
  </div>
  {_script()}
</body>
</html>
"""


def write_dossier(pack: Mapping[str, Any], path: str | Path) -> Path:
    """Write a workbench HTML file and return its path."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_dossier(pack), encoding="utf-8")
    return output_path
