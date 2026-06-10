from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any, Mapping, Sequence

from .assets import normalize_palette, normalize_tags, pack_routes, route_assets
from .dossier.shared import (
    _as_mappings,
    _clip_detail,
    _prepared_pack,
    _provider_label,
    _public_type_rationale,
    _render_type_roles,
)
from .font_preview import font_face_css_for_groups, resolve_font_preview
from .navigation import (
    PrototypeNavigation,
    PrototypeNavLink,
    PrototypeRouteNav,
    build_prototype_navigation,
    prototype_route_id,
)
from .route_refs import resolve_route_ref
from .safe_urls import safe_href
from .text import clean_title, display_text


def _pick_route(pack: Mapping[str, Any], route_id: str | None = None) -> dict[str, Any]:
    routes = pack_routes(pack)
    if route_id:
        for route in routes:
            if str(route.get("id") or "") == route_id:
                return route
    else:
        matched = resolve_route_ref(pack.get("recommended_route_ref"), routes)
        if matched:
            return dict(matched)
    return routes[0]


def _css_vars(route: Mapping[str, Any], font_stack: str) -> str:
    palette = normalize_palette(route.get("palette"))
    names = ["--surface", "--paper", "--accent", "--ink", "--signal"]
    declarations = [f"--font-headline: {font_stack};"]
    for name, color in zip(names, palette, strict=False):
        declarations.append(f"{name}: {color['hex']};")
    return " ".join(declarations)


def _prototype_asset_src(src: str) -> str:
    safe = safe_href(src)
    if safe.startswith("assets/"):
        return f"../{safe}"
    return safe_href(safe, allow_parent_assets=True)


def _asset_is_live(asset: Mapping[str, Any]) -> bool:
    return bool(asset.get("live_artifact")) or not bool(asset.get("deterministic", True))


def _asset_display_title(asset: Mapping[str, Any], fallback: str) -> str:
    title = display_text(asset.get("title"), fallback=fallback)
    kind = display_text(asset.get("kind"))
    if kind in {"manual-prompt-card", "generation-unavailable", "visual-direction-board"}:
        return title
    if not _asset_is_live(asset) and "system sketch" not in title.lower():
        return f"{title} local system sketch"
    return title


def _asset_provenance_caption(asset: Mapping[str, Any]) -> str:
    kind = display_text(asset.get("kind"))
    if kind == "manual-prompt-card":
        return "image direction prompt"
    if kind == "generation-unavailable":
        return "image direction unavailable"
    if kind == "visual-direction-board":
        return "internal visual direction board"
    if kind == "fixture-system-sketch":
        return "system sketch"
    if _asset_is_live(asset):
        return "route concept image"
    return "system sketch"


def _asset_compact_caption(asset: Mapping[str, Any]) -> str:
    kind = display_text(asset.get("kind"))
    if kind == "generated-concept-image" or _asset_is_live(asset):
        return "Route concept image"
    if kind == "visual-direction-board":
        return "Internal visual direction board"
    if kind == "generation-unavailable":
        return "Image direction unavailable"
    if kind == "manual-prompt-card":
        return "Image direction prompt"
    if kind == "fixture-system-sketch":
        return "System sketch"
    return "Route visual"


def _text_words(value: str) -> list[str]:
    return [part for part in value.replace("\n", " ").split(" ") if part]


def _statement_mode(value: str, *, long_chars: int, long_words: int) -> str:
    text = " ".join(_text_words(value))
    if len(text) > long_chars or len(_text_words(text)) > long_words:
        return "editorial"
    return "poster"


def _has_meaningful_constraint_payload(values: Sequence[str]) -> bool:
    meaningful = [
        value
        for value in values
        if len(value.strip()) >= 28 or len(_text_words(value)) >= 5
    ]
    return len(meaningful) >= 2


def _font_option(pack: Mapping[str, Any], route: Mapping[str, Any]) -> Mapping[str, Any]:
    route_id = _route_id(route)
    for group in _as_mappings(pack.get("font_options")):
        if display_text(group.get("route_id")) != route_id:
            continue
        options = _as_mappings(group.get("options"))
        for option in options:
            if resolve_font_preview(option).is_actual_loaded:
                return option
        for option in options:
            if display_text(option.get("tier")) == "open_public":
                return option
        for option in options:
            if display_text(option.get("tier")) == "safe_local":
                return option
        return options[0] if options else {}
    return {}


def _type_read(route: Mapping[str, Any], option: Mapping[str, Any], preview) -> tuple[str, str, str, str]:
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


def _type_read_paragraphs(rationale: str, best_use: str) -> str:
    paragraphs = []
    if rationale:
        paragraphs.append(f'<p class="prototype-type-note">{escape(rationale)}</p>')
    if best_use:
        paragraphs.append(f'<p class="prototype-type-use">{escape(best_use)}</p>')
    return "".join(paragraphs)


def _render_font_proof_details(preview) -> str:
    source = display_text(preview.source_label)
    license_note = display_text(preview.license_note)
    if not source and not license_note:
        return ""
    summary = escape(_clip_detail(source or license_note, 96))
    detail_rows = []
    if source:
        detail_rows.append(("Source", source))
    if license_note:
        detail_rows.append(("License / proof", license_note))
    rows = "".join(
        f"<div><dt>{escape(label)}</dt><dd>{escape(value)}</dd></div>"
        for label, value in detail_rows
    )
    return f"""
      <details class="prototype-receipt-detail">
        <summary>{summary}</summary>
        <dl>{rows}</dl>
      </details>"""


def _render_asset_figure(
    asset: Mapping[str, Any],
    *,
    class_name: str,
    fallback_title: str,
    compact_caption: bool = False,
) -> str:
    src = display_text(asset.get("src"))
    kind = display_text(asset.get("kind"))
    visual_state = "generated" if kind == "generated-concept-image" else ("system-sketch" if kind == "fixture-system-sketch" else kind)
    title = _asset_display_title(asset, fallback_title)
    caption = _asset_provenance_caption(asset)
    provider_label = _provider_label(display_text(asset.get("provider"), fallback="local generator"))
    visible_caption = _asset_compact_caption(asset) if compact_caption else f"{title} / {caption}"
    if src:
        hero_src = _prototype_asset_src(src)
        if hero_src:
            return f"""
              <figure class="{class_name}" data-visual-state="{escape(visual_state, quote=True)}" data-provider-label="{escape(provider_label, quote=True)}" aria-label="{escape(f'{title}. {caption}', quote=True)}">
                <img src="{escape(hero_src, quote=True)}" alt="{escape(display_text(asset.get('alt'), fallback=title), quote=True)}">
                <figcaption>{escape(visible_caption)}</figcaption>
              </figure>"""
    prompt = display_text(asset.get("prompt"), fallback="No generator was ready. Use the route brief and London notes as the image prompt.")
    prompt_summary = _clip_detail(prompt, 150)
    copy_label = display_text(asset.get("copy_label"), fallback="Copy image prompt")
    return f"""
      <figure class="{class_name} prototype-prompt-card" data-visual-state="{escape(visual_state, quote=True)}">
        <p class="prototype-eyebrow">{escape(display_text(asset.get("kind"), fallback="manual-prompt-card").replace("-", " "))}</p>
        <h3>{escape(title)}</h3>
        <p>{escape(prompt_summary)}</p>
        <details class="prototype-receipt-detail">
          <summary>Full image prompt</summary>
          <pre>{escape(prompt)}</pre>
        </details>
        <button type="button" data-copy="{escape(prompt, quote=True)}">{escape(copy_label)}</button>
        <figcaption>{escape(caption)}</figcaption>
      </figure>"""


def _route_id(route: Mapping[str, Any]) -> str:
    return prototype_route_id(route)


def _font_stack(pack: Mapping[str, Any], route: Mapping[str, Any]) -> str:
    return _font_preview(pack, route).css_stack


def _font_preview(pack: Mapping[str, Any], route: Mapping[str, Any]):
    option = _font_option(pack, route)
    if option:
        return resolve_font_preview(option)
    return resolve_font_preview(
        {
            "tier": "safe_local",
            "fallback_stack": "Arial, Helvetica, sans-serif",
            "headline_font": "Prototype system fallback",
        }
    )


def _route_comparison(pack: Mapping[str, Any], route: Mapping[str, Any]) -> Mapping[str, Any]:
    route_id = _route_id(route)
    for row in _as_mappings(pack.get("route_comparison")):
        if display_text(row.get("route_id")) == route_id:
            return row
    return {}


def _moodboard_tiles(pack: Mapping[str, Any], route: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    route_id = _route_id(route)
    for group in _as_mappings(pack.get("moodboard_tiles")):
        if display_text(group.get("route_id")) == route_id:
            return _as_mappings(group.get("tiles"))
    return []


def _render_palette(route: Mapping[str, Any]) -> str:
    return "".join(
        f"""<li>
          <span style="background:{escape(color['hex'], quote=True)}"></span>
          <b>{escape(color['role'])}</b>
          <em>{escape(color['hex'])}</em>
        </li>"""
        for color in normalize_palette(route.get("palette"))
    )


def _nav_section_attrs(link: PrototypeNavLink) -> str:
    return (
        f'id="{escape(link.id, quote=True)}" '
        f'data-nav-section="{escape(link.id, quote=True)}" '
        f'data-nav-kind="{escape(link.kind, quote=True)}" '
        f'data-nav-route="{escape(link.route_id, quote=True)}" '
        f'data-nav-route-title="{escape(link.route_title, quote=True)}" '
        f'data-nav-label="{escape(link.label, quote=True)}" '
        'tabindex="-1"'
    )


def _render_nav_link(link: PrototypeNavLink, *, class_name: str = "", current: bool = False) -> str:
    class_attr = f' class="{escape(class_name, quote=True)}"' if class_name else ""
    current_attr = ' aria-current="location"' if current else ""
    return (
        f'<a{class_attr} href="#{escape(link.id, quote=True)}" '
        f'data-nav-link="{escape(link.id, quote=True)}" '
        f'data-nav-route="{escape(link.route_id, quote=True)}" '
        f'data-nav-kind="{escape(link.kind, quote=True)}"{current_attr}>'
        f"{escape(link.label)}</a>"
    )


def _prototype_moments(route: Mapping[str, Any], tiles: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    sections = _as_mappings(route.get("sections"))
    if sections:
        return [
            {
                "title": display_text(section.get("title"), fallback=f"Moment {index}"),
                "body": display_text(section.get("body")),
                "eyebrow": display_text(section.get("eyebrow"), fallback=f"Moment {index:02d}"),
            }
            for index, section in enumerate(sections, start=1)
        ][:4]
    return [
        {
            "title": display_text(tile.get("title"), fallback=f"Moment {index}"),
            "body": display_text(tile.get("caption")),
            "eyebrow": display_text(tile.get("kind"), fallback=f"Moment {index:02d}").replace("-", " "),
        }
        for index, tile in enumerate(tiles[:3], start=1)
    ]


def _render_moments(moments: Sequence[Mapping[str, str]], moment_links: Sequence[PrototypeNavLink]) -> str:
    rendered = []
    for index, moment in enumerate(moments[:4], start=1):
        link = moment_links[index - 1]
        rendered.append(
            f"""
            <section class="prototype-moment" {_nav_section_attrs(link)}>
              <p class="prototype-eyebrow">{escape(moment["eyebrow"])}</p>
              <h2>{escape(moment["title"])}</h2>
              <p>{escape(moment["body"])}</p>
              <span>{index:02d}</span>
            </section>"""
        )
    return "\n".join(rendered)


def _render_primary_jumps(navigation: PrototypeNavigation) -> str:
    return "".join(
        _render_nav_link(link, class_name="prototype-top-link", current=link.id == "overview")
        for link in navigation.primary_sections
        if link.id in {"overview", "routes", "route-sections", "handoff"}
    )


def _render_nav_group(title: str, links: Sequence[PrototypeNavLink], *, include_eyebrow: bool = False) -> str:
    rendered_links = "".join(
        f"""
        <a href="#{escape(link.id, quote=True)}" data-nav-link="{escape(link.id, quote=True)}" data-nav-route="{escape(link.route_id, quote=True)}" data-nav-kind="{escape(link.kind, quote=True)}">
          {f'<span>{escape(link.eyebrow)}</span>' if include_eyebrow else ''}
          <b>{escape(link.label)}</b>
        </a>"""
        for link in links
    )
    return f"""
      <section class="prototype-nav-group">
        <p>{escape(title)}</p>
        {rendered_links}
      </section>"""


def _render_nav_map(navigation: PrototypeNavigation) -> str:
    groups = [
        _render_nav_group("Prototype", navigation.primary_sections, include_eyebrow=True),
    ]
    if navigation.current_moments:
        groups.append(_render_nav_group("Current route moments", navigation.current_moments, include_eyebrow=True))
    for index, route in enumerate(navigation.routes, start=1):
        groups.append(_render_nav_group(f"Route {index:02d}", (route.panel, *route.sections), include_eyebrow=True))
    return "\n".join(groups)


def _render_left_rail(navigation: PrototypeNavigation) -> str:
    return f"""
    <nav class="prototype-left-rail" aria-label="Prototype route and section map">
      {_render_nav_map(navigation)}
    </nav>"""


def _render_mobile_drawer(navigation: PrototypeNavigation) -> str:
    return f"""
    <div class="prototype-mobile-drawer" id="prototype-mobile-drawer" data-mobile-drawer hidden>
      <nav aria-label="Mobile prototype route and section map">
        {_render_nav_map(navigation)}
      </nav>
    </div>"""


def _render_command_palette(navigation: PrototypeNavigation) -> str:
    items = "".join(
        f"""
        <a href="#{escape(link.id, quote=True)}" data-command-item data-nav-link="{escape(link.id, quote=True)}" data-command-key="{escape((link.eyebrow + ' ' + link.label + ' ' + link.route_title).lower(), quote=True)}">
          <span>{escape(link.eyebrow)}</span>
          <b>{escape(link.label)}</b>
        </a>"""
        for link in navigation.all_links
    )
    return f"""
    <div class="prototype-command-palette" id="prototype-command-palette" data-command-palette role="dialog" aria-modal="true" aria-label="Prototype command palette" hidden>
      <div class="prototype-command-panel">
        <div class="prototype-command-search">
          <input id="prototype-command-input" data-command-search type="search" autocomplete="off" placeholder="Search routes and sections">
          <button type="button" data-command-close>Close</button>
        </div>
        <div class="prototype-command-list" data-command-list>{items}</div>
      </div>
    </div>"""


def _render_route_switcher(navigation: PrototypeNavigation) -> str:
    tabs = "".join(
        f"""
        <a href="#{escape(route.panel.id, quote=True)}" role="tab" aria-selected="{str(route.id == navigation.current_route_id).lower()}" data-prototype-route-tab="{escape(route.id, quote=True)}" data-nav-route-tab="{escape(route.id, quote=True)}" data-nav-link="{escape(route.panel.id, quote=True)}">
          <span>Route {index:02d}</span>
          <b>{escape(route.title)}</b>
        </a>"""
        for index, route in enumerate(navigation.routes, start=1)
    )
    return f'<div class="prototype-route-switcher" role="tablist" aria-label="Prototype routes">{tabs}</div>'


def _render_route_cards(routes: Sequence[Mapping[str, Any]], route_nav: Sequence[PrototypeRouteNav]) -> str:
    rendered = []
    for index, (item, nav_route) in enumerate(zip(routes, route_nav, strict=False), start=1):
        section_links = "".join(_render_nav_link(section, class_name="prototype-route-section-link") for section in nav_route.sections)
        rendered.append(
            f"""
            <article>
              <p class="prototype-eyebrow">Route {index:02d}</p>
              <h3>{escape(nav_route.title)}</h3>
              <p>{escape(display_text(item.get("headline") or item.get("rationale")))}</p>
              {_render_nav_link(nav_route.panel, class_name="prototype-route-jump")}
              <div class="prototype-route-section-jumps">{section_links}</div>
            </article>"""
        )
    return "".join(rendered)


def _render_tile_strip(tiles: Sequence[Mapping[str, Any]]) -> str:
    rendered = []
    for tile in tiles[:5]:
        rendered.append(
            f"""
            <li>
              <b>{escape(display_text(tile.get("kind")).replace("-", " "))}</b>
              <span>{escape(display_text(tile.get("title")))}</span>
            </li>"""
        )
    return "".join(rendered)


def _render_route_panel(pack: Mapping[str, Any], route: Mapping[str, Any], route_nav: PrototypeRouteNav) -> str:
    route_key = _route_id(route)
    route_title = display_text(route.get("title") or route.get("name"), fallback="Prototype Route")
    title_mode = _statement_mode(route_title, long_chars=46, long_words=7)
    panel_class = f"prototype-route-panel prototype-route-panel--{title_mode}-title"
    assets = route_assets(route)
    hero = assets[0]
    sections = _as_mappings(route.get("sections"))
    palette = normalize_palette(route.get("palette"))
    font_option = _font_option(pack, route)
    font_preview = _font_preview(pack, route)
    type_family, type_direction, type_rationale, type_best_use = _type_read(route, font_option, font_preview)
    type_role_rows = _render_type_roles(type_direction)
    type_notes = _type_read_paragraphs(type_rationale, type_best_use)
    font_proof_details = _render_font_proof_details(font_preview)
    section_rows = []
    for index, section in enumerate(sections, start=1):
        link = route_nav.sections[index - 1]
        section_rows.append(
            f"""
            <article {_nav_section_attrs(link)}>
              <span>{index:02d}</span>
              <h3>{escape(display_text(section.get("title"), fallback=f"Section {index}"))}</h3>
              <p>{escape(display_text(section.get("body")))}</p>
            </article>"""
        )
    color_rows = "".join(
        f"<li><span style=\"background:{escape(color['hex'], quote=True)}\"></span><b>{escape(color['name'])}</b></li>"
        for color in palette
    )
    return f"""
    <article class="{panel_class}" {_nav_section_attrs(route_nav.panel)} data-prototype-route-panel="{escape(route_key, quote=True)}">
      <div>
        <p class="prototype-eyebrow">Route Panel</p>
        <h2>{escape(route_title)}</h2>
        <p>{escape(display_text(route.get("rationale") or route.get("subhead")))}</p>
        <ul class="prototype-panel-colors">{color_rows}</ul>
        <h3 class="prototype-type-family">{escape(type_family)}</h3>
        {type_notes}
        <dl class="prototype-type-roles">{type_role_rows}</dl>
        {font_proof_details}
      </div>
      {_render_asset_figure(hero, class_name="prototype-panel-visual", fallback_title="Route visual handoff")}
      <div class="prototype-section-list">
        {"".join(section_rows)}
      </div>
    </article>"""


def render_static_prototype(pack: Mapping[str, Any], route_id: str | None = None) -> str:
    """Render one first-pass static prototype route from a London Pack."""

    prepared = _prepared_pack(pack)
    routes = pack_routes(prepared)
    route = _pick_route(prepared, route_id)
    route_key = _route_id(route)
    assets = route_assets(route)
    hero = assets[0]
    title = escape(clean_title(prepared, fallback="London Prototype"))
    route_title_raw = display_text(route.get("title") or route.get("name"), fallback="Prototype Route")
    route_title = escape(route_title_raw)
    headline_raw = display_text(route.get("headline") or route.get("thesis"), fallback=route_title_raw)
    headline = escape(headline_raw)
    subhead_raw = display_text(route.get("subhead") or route.get("rationale"), fallback="A route-specific first pass generated from the London Pack.")
    subhead = escape(subhead_raw)
    tags = normalize_tags(route.get("tags"), defaults=("first pass", "London route"))
    font_stack = _font_stack(prepared, route)
    comparison = _route_comparison(prepared, route)
    tiles = _moodboard_tiles(prepared, route)
    moments = _prototype_moments(route, tiles)
    navigation = build_prototype_navigation(routes, route, moment_titles=[moment["title"] for moment in moments])
    first_tile = tiles[0] if tiles else {}
    tension = first_tile.get("tension_pair") if isinstance(first_tile.get("tension_pair"), Mapping) else {}
    argument_heading_raw = display_text(comparison.get("first_build_move"), fallback=headline_raw)
    argument_body_raw = display_text(comparison.get("best_for"), fallback=display_text(route.get("rationale")))
    steal_raw = display_text(comparison.get("steal"))
    avoid_raw = display_text(comparison.get("do_not_copy"))
    risk_raw = display_text(comparison.get("risk"))
    steal_value = steal_raw or display_text(tension.get("wants"))
    avoid_value = avoid_raw or display_text(tension.get("avoid"))
    risk_value = risk_raw or "The route fails if the product proof gets generic."
    constraint_rows = [
        ("Steal", steal_value),
        ("Do Not Copy", avoid_value),
        ("Risk", risk_value),
        ("Prototype Role", "First-pass static proof from the London session, ready for visual approval and provider-backed refinement."),
    ]
    argument_mode = _statement_mode(argument_heading_raw, long_chars=64, long_words=10)
    constraints_meaningful = _has_meaningful_constraint_payload([steal_raw, avoid_raw, risk_raw, display_text(tension.get("wants")), display_text(tension.get("avoid"))])
    workbench_modifiers = []
    if argument_mode == "editorial" and not constraints_meaningful:
        workbench_modifiers.append("prototype-workbench--argument-full")
    workbench_class = " ".join(["prototype-workbench", *workbench_modifiers])
    hero_mode = _statement_mode(headline_raw, long_chars=56, long_words=8)
    hero_classes = ["prototype-hero", f"prototype-hero--{hero_mode}"]
    if hero_mode == "editorial":
        hero_classes.append("prototype-hero--long-headline")
    hero_class = " ".join(hero_classes)
    tag_html = "".join(f"<li>{escape(tag)}</li>" for tag in tags)
    font_preview = _font_preview(prepared, route)
    font_option = _font_option(prepared, route)
    font_face_css = font_face_css_for_groups(_as_mappings(prepared.get("font_options")), asset_href_prefix="../")
    type_family, type_direction_raw, type_rationale, type_best_use = _type_read(route, font_option, font_preview)
    type_direction_mode = "is-long-type-direction" if len(type_direction_raw) > 80 else "is-short-specimen"
    type_role_rows = _render_type_roles(type_direction_raw)
    type_notes = _type_read_paragraphs(type_rationale, type_best_use)
    font_proof_details = _render_font_proof_details(font_preview)
    primary_jumps = _render_primary_jumps(navigation)
    mobile_drawer = _render_mobile_drawer(navigation)
    left_rail = _render_left_rail(navigation)
    command_palette = _render_command_palette(navigation)
    route_switcher = _render_route_switcher(navigation)
    route_cards = _render_route_cards(routes, navigation.routes)
    all_route_panels = "\n".join(
        _render_route_panel(prepared, item, nav_route)
        for item, nav_route in zip(routes, navigation.routes, strict=False)
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{route_title} - {title}</title>
  <style>
    :root {{ {_css_vars(route, font_stack)} color-scheme: light; }}
    {font_face_css}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--paper); color: var(--ink); font-family: Arial, Helvetica, sans-serif; overflow-x: hidden; }}
    html {{ scroll-behavior: smooth; }}
    .prototype-route {{ min-height: 100vh; overflow-x: hidden; }}
    [data-nav-section] {{ scroll-margin-top: 92px; outline: none; }}
    [data-nav-section]:target, .is-target-flash {{ animation: prototypeTargetFlash 1.15s ease; }}
    @keyframes prototypeTargetFlash {{
      0% {{ box-shadow: inset 0 0 0 0 var(--signal); }}
      30% {{ box-shadow: inset 0 0 0 8px var(--signal); }}
      100% {{ box-shadow: inset 0 0 0 0 transparent; }}
    }}
    .prototype-skip-link {{ position: fixed; left: 16px; top: 12px; z-index: 80; transform: translateY(-140%); padding: 10px 12px; background: var(--signal); color: var(--ink); border: 2px solid var(--ink); font-weight: 900; }}
    .prototype-skip-link:focus {{ transform: translateY(0); }}
    .prototype-nav {{ position: sticky; top: 0; z-index: 50; display: grid; grid-template-columns: minmax(160px, 0.8fr) minmax(240px, 1fr) auto; gap: 16px; align-items: center; padding: 12px clamp(16px, 4vw, 52px); background: rgba(255, 249, 235, 0.96); color: var(--ink); border-bottom: 2px solid var(--ink); backdrop-filter: blur(12px); }}
    .prototype-brand {{ color: inherit; text-decoration: none; font-family: var(--font-headline); font-size: 1.05rem; line-height: 1; min-width: 0; overflow-wrap: anywhere; }}
    .prototype-current {{ display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 2px 8px; align-items: baseline; min-width: 0; padding: 8px 10px; border-left: 2px solid var(--ink); }}
    .prototype-current span {{ font-size: 0.68rem; text-transform: uppercase; font-weight: 900; }}
    .prototype-current strong {{ min-width: 0; overflow-wrap: anywhere; font-size: 0.86rem; line-height: 1.12; }}
    .prototype-nav-actions {{ display: flex; gap: 8px; align-items: center; justify-content: flex-end; min-width: 0; }}
    .prototype-primary-jumps {{ display: flex; gap: 0; align-items: stretch; border: 1px solid var(--ink); background: var(--paper); }}
    .prototype-top-link, .prototype-nav-button {{ display: inline-flex; align-items: center; min-height: 36px; padding: 8px 10px; color: inherit; background: transparent; border: 0; border-right: 1px solid var(--ink); text-decoration: none; font-size: 0.72rem; font-weight: 900; text-transform: uppercase; cursor: pointer; white-space: nowrap; }}
    .prototype-nav-button {{ border: 1px solid var(--ink); background: var(--signal); font-family: inherit; }}
    .prototype-menu-button {{ display: none; }}
    [data-nav-link][aria-current="location"], [data-nav-route-tab][aria-selected="true"] {{ background: var(--ink); color: var(--paper); }}
    .prototype-layout {{ display: grid; grid-template-columns: minmax(220px, 280px) minmax(0, 1fr); align-items: start; }}
    .prototype-content {{ min-width: 0; }}
    .prototype-left-rail {{ position: sticky; top: 68px; height: calc(100vh - 68px); overflow: auto; padding: 18px 14px 26px; background: var(--paper); border-right: 2px solid var(--ink); }}
    .prototype-nav-group {{ padding: 0 0 16px; margin: 0 0 16px; border-bottom: 1px solid rgba(0, 0, 0, 0.22); }}
    .prototype-nav-group p {{ margin: 0 0 8px; font-size: 0.7rem; text-transform: uppercase; font-weight: 900; }}
    .prototype-nav-group a {{ display: grid; gap: 2px; padding: 8px 9px; color: inherit; text-decoration: none; border-left: 3px solid transparent; }}
    .prototype-nav-group a + a {{ margin-top: 2px; }}
    .prototype-nav-group a span {{ font-size: 0.66rem; text-transform: uppercase; font-weight: 900; opacity: 0.72; }}
    .prototype-nav-group a b {{ font-size: 0.82rem; line-height: 1.14; overflow-wrap: anywhere; }}
    .prototype-mobile-drawer {{ display: none; }}
    .prototype-command-palette {{ position: fixed; inset: 0; z-index: 70; display: grid; place-items: start center; padding: 12vh 20px 20px; background: rgba(21, 21, 21, 0.42); }}
    .prototype-command-palette[hidden] {{ display: none; }}
    .prototype-command-panel {{ width: min(680px, 100%); max-height: 76vh; overflow: hidden; display: grid; grid-template-rows: auto minmax(0, 1fr); background: var(--paper); color: var(--ink); border: 3px solid var(--ink); box-shadow: 14px 14px 0 var(--accent); }}
    .prototype-command-search {{ display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; padding: 12px; border-bottom: 2px solid var(--ink); }}
    .prototype-command-search input {{ width: 100%; min-height: 42px; padding: 9px 10px; border: 2px solid var(--ink); background: #fff; color: inherit; font: inherit; }}
    .prototype-command-search button {{ min-height: 42px; border: 2px solid var(--ink); background: var(--signal); font: inherit; font-weight: 900; cursor: pointer; }}
    .prototype-command-list {{ overflow: auto; padding: 8px; }}
    .prototype-command-list a {{ display: grid; gap: 3px; padding: 10px; color: inherit; text-decoration: none; border-bottom: 1px solid rgba(0, 0, 0, 0.18); }}
    .prototype-command-list a[hidden] {{ display: none; }}
    .prototype-command-list span {{ font-size: 0.68rem; text-transform: uppercase; font-weight: 900; opacity: 0.72; }}
    .prototype-command-list b {{ overflow-wrap: anywhere; }}
    .prototype-hero {{ min-height: calc(100vh - 74px); display: grid; grid-template-columns: minmax(380px, 0.95fr) minmax(420px, 1.05fr); gap: clamp(24px, 3.5vw, 52px); align-items: center; padding: clamp(36px, 4vw, 64px); background: var(--ink); color: var(--paper); border-bottom: 12px solid var(--surface); }}
    .prototype-hero--long-headline {{ grid-template-columns: minmax(420px, 0.9fr) minmax(460px, 1.1fr); }}
    .prototype-eyebrow {{ margin: 0 0 12px; text-transform: uppercase; font-size: 0.76rem; line-height: 1.15; font-weight: 900; letter-spacing: 0; }}
    h1, h2, h3 {{ margin: 0; letter-spacing: 0; }}
    .prototype-hero h1 {{ max-width: min(19ch, 100%); font-family: var(--font-headline); font-size: 4.55rem; line-height: 0.95; overflow-wrap: normal; word-break: normal; text-wrap: balance; }}
    .prototype-hero--long-headline h1 {{ max-width: min(22ch, 100%); font-size: 3.85rem; line-height: 0.98; }}
    .prototype-subhead {{ max-width: 700px; font-size: clamp(1.05rem, 1.8vw, 1.55rem); line-height: 1.36; }}
    .prototype-tags {{ display: flex; flex-wrap: wrap; gap: 8px; padding: 0; margin: 28px 0 0; list-style: none; }}
    .prototype-tags li {{ border: 1px solid currentColor; padding: 7px 10px; font-size: 0.78rem; text-transform: uppercase; font-weight: 900; border-radius: 999px; }}
    .prototype-visual {{ align-self: center; max-height: min(560px, calc(100vh - 170px)); margin: 0; display: grid; grid-template-rows: minmax(0, 1fr) auto; border: 8px solid var(--paper); background: var(--surface); overflow: hidden; box-shadow: 18px 18px 0 var(--accent); }}
    .prototype-visual img {{ width: 100%; max-height: min(500px, calc(100vh - 220px)); aspect-ratio: 16 / 10; object-fit: contain; display: block; background: var(--surface); }}
    .prototype-visual figcaption {{ padding: 8px 10px; background: var(--ink); color: var(--paper); font-size: 0.72rem; line-height: 1.15; font-weight: 900; text-transform: uppercase; }}
    .prototype-prompt-card {{ padding: 18px; display: grid; gap: 12px; color: var(--ink); }}
    .prototype-prompt-card pre {{ white-space: pre-wrap; overflow-wrap: anywhere; max-height: 360px; overflow: auto; padding: 14px; background: var(--paper); border: 2px dashed var(--ink); font: 0.9rem/1.4 Arial, Helvetica, sans-serif; }}
    .prototype-prompt-card button {{ justify-self: start; border: 2px solid var(--ink); border-radius: 6px; background: var(--ink); color: var(--paper); padding: 9px 12px; font-weight: 900; }}
    .prototype-proof {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(280px, 0.48fr); border-bottom: 2px solid var(--ink); }}
    .prototype-palette {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); padding: 0; margin: 0; list-style: none; }}
    .prototype-palette li {{ min-height: 136px; padding: 12px; border-right: 1px solid rgba(0, 0, 0, 0.24); background: #fff; }}
    .prototype-palette span {{ display: block; height: 58px; border: 2px solid var(--ink); margin-bottom: 10px; }}
    .prototype-palette b, .prototype-palette em {{ display: block; font-size: 0.76rem; font-style: normal; }}
    .prototype-type {{ padding: 24px; background: var(--signal); border-left: 2px solid var(--ink); }}
    .prototype-type h2 {{ font-family: var(--font-headline); font-size: clamp(2rem, 4vw, 4.5rem); line-height: 0.94; max-width: min(14ch, 100%); }}
    .prototype-type.is-long-type-direction h2 {{ font-size: clamp(1.8rem, 3.4vw, 3.4rem); max-width: min(18ch, 100%); }}
    .prototype-type-roles {{ display: grid; gap: 8px; margin: 14px 0 0; }}
    .prototype-type-roles div {{ padding: 10px 0; border-top: 1px solid rgba(0, 0, 0, 0.24); }}
    .prototype-type-roles dt {{ margin: 0; font-size: 0.7rem; text-transform: uppercase; font-weight: 900; }}
    .prototype-type-roles dd {{ margin: 5px 0 0; max-width: 68ch; font-size: 0.94rem; line-height: 1.42; }}
    .prototype-moments {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); }}
    .prototype-moment {{ position: relative; min-height: 410px; padding: 34px; border-right: 1px solid rgba(0, 0, 0, 0.22); border-bottom: 1px solid rgba(0, 0, 0, 0.22); background: var(--paper); }}
    .prototype-moment:nth-child(2) {{ background: var(--surface); color: var(--ink); }}
    .prototype-moment:nth-child(3) {{ background: var(--ink); color: var(--paper); }}
    .prototype-moment:nth-child(4) {{ background: var(--accent); color: var(--ink); }}
    .prototype-moment h2 {{ font-family: var(--font-headline); font-size: clamp(2rem, 4vw, 4.2rem); line-height: 0.94; overflow-wrap: break-word; }}
    .prototype-moment p:last-of-type {{ max-width: 36rem; font-size: 1.02rem; line-height: 1.45; }}
    .prototype-moment span {{ position: absolute; right: 20px; bottom: 18px; font-family: Georgia, serif; font-size: 5rem; line-height: 0.8; opacity: 0.24; }}
    .prototype-workbench {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(280px, 0.44fr); gap: 20px; align-items: start; padding: clamp(28px, 5vw, 70px); background: #fff9eb; }}
    .prototype-workbench--argument-full {{ grid-template-columns: minmax(0, 1fr); }}
    .prototype-workbench--argument-full .prototype-argument {{ grid-column: 1 / -1; }}
    .prototype-argument, .prototype-constraints {{ border: 2px solid var(--ink); padding: 22px; background: var(--paper); border-radius: 8px; }}
    .prototype-argument h2 {{ font-family: var(--font-headline); overflow-wrap: normal; word-break: normal; }}
    .prototype-argument--poster h2 {{ max-width: min(16ch, 100%); font-size: 4.65rem; line-height: 0.9; }}
    .prototype-argument--editorial h2 {{ max-width: min(34ch, 72vw); font-size: 3.25rem; line-height: 1; text-wrap: balance; }}
    .prototype-argument--editorial > p:not(.prototype-eyebrow) {{ max-width: 68ch; font-size: 1.08rem; line-height: 1.5; }}
    .prototype-tiles {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; padding: 0; margin: 22px 0 0; list-style: none; }}
    .prototype-tiles li {{ min-height: 120px; padding: 14px; border: 1px solid var(--ink); background: #fff; }}
    .prototype-tiles b, .prototype-tiles span {{ display: block; }}
    .prototype-constraints dl, .prototype-constraints dd {{ margin: 0; }}
    .prototype-constraints div {{ padding: 12px 0; border-top: 1px solid rgba(0, 0, 0, 0.22); }}
    .prototype-constraints dt {{ font-size: 0.72rem; text-transform: uppercase; font-weight: 900; }}
    .prototype-constraints dd {{ margin-top: 6px; line-height: 1.36; }}
    .prototype-route-index {{ padding: clamp(28px, 5vw, 70px); background: var(--paper); border-top: 2px solid var(--ink); }}
    .prototype-route-index h2 {{ font-family: var(--font-headline); font-size: clamp(2.2rem, 5vw, 5.2rem); line-height: 0.9; max-width: min(24ch, 100%); }}
    .prototype-route-switcher {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); margin: 24px 0; border: 2px solid var(--ink); background: #fff9eb; }}
    .prototype-route-switcher a {{ display: grid; gap: 4px; min-height: 72px; padding: 12px; color: inherit; text-decoration: none; border-right: 1px solid var(--ink); }}
    .prototype-route-switcher a:last-child {{ border-right: 0; }}
    .prototype-route-switcher span {{ font-size: 0.68rem; text-transform: uppercase; font-weight: 900; }}
    .prototype-route-switcher b {{ line-height: 1.12; overflow-wrap: anywhere; }}
    .prototype-route-cards {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; margin-top: 24px; }}
    .prototype-route-cards article {{ border: 2px solid var(--ink); border-radius: 8px; padding: 20px; background: #fff9eb; }}
    .prototype-route-cards h3 {{ font-family: var(--font-headline); font-size: clamp(1.8rem, 3vw, 3.6rem); line-height: 0.94; }}
    .prototype-route-cards a {{ color: inherit; font-weight: 900; }}
    .prototype-route-jump {{ display: inline-flex; margin: 10px 0 0; }}
    .prototype-route-section-jumps {{ display: grid; gap: 6px; margin-top: 14px; }}
    .prototype-route-section-link {{ display: block; padding: 7px 9px; border: 1px solid var(--ink); border-radius: 6px; text-decoration: none; background: #fff; }}
    .prototype-route-panels {{ display: grid; gap: 0; background: var(--ink); }}
    .prototype-route-panel {{ display: grid; grid-template-columns: minmax(0, 0.6fr) minmax(280px, 0.72fr); gap: 24px; padding: clamp(28px, 5vw, 70px); color: var(--paper); border-top: 2px solid var(--paper); }}
    .prototype-route-panel h2 {{ font-family: var(--font-headline); font-size: 5.2rem; line-height: 0.9; max-width: min(16ch, 100%); }}
    .prototype-route-panel--editorial-title h2 {{ max-width: min(24ch, 100%); font-size: 4.2rem; line-height: 0.96; text-wrap: balance; }}
    .prototype-panel-visual {{ margin: 0; background: var(--surface); border: 6px solid var(--paper); }}
    .prototype-panel-visual img {{ width: 100%; aspect-ratio: 16 / 10; object-fit: contain; display: block; }}
    .prototype-panel-visual figcaption {{ padding: 10px; background: var(--paper); color: var(--ink); font-weight: 900; }}
    .prototype-panel-colors {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; padding: 0; margin: 20px 0; list-style: none; }}
    .prototype-panel-colors li {{ min-width: 0; }}
    .prototype-panel-colors span {{ display: block; height: 36px; border: 1px solid var(--paper); }}
    .prototype-panel-colors b {{ display: block; margin-top: 6px; font-size: 0.72rem; overflow-wrap: anywhere; }}
    .prototype-type-family {{ margin: 18px 0 8px; font-family: var(--font-headline); font-size: 1.6rem; line-height: 1; }}
    .prototype-type-note, .prototype-type-use {{ max-width: 68ch; line-height: 1.42; }}
    .prototype-type-note {{ font-weight: 800; }}
    .prototype-type-use {{ opacity: 0.82; }}
    .prototype-receipt-detail {{ margin-top: 12px; max-width: 70ch; font-size: 0.9rem; line-height: 1.4; }}
    .prototype-receipt-detail summary {{ cursor: pointer; font-weight: 900; }}
    .prototype-receipt-detail dl {{ display: grid; gap: 8px; margin: 10px 0 0; }}
    .prototype-receipt-detail div {{ border-top: 1px solid currentColor; padding-top: 8px; }}
    .prototype-receipt-detail dt {{ font-size: 0.7rem; text-transform: uppercase; font-weight: 900; }}
    .prototype-receipt-detail dd {{ margin: 4px 0 0; overflow-wrap: anywhere; }}
    .prototype-section-list {{ grid-column: 1 / -1; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }}
    .prototype-section-list article {{ min-height: 210px; padding: 18px; background: var(--paper); color: var(--ink); border-radius: 8px; }}
    .prototype-section-list span {{ font-family: Georgia, serif; font-size: 2.6rem; opacity: 0.34; }}
    .prototype-section-list h3 {{ font-size: clamp(1.3rem, 2.2vw, 2.5rem); line-height: 1; }}
    .prototype-footer {{ display: flex; justify-content: space-between; gap: 20px; padding: 26px clamp(20px, 5vw, 86px); background: var(--ink); color: var(--paper); font-weight: 900; }}
    @media (max-width: 900px) {{
      .prototype-route, .prototype-route * {{ min-width: 0; }}
      .prototype-route {{ max-width: 100vw; overflow-x: hidden; }}
      [data-nav-section] {{ scroll-margin-top: 76px; }}
      .prototype-nav {{ grid-template-columns: minmax(0, 1fr) auto; gap: 10px; padding: 10px 14px; }}
      .prototype-current {{ grid-column: 1 / -1; grid-template-columns: auto minmax(0, 1fr); padding: 6px 0 0; border-left: 0; border-top: 1px solid rgba(0, 0, 0, 0.24); }}
      .prototype-primary-jumps {{ display: none; }}
      .prototype-menu-button {{ display: inline-flex; }}
      .prototype-layout {{ display: block; }}
      .prototype-left-rail {{ display: none; }}
      .prototype-mobile-drawer:not([hidden]) {{ display: block; position: fixed; inset: 74px 0 0; z-index: 45; overflow: auto; padding: 18px; background: var(--paper); border-top: 2px solid var(--ink); }}
      .prototype-mobile-drawer .prototype-nav-group {{ max-width: calc(100vw - 36px); }}
      .prototype-command-palette {{ padding: 76px 14px 14px; place-items: start stretch; }}
      .prototype-command-panel {{ max-height: calc(100vh - 92px); box-shadow: 8px 8px 0 var(--accent); }}
      .prototype-hero, .prototype-proof, .prototype-workbench, .prototype-route-panel {{ grid-template-columns: 1fr; }}
      .prototype-hero {{ min-height: auto; padding: 44px 24px; }}
      .prototype-palette, .prototype-moments, .prototype-tiles, .prototype-route-cards, .prototype-section-list {{ grid-template-columns: 1fr; }}
      .prototype-route-switcher {{ grid-template-columns: 1fr; }}
      .prototype-route-switcher a {{ border-right: 0; border-bottom: 1px solid var(--ink); }}
      .prototype-route-switcher a:last-child {{ border-bottom: 0; }}
      .prototype-hero h1, .prototype-hero--long-headline h1 {{ width: min(100%, calc(100vw - 48px)); max-width: calc(100vw - 48px); font-size: 2.35rem; line-height: 0.98; overflow-wrap: break-word; word-break: normal; }}
      .prototype-subhead {{ width: min(100%, calc(100vw - 48px)); max-width: calc(100vw - 48px); font-size: 1rem; }}
      .prototype-visual, .prototype-argument, .prototype-constraints, .prototype-route-cards article, .prototype-route-panel, .prototype-section-list article, .prototype-panel-visual {{ width: min(100%, calc(100vw - 48px)); max-width: calc(100vw - 48px); }}
      .prototype-visual, .prototype-visual img {{ max-height: none; }}
      .prototype-argument--poster h2, .prototype-argument--editorial h2, .prototype-route-panel h2, .prototype-route-panel--editorial-title h2 {{ max-width: calc(100vw - 48px); font-size: 2.25rem; line-height: 1; }}
      h2, h3, p, li, dd, .prototype-footer span {{ overflow-wrap: anywhere; }}
      .prototype-visual {{ border-width: 5px; box-shadow: 8px 8px 0 var(--accent); }}
      .prototype-type {{ border-left: 0; border-top: 2px solid var(--ink); }}
    }}
  </style>
</head>
<body>
  <a class="prototype-skip-link" href="#prototype-content">Skip to prototype content</a>
  <main class="prototype-route" id="prototype-content" data-route-id="{escape(route_key, quote=True)}">
    <nav class="prototype-nav" aria-label="Prototype navigation">
      <a class="prototype-brand" href="#overview">{title}</a>
      <div class="prototype-current" aria-live="polite">
        <span>Route</span>
        <strong data-current-route>{route_title}</strong>
        <span>Section</span>
        <strong data-current-section>Overview</strong>
      </div>
      <div class="prototype-nav-actions">
        <div class="prototype-primary-jumps" aria-label="Primary prototype jumps">{primary_jumps}</div>
        <button class="prototype-nav-button" type="button" data-command-open aria-controls="prototype-command-palette">Find</button>
        <button class="prototype-nav-button prototype-menu-button" type="button" data-mobile-toggle aria-controls="prototype-mobile-drawer" aria-expanded="false">Menu</button>
      </div>
    </nav>
    {mobile_drawer}
    {command_palette}
    <div class="prototype-layout">
      {left_rail}
      <div class="prototype-content">
        <section class="{hero_class}" {_nav_section_attrs(navigation.primary_sections[0])}>
          <div>
            <p class="prototype-eyebrow">London Osei first-pass prototype</p>
            <h1>{headline}</h1>
            <p class="prototype-subhead">{subhead}</p>
            <ul class="prototype-tags">{tag_html}</ul>
          </div>
          {_render_asset_figure(hero, class_name="prototype-visual", fallback_title="Route visual handoff", compact_caption=True)}
        </section>
        <section class="prototype-proof" {_nav_section_attrs(navigation.primary_sections[1])}>
          <ul class="prototype-palette">{_render_palette(route)}</ul>
          <aside class="prototype-type {type_direction_mode}">
            <p class="prototype-eyebrow">Type Direction</p>
            <h2>{escape(type_family)}</h2>
            {type_notes}
            <dl class="prototype-type-roles">{type_role_rows}</dl>
            {font_proof_details}
          </aside>
        </section>
        <section class="prototype-moments" {_nav_section_attrs(navigation.primary_sections[2])}>
          {_render_moments(moments, navigation.current_moments)}
        </section>
        <section class="{workbench_class}" {_nav_section_attrs(navigation.primary_sections[3])}>
          <article class="prototype-argument prototype-argument--{argument_mode}">
            <p class="prototype-eyebrow">Route Argument</p>
            <h2>{escape(argument_heading_raw)}</h2>
            <p>{escape(argument_body_raw)}</p>
            <ul class="prototype-tiles">{_render_tile_strip(tiles)}</ul>
          </article>
          <aside class="prototype-constraints">
            <p class="prototype-eyebrow">Build Constraints</p>
            <dl>
              {"".join(f"<div><dt>{escape(label)}</dt><dd>{escape(value)}</dd></div>" for label, value in constraint_rows)}
            </dl>
          </aside>
        </section>
        <section class="prototype-route-index" {_nav_section_attrs(navigation.primary_sections[4])}>
          <p class="prototype-eyebrow">Route Switcher</p>
          <h2>Every route stays in its own lane.</h2>
          {route_switcher}
          <div class="prototype-route-cards">{route_cards}</div>
        </section>
        <section class="prototype-route-panels" {_nav_section_attrs(navigation.primary_sections[5])}>
          {all_route_panels}
        </section>
        <footer class="prototype-footer">
          <span>{route_title}</span>
          <span>{title}</span>
        </footer>
      </div>
    </div>
  </main>
  <script>
    (() => {{
      const drawer = document.querySelector("[data-mobile-drawer]");
      const menuButton = document.querySelector("[data-mobile-toggle]");
      const palette = document.querySelector("[data-command-palette]");
      const commandInput = document.querySelector("[data-command-search]");
      const commandItems = Array.from(document.querySelectorAll("[data-command-item]"));
      const currentRoute = document.querySelector("[data-current-route]");
      const currentSection = document.querySelector("[data-current-section]");
      const navLinks = Array.from(document.querySelectorAll("[data-nav-link]"));
      const routeTabs = Array.from(document.querySelectorAll("[data-nav-route-tab]"));
      const sections = Array.from(document.querySelectorAll("[data-nav-section]"));
      const copyText = async (text) => {{
        try {{
          await navigator.clipboard.writeText(text);
        }} catch (error) {{
          const area = document.createElement("textarea");
          area.value = text;
          document.body.appendChild(area);
          area.select();
          document.execCommand("copy");
          area.remove();
        }}
      }};

      const setDrawer = (open) => {{
        if (!drawer || !menuButton) return;
        drawer.hidden = !open;
        menuButton.setAttribute("aria-expanded", String(open));
      }};

      const openPalette = () => {{
        if (!palette || !commandInput) return;
        palette.hidden = false;
        commandInput.focus();
        commandInput.select();
      }};

      const closePalette = () => {{
        if (!palette) return;
        palette.hidden = true;
      }};

      const setCurrent = (section) => {{
        if (!section) return;
        const id = section.dataset.navSection;
        const routeId = section.dataset.navRoute;
        if (currentRoute) currentRoute.textContent = section.dataset.navRouteTitle || "";
        if (currentSection) currentSection.textContent = section.dataset.navLabel || "";
        navLinks.forEach((link) => {{
          if (link.dataset.navLink === id) link.setAttribute("aria-current", "location");
          else link.removeAttribute("aria-current");
        }});
        routeTabs.forEach((tab) => {{
          tab.setAttribute("aria-selected", String(tab.dataset.navRouteTab === routeId));
        }});
      }};

      const flashTarget = (id) => {{
        if (!id) return;
        const target = document.getElementById(id);
        if (!target) return;
        target.classList.remove("is-target-flash");
        void target.offsetWidth;
        target.classList.add("is-target-flash");
        window.setTimeout(() => target.classList.remove("is-target-flash"), 1200);
      }};

      menuButton?.addEventListener("click", () => setDrawer(drawer?.hidden));
      document.querySelector("[data-command-open]")?.addEventListener("click", openPalette);
      document.querySelector("[data-command-close]")?.addEventListener("click", closePalette);
      palette?.addEventListener("click", (event) => {{
        if (event.target === palette) closePalette();
      }});
      commandInput?.addEventListener("input", () => {{
        const query = commandInput.value.trim().toLowerCase();
        commandItems.forEach((item) => {{
          item.hidden = query !== "" && !item.dataset.commandKey.includes(query);
        }});
      }});
      navLinks.forEach((link) => {{
        link.addEventListener("click", () => {{
          setDrawer(false);
          closePalette();
          window.requestAnimationFrame(() => flashTarget(decodeURIComponent(link.hash.slice(1))));
        }});
      }});
      document.querySelectorAll("[data-copy]").forEach((button) => {{
        button.addEventListener("click", () => copyText(button.dataset.copy || ""));
      }});
      window.addEventListener("hashchange", () => flashTarget(decodeURIComponent(window.location.hash.slice(1))));
      document.addEventListener("keydown", (event) => {{
        const target = event.target;
        const isEditable = target?.matches?.("input, textarea, select, [contenteditable='true']");
        const key = event.key.toLowerCase();
        if ((event.metaKey || event.ctrlKey) && key === "k") {{
          event.preventDefault();
          openPalette();
          return;
        }}
        if (event.key === "/" && !isEditable && !event.metaKey && !event.ctrlKey && !event.altKey) {{
          event.preventDefault();
          openPalette();
          return;
        }}
        if (event.key === "Escape") {{
          closePalette();
          setDrawer(false);
        }}
      }});

      if ("IntersectionObserver" in window) {{
        const observer = new IntersectionObserver(
          (entries) => {{
            const visible = entries
              .filter((entry) => entry.isIntersecting)
              .sort((a, b) => b.intersectionRatio - a.intersectionRatio || a.boundingClientRect.top - b.boundingClientRect.top)[0];
            if (visible) setCurrent(visible.target);
          }},
          {{ rootMargin: "-30% 0px -55% 0px", threshold: [0.08, 0.22, 0.45] }}
        );
        sections.forEach((section) => observer.observe(section));
      }}
      setCurrent(document.getElementById(decodeURIComponent(window.location.hash.slice(1))) || sections[0]);
      flashTarget(decodeURIComponent(window.location.hash.slice(1)));
    }})();
  </script>
</body>
</html>
"""


def write_static_prototype(pack: Mapping[str, Any], out_dir: str | Path, route_id: str | None = None) -> Path:
    """Write prototype/index.html for a pack and return the file path."""

    prototype_dir = Path(out_dir) / "prototype"
    prototype_dir.mkdir(parents=True, exist_ok=True)
    path = prototype_dir / "index.html"
    path.write_text(render_static_prototype(pack, route_id=route_id), encoding="utf-8")
    return path
