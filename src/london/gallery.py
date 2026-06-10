from __future__ import annotations

from dataclasses import dataclass
import hashlib
from html import escape
import json
import shutil
from pathlib import Path
from typing import Any, Mapping, Sequence

from .assets import normalize_palette, normalize_tags, pack_routes, route_assets, slugify
from .dossier.shared import _provider_label, _public_type_rationale
from .font_preview import resolve_font_preview
from .route_refs import resolve_route_ref
from .safe_urls import safe_href
from .text import clean_title, display_text


PUBLIC_GALLERY_IMAGE_KINDS = {"generated-concept-image"}
BLOCKED_GALLERY_KINDS = {
    "visual-direction-board",
    "manual-prompt-card",
    "generation-unavailable",
    "fixture-system-sketch",
}


@dataclass
class GalleryItem:
    pack_dir: Path
    pack_title: str
    slug: str
    route_id: str
    route_title: str
    route_headline: str
    route_subhead: str
    route_rationale: str
    visual_read: str
    artifact_type: str
    proof_state: str
    preview_href: str
    preview_source_path: Path | None
    preview_alt: str
    palette: list[dict[str, str]]
    tags: list[str]
    font_family: str
    type_direction: str
    type_rationale: str
    type_best_use: str
    provider: str
    receipt_status: str
    caveat: str = ""
    blocked_reason: str = ""

    @property
    def eligible(self) -> bool:
        return self.proof_state == "eligible"


@dataclass(frozen=True)
class GalleryEligibility:
    ok: bool
    asset_path: Path | None = None
    receipt: Mapping[str, Any] | None = None
    reason: str = ""


def collect_gallery_items(pack_dirs: Sequence[str | Path], *, out_dir: str | Path | None = None) -> list[GalleryItem]:
    """Collect gallery entries from one or more written London pack directories."""

    output_root = Path(out_dir) if out_dir is not None else None
    assets_dir = output_root / "assets" if output_root is not None else None
    if assets_dir is not None:
        assets_dir.mkdir(parents=True, exist_ok=True)

    items: list[GalleryItem] = []
    used_slugs: set[str] = set()
    for pack_dir in pack_dirs:
        root = Path(pack_dir)
        pack_path = root / "london-pack.json"
        if not pack_path.exists():
            raise FileNotFoundError(f"Missing london-pack.json in {root}")
        pack = json.loads(pack_path.read_text(encoding="utf-8"))
        item = _item_for_pack(root, pack)
        item.slug = _unique_slug(item.slug, used_slugs)
        if item.eligible and assets_dir is not None:
            item.preview_href = _copy_preview_asset(item, assets_dir)
        items.append(item)
    return items


def render_gallery_index(items: Sequence[GalleryItem]) -> str:
    eligible = [item for item in items if item.eligible]
    blocked = [item for item in items if not item.eligible]
    cards = "\n".join(_render_gallery_card(item) for item in eligible)
    hero = _gallery_hero(eligible)
    if not cards:
        cards = """
        <div class="gallery-empty">
          <p class="gallery-kicker">Gallery</p>
          <h2>No route image is ready.</h2>
          <p>Generate at least one route image before publishing the gallery.</p>
        </div>"""
    diagnostics = _render_blocked_diagnostics(blocked)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>London Gallery</title>
  <style>{_gallery_style()}</style>
</head>
<body>
  <header class="gallery-topbar">
    <a class="gallery-mark" href="index.html">London</a>
  </header>
  <main class="gallery-shell">
    {hero}
    <section class="gallery-grid" aria-label="Public gallery work">
      {cards}
    </section>
    {diagnostics}
  </main>
</body>
</html>"""


def render_gallery_detail(item: GalleryItem) -> str:
    if not item.eligible:
        raise ValueError("Blocked gallery items do not render public detail pages.")
    swatches = "".join(
        f"""<li><span style="--swatch:{escape(color['hex'], quote=True)}"></span><b>{escape(color['name'])}</b></li>"""
        for color in item.palette[:6]
    )
    tags = "".join(f"<li>{escape(tag)}</li>" for tag in item.tags[:8])
    caveat = f"<p>{escape(item.caveat)}</p>" if item.caveat else ""
    subhead = f"<p class=\"gallery-subhead\">{escape(item.route_subhead)}</p>" if item.route_subhead else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(item.route_title)} - London Gallery</title>
  <style>{_gallery_style()}</style>
</head>
<body>
  <header class="gallery-detail-header">
    <a class="gallery-mark" href="../index.html">London</a>
    <div>
      <p class="gallery-kicker">{escape(item.pack_title)}</p>
      <h1>{escape(item.route_title)}</h1>
      <p class="gallery-lede">{escape(item.route_headline or item.route_title)}</p>
      {subhead}
    </div>
  </header>
  <nav class="gallery-toolbar" aria-label="Gallery detail toolbar">
    <a aria-current="page" href="#preview">Preview</a>
    <a href="#pages">Pages</a>
    <a href="#routes">Routes</a>
    <button type="button" data-copy="{escape(item.route_title, quote=True)}">Copy title</button>
    <a href="../{escape(item.preview_href, quote=True)}" download>Download</a>
    <a href="../{escape(item.preview_href, quote=True)}">Open image</a>
  </nav>
  <main class="gallery-detail-layout">
    <section class="gallery-preview-stack" id="preview">
      <figure class="gallery-large-preview">
        <img src="../{escape(item.preview_href, quote=True)}" alt="{escape(item.preview_alt, quote=True)}">
        <figcaption>{escape(item.route_headline or item.route_title)}</figcaption>
      </figure>
      <article class="gallery-secondary-preview" id="pages">
        <p class="gallery-kicker">Route context</p>
        <h2>{escape(item.route_headline or item.route_title)}</h2>
        {subhead}
        {_optional_paragraph(item.route_rationale, class_name="gallery-route-read")}
        {_optional_paragraph(item.visual_read, class_name="gallery-visual-read")}
      </article>
    </section>
    <aside class="gallery-rail" aria-label="Gallery metadata">
      <section class="gallery-rail-card">
        <p class="gallery-kicker">Palette</p>
        <ul class="gallery-swatches">{swatches}</ul>
      </section>
      <section class="gallery-rail-card">
        <p class="gallery-kicker">Type direction</p>
        <h2>{escape(item.font_family)}</h2>
        <p>{escape(item.type_direction)}</p>
        {_optional_paragraph(item.type_rationale, class_name="gallery-type-note")}
        {_optional_paragraph(item.type_best_use, class_name="gallery-type-use")}
      </section>
      <section class="gallery-rail-card">
        <p class="gallery-kicker">Source record</p>
        <details class="gallery-proof-detail">
          <summary>Open audit note</summary>
          <p>This public card is admitted only when its displayed image is bound to a generated local asset.</p>
          <dl class="gallery-proof-list">
            <div><dt>Image source</dt><dd>{escape(item.provider)}</dd></div>
          </dl>
        </details>
        {caveat}
      </section>
      <section class="gallery-rail-card">
        <p class="gallery-kicker">Tags</p>
        <ul class="gallery-tags">{tags}</ul>
      </section>
    </aside>
  </main>
  <script>
    document.querySelectorAll("[data-copy]").forEach((button) => {{
      button.addEventListener("click", async () => {{
        try {{ await navigator.clipboard.writeText(button.dataset.copy || ""); }}
        catch (error) {{}}
      }});
    }});
  </script>
</body>
</html>"""


def write_gallery(pack_dirs: Sequence[str | Path], out_dir: str | Path) -> Path:
    """Write a standalone public proof gallery from generated London pack directories."""

    output_root = Path(out_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    details_dir = output_root / "details"
    details_dir.mkdir(exist_ok=True)
    items = collect_gallery_items(pack_dirs, out_dir=output_root)
    index_path = output_root / "index.html"
    index_path.write_text(render_gallery_index(items), encoding="utf-8")
    for item in items:
        if item.eligible:
            (details_dir / f"{item.slug}.html").write_text(render_gallery_detail(item), encoding="utf-8")
    return index_path


def _item_for_pack(root: Path, pack: Mapping[str, Any]) -> GalleryItem:
    routes = pack_routes(pack)
    if not routes:
        raise ValueError(f"Pack has no routes: {root}")
    pack_title = clean_title(pack, fallback=root.name)
    recommended = resolve_route_ref(pack.get("recommended_route_ref"), routes)
    selected = recommended if recommended is not None else routes[0]
    selected_asset = _primary_asset(selected)
    selected_route_id = _route_id(selected)
    eligibility = _gallery_asset_eligibility(root, pack, selected_route_id, selected_asset)
    caveat = ""
    if not eligibility.ok:
        generated = _first_generated_route(root, pack, routes)
        if generated is not None:
            selected, selected_asset = generated
            selected_route_id = _route_id(selected)
            eligibility = _gallery_asset_eligibility(root, pack, selected_route_id, selected_asset)
            caveat = "Recommended route visual proof missing; showing the nearest generated route instead."
    if eligibility.ok:
        return _gallery_item(root, pack, selected, selected_asset, pack_title=pack_title, caveat=caveat)
    blocked_kind = display_text(selected_asset.get("kind"), fallback="<missing>")
    item = _gallery_item(root, pack, selected, selected_asset, pack_title=pack_title, caveat="")
    item.proof_state = "blocked"
    item.preview_href = ""
    item.preview_source_path = None
    reason = eligibility.reason or f"primary visual kind is {blocked_kind}; fallback boards stay internal/offline"
    if reason.startswith("primary visual kind"):
        detail = reason
    else:
        detail = f"primary visual kind is {blocked_kind}; {reason}"
    item.blocked_reason = (
        "Public proof blocked: no generated image for this route. "
        f"{detail}."
    )
    return item


def _gallery_item(
    root: Path,
    pack: Mapping[str, Any],
    route: Mapping[str, Any],
    asset: Mapping[str, Any],
    *,
    pack_title: str,
    caveat: str = "",
) -> GalleryItem:
    route_id = _route_id(route)
    route_title = display_text(route.get("title") or route.get("name"), fallback="Untitled route")
    route_headline = display_text(route.get("headline") or route.get("thesis") or route.get("rationale"), fallback=route_title)
    route_subhead = display_text(route.get("subhead") or route.get("best_for"))
    route_rationale = _route_argument(pack, route)
    visual_read = _visual_read(route, asset)
    artifact_type = display_text(pack.get("artifact_type") or pack.get("artifactType"), fallback="Route proof")
    palette = normalize_palette(route.get("palette"))
    tags = normalize_tags(route.get("tags"), defaults=(artifact_type,))
    eligibility = _gallery_asset_eligibility(root, pack, route_id, asset)
    provider, receipt_status = _proof_receipt(pack, route_id, asset)
    font_family, type_direction, type_rationale, type_best_use = _type_summary(pack, route_id, route)
    return GalleryItem(
        pack_dir=root,
        pack_title=pack_title,
        slug=slugify(f"{pack_title}-{route_title}", fallback="gallery-item"),
        route_id=route_id,
        route_title=route_title,
        route_headline=route_headline,
        route_subhead=route_subhead,
        route_rationale=route_rationale,
        visual_read=visual_read,
        artifact_type=artifact_type,
        proof_state="eligible" if eligibility.ok else "blocked",
        preview_href=safe_href(asset.get("src")),
        preview_source_path=eligibility.asset_path,
        preview_alt=_public_image_alt(route_title),
        palette=palette,
        tags=tags,
        font_family=font_family,
        type_direction=type_direction,
        type_rationale=type_rationale,
        type_best_use=type_best_use,
        provider=provider,
        receipt_status=receipt_status,
        caveat=caveat,
    )


def _render_gallery_card(item: GalleryItem) -> str:
    accent = item.palette[0]["hex"] if item.palette else "#1d1d1b"
    tags = "".join(f"<li>{escape(tag)}</li>" for tag in item.tags[:4])
    subhead = f"""<p class="gallery-card-subcopy">{escape(item.route_subhead)}</p>""" if item.route_subhead else ""
    rationale = (
        f"""<p class="gallery-card-rationale">{escape(item.route_rationale)}</p>"""
        if item.route_rationale
        else ""
    )
    visual = (
        f"""<p class="gallery-card-visual">{escape(item.visual_read)}</p>"""
        if item.visual_read
        else ""
    )
    return f"""
      <article class="gallery-card" data-proof-state="eligible" style="--route-accent:{escape(accent, quote=True)}">
        <a class="gallery-card-link" href="details/{escape(item.slug, quote=True)}.html">
          <figure class="gallery-card-preview">
            <img src="{escape(item.preview_href, quote=True)}" alt="{escape(item.preview_alt, quote=True)}">
          </figure>
          <div class="gallery-card-caption">
            <p class="gallery-kicker">{escape(item.artifact_type)}</p>
            <h2>{escape(item.route_title)}</h2>
            <p>{escape(item.route_headline or item.route_title)}</p>
            {subhead}
            {rationale}
            {visual}
            <ul class="gallery-tags">{tags}</ul>
          </div>
        </a>
      </article>"""


def _gallery_hero(items: Sequence[GalleryItem]) -> str:
    if not items:
        return """
    <section class="gallery-hero" aria-labelledby="gallery-title">
      <p class="gallery-kicker">Gallery</p>
      <h1 id="gallery-title">No route image is ready.</h1>
      <p>Generate at least one route image before publishing the gallery.</p>
    </section>"""
    lead = items[0]
    route_list = " · ".join(item.route_title for item in items[:3])
    title = lead.route_headline or lead.route_title
    lede = lead.route_subhead or route_list
    route_line = f"""<p class="gallery-route-line">{escape(route_list)}</p>""" if route_list else ""
    return f"""
    <section class="gallery-hero" aria-labelledby="gallery-title">
      <p class="gallery-kicker">{escape(lead.pack_title)}</p>
      <h1 id="gallery-title">{escape(title)}</h1>
      <p>{escape(lede)}</p>
      {route_line}
    </section>"""


def _optional_paragraph(value: str, *, class_name: str = "") -> str:
    text = display_text(value)
    if not text:
        return ""
    class_attr = f' class="{escape(class_name, quote=True)}"' if class_name else ""
    return f"<p{class_attr}>{escape(text)}</p>"


def _public_image_alt(route_title: str) -> str:
    return f"{display_text(route_title, fallback='Route')} concept image"


def _render_blocked_diagnostics(items: Sequence[GalleryItem]) -> str:
    if not items:
        return ""
    rows = "\n".join(
        f"""
        <article class="gallery-diagnostic-card" data-proof-state="blocked">
          <p class="gallery-kicker">Internal diagnostic</p>
          <h3>{escape(item.pack_title)}</h3>
          <p>{escape(item.blocked_reason)}</p>
        </article>"""
        for item in items
    )
    return f"""
    <details class="gallery-diagnostics" data-public-gallery="internal-diagnostics">
      <summary>Internal gallery review notes</summary>
      <p>Some submitted packs need internal review before they can become public gallery cards.</p>
      <div class="gallery-diagnostic-grid">{rows}</div>
    </details>"""


def _gallery_style() -> str:
    return """
    :root {
      --gallery-bg: #f7f6f2;
      --gallery-card: #ffffff;
      --gallery-ink: #1d1d1b;
      --gallery-muted: #77736d;
      --gallery-border: rgba(0, 0, 0, 0.10);
      --gallery-radius: 14px;
      --route-accent: #1d1d1b;
      color-scheme: light;
    }
    * { box-sizing: border-box; }
    html, body { max-width: 100%; overflow-x: hidden; }
    body { margin: 0; background: var(--gallery-bg); color: var(--gallery-ink); font-family: Inter, Arial, Helvetica, sans-serif; }
    a { color: inherit; }
    .gallery-topbar { position: sticky; top: 0; z-index: 10; display: grid; grid-template-columns: auto minmax(220px, 1fr) auto auto; gap: 14px; align-items: center; padding: 16px clamp(18px, 4vw, 44px); background: rgba(247, 246, 242, 0.96); border-bottom: 1px solid var(--gallery-border); backdrop-filter: blur(12px); }
    .gallery-topbar > *, .gallery-card, .gallery-detail-header > *, .gallery-rail-card { min-width: 0; }
    .gallery-mark { font-weight: 800; text-decoration: none; letter-spacing: 0; }
    .gallery-filters, .gallery-tags, .gallery-meta-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
    .gallery-filters button, .gallery-tags li, .gallery-toolbar a, .gallery-toolbar button { border: 1px solid var(--gallery-border); border-radius: 999px; background: var(--gallery-card); color: var(--gallery-ink); padding: 8px 12px; font: inherit; font-size: 0.78rem; font-weight: 800; text-decoration: none; }
    .gallery-filters button[aria-pressed="true"], .gallery-toolbar [aria-current="page"] { border-color: var(--route-accent); box-shadow: inset 0 0 0 1px var(--route-accent); }
    .gallery-shell { width: min(1680px, calc(100vw - 48px)); margin: 0 auto; padding: clamp(28px, 5vw, 72px) 0; }
    .gallery-hero { max-width: 820px; margin-bottom: 28px; }
    .gallery-hero h1, .gallery-detail-header h1 { margin: 0; font-size: clamp(2.4rem, 5vw, 5.6rem); line-height: 0.95; letter-spacing: 0; overflow-wrap: anywhere; }
    .gallery-hero p:not(.gallery-kicker) { max-width: 62ch; color: var(--gallery-muted); font-size: 1.05rem; line-height: 1.45; }
    .gallery-lede, .gallery-subhead, .gallery-route-line { color: var(--gallery-muted); line-height: 1.45; }
    .gallery-lede { max-width: 62ch; font-size: clamp(1.05rem, 1.8vw, 1.35rem); }
    .gallery-subhead { max-width: 68ch; }
    .gallery-route-line { margin-top: 14px; font-weight: 800; }
    .gallery-kicker { margin: 0 0 8px; color: var(--gallery-muted); font-size: 0.72rem; text-transform: uppercase; font-weight: 900; letter-spacing: 0; }
    .gallery-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 360px), 420px)); gap: 22px; align-items: start; justify-content: start; }
    .gallery-card { background: var(--gallery-card); border: 1px solid var(--gallery-border); border-top: 4px solid var(--route-accent); border-radius: var(--gallery-radius); overflow: hidden; }
    .gallery-card-link { display: grid; gap: 0; color: inherit; text-decoration: none; }
    .gallery-card-preview { margin: 0; aspect-ratio: 4 / 3; min-height: 0; display: grid; place-items: center; background: #efeee9; border-bottom: 1px solid var(--gallery-border); overflow: hidden; }
    .gallery-card-preview img { width: 100%; height: 100%; object-fit: cover; display: block; }
    .gallery-large-preview img { width: 100%; height: 100%; object-fit: contain; display: block; }
    .gallery-card-caption { padding: 14px 16px 18px; }
    .gallery-card-caption h2 { margin: 0 0 6px; font-size: clamp(1.4rem, 2.4vw, 2.25rem); line-height: 1; letter-spacing: 0; }
    .gallery-card-caption p { margin: 0 0 12px; color: var(--gallery-muted); line-height: 1.35; }
    .gallery-card-subcopy { font-size: 0.92rem; }
    .gallery-card-rationale, .gallery-route-read { color: var(--gallery-ink); }
    .gallery-card-visual, .gallery-visual-read { color: var(--gallery-muted); }
    .gallery-tags { padding: 0; margin: 0; list-style: none; }
    .gallery-tags li { padding: 6px 9px; font-size: 0.68rem; }
    .gallery-empty, .gallery-diagnostics, .gallery-secondary-preview { padding: 22px; background: var(--gallery-card); border: 1px solid var(--gallery-border); border-radius: var(--gallery-radius); }
    .gallery-diagnostics { margin-top: 36px; }
    .gallery-diagnostic-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; }
    .gallery-diagnostic-card { padding: 16px; background: #fbfaf7; border: 1px solid var(--gallery-border); border-left: 4px solid #9f3d2d; border-radius: 10px; }
    .gallery-diagnostic-card h3 { margin: 0 0 8px; }
    .gallery-detail-header { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 28px; align-items: start; padding: clamp(22px, 4vw, 44px); border-bottom: 1px solid var(--gallery-border); }
    .gallery-meta-row { color: var(--gallery-muted); }
    .gallery-meta-row span { padding-right: 10px; border-right: 1px solid var(--gallery-border); }
    .gallery-toolbar { position: sticky; top: 0; z-index: 8; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; padding: 12px clamp(18px, 4vw, 44px); background: rgba(247, 246, 242, 0.96); border-bottom: 1px solid var(--gallery-border); backdrop-filter: blur(12px); }
    .gallery-detail-layout { width: min(1680px, calc(100vw - 48px)); margin: 0 auto; padding: clamp(24px, 4vw, 52px) 0; display: grid; grid-template-columns: minmax(620px, 1fr) minmax(340px, 420px); gap: 24px; align-items: start; }
    .gallery-preview-stack, .gallery-rail { display: grid; gap: 16px; }
    .gallery-large-preview { min-height: 620px; margin: 0; display: grid; grid-template-rows: minmax(0, 1fr) auto; background: var(--gallery-card); border: 1px solid var(--gallery-border); border-radius: var(--gallery-radius); overflow: hidden; }
    .gallery-large-preview figcaption { padding: 12px 14px; color: var(--gallery-muted); border-top: 1px solid var(--gallery-border); }
    .gallery-rail-card { padding: 18px; background: var(--gallery-card); border: 1px solid var(--gallery-border); border-radius: var(--gallery-radius); }
    .gallery-rail-card h2 { margin: 0 0 8px; font-size: 1.7rem; line-height: 1; }
    .gallery-swatches { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; padding: 0; margin: 0; list-style: none; }
    .gallery-swatches span { display: block; aspect-ratio: 1; border-radius: 12px; border: 1px solid var(--gallery-border); background: var(--swatch); }
    .gallery-swatches b { display: block; margin-top: 5px; font-size: 0.68rem; overflow-wrap: anywhere; }
    .gallery-proof-list { display: grid; gap: 10px; margin: 0; }
    .gallery-proof-detail summary { cursor: pointer; font-weight: 800; }
    .gallery-proof-list div { padding-top: 10px; border-top: 1px solid var(--gallery-border); }
    .gallery-proof-list dt { color: var(--gallery-muted); font-size: 0.7rem; text-transform: uppercase; font-weight: 900; }
    .gallery-proof-list dd { margin: 3px 0 0; }
    @media (max-width: 900px) {
      .gallery-topbar, .gallery-detail-header, .gallery-detail-layout { grid-template-columns: 1fr; }
      .gallery-shell, .gallery-detail-layout { width: min(100%, calc(100vw - 32px)); }
      .gallery-large-preview { min-height: 420px; }
    }
    @media (max-width: 520px) {
      .gallery-topbar { padding-inline: 20px; }
      .gallery-filters, .gallery-toolbar { max-width: 100%; }
      .gallery-grid { grid-template-columns: 1fr; }
      .gallery-card { width: 100%; max-width: 100%; }
      .gallery-card-preview img { object-fit: contain; }
      .gallery-filters button, .gallery-toolbar a, .gallery-toolbar button { white-space: normal; }
      .gallery-hero h1, .gallery-detail-header h1 { font-size: clamp(1.75rem, 8.8vw, 2.1rem); }
      .gallery-hero h1 { max-width: 11ch; }
      .gallery-hero p:not(.gallery-kicker) { max-width: 32ch; }
    }
    """


def _primary_asset(route: Mapping[str, Any]) -> Mapping[str, Any]:
    assets = route_assets(route)
    return assets[0] if assets else {}


def _route_id(route: Mapping[str, Any]) -> str:
    return display_text(route.get("id"), fallback=slugify(display_text(route.get("title")), fallback="route"))


def _safe_asset_path(root: Path, src: str) -> Path | None:
    path, _ = _safe_asset_path_result(root, src)
    return path


def _safe_asset_path_result(root: Path, src: str) -> tuple[Path | None, str]:
    src = display_text(src)
    if not src or src.startswith("data:") or src.startswith("http://") or src.startswith("https://"):
        return None, "unsafe asset path: missing, remote, or inline asset src"
    path = Path(src)
    if path.is_absolute() or ".." in path.parts:
        return None, f"unsafe asset path: {src}"
    resolved = (root / path).resolve()
    assets_root = (root / "assets").resolve()
    if not resolved.is_relative_to(assets_root):
        return None, f"unsafe asset path: {src}; public gallery assets must stay inside pack assets"
    if not resolved.exists():
        return None, f"generated image asset file not found: {src}"
    return resolved, ""


def _gallery_asset_eligibility(
    root: Path, pack: Mapping[str, Any], route_id: str, asset: Mapping[str, Any]
) -> GalleryEligibility:
    kind = display_text(asset.get("kind"))
    if kind not in PUBLIC_GALLERY_IMAGE_KINDS:
        return GalleryEligibility(
            ok=False,
            reason=f"primary visual kind is {kind or '<missing>'}; fallback boards stay internal/offline",
        )
    path, path_reason = _safe_asset_path_result(root, display_text(asset.get("src")))
    if path is None:
        return GalleryEligibility(ok=False, reason=path_reason)
    asset_receipt_id = display_text(asset.get("receipt_id"))
    if not asset_receipt_id:
        return GalleryEligibility(ok=False, asset_path=path, reason="asset missing receipt_id")
    route_receipt = _gallery_receipt_for_route(pack, route_id)
    receipt = _gallery_receipt_for_route(pack, route_id, receipt_id=asset_receipt_id)
    if receipt is None and route_receipt is None:
        return GalleryEligibility(ok=False, asset_path=path, reason="missing generated_live image receipt")
    if receipt is None:
        return GalleryEligibility(
            ok=False,
            asset_path=path,
            receipt=route_receipt,
            reason="asset receipt_id does not match image receipt",
        )
    receipt_id = display_text(receipt.get("receipt_id"))
    if asset_receipt_id != receipt_id:
        return GalleryEligibility(
            ok=False,
            asset_path=path,
            receipt=receipt,
            reason="asset receipt_id does not match image receipt",
        )
    receipt_reason = _receipt_public_block_reason(receipt)
    if receipt_reason:
        return GalleryEligibility(ok=False, asset_path=path, receipt=receipt, reason=receipt_reason)
    src = display_text(asset.get("src"))
    receipt_src = display_text(receipt.get("asset_src"))
    if receipt_src != src:
        return GalleryEligibility(
            ok=False,
            asset_path=path,
            receipt=receipt,
            reason="receipt asset_src does not match displayed asset",
        )
    receipt_hash = display_text(receipt.get("asset_sha256"))
    if not receipt_hash:
        return GalleryEligibility(ok=False, asset_path=path, receipt=receipt, reason="receipt missing asset_sha256")
    asset_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if asset_hash != receipt_hash:
        return GalleryEligibility(
            ok=False,
            asset_path=path,
            receipt=receipt,
            reason="asset sha256 does not match image receipt",
        )
    return GalleryEligibility(ok=True, asset_path=path, receipt=receipt)


def _first_generated_route(
    root: Path, pack: Mapping[str, Any], routes: Sequence[Mapping[str, Any]]
) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    for route in routes:
        asset = _primary_asset(route)
        if _gallery_asset_eligibility(root, pack, _route_id(route), asset).ok:
            return route, asset
    return None


def _proof_receipt(pack: Mapping[str, Any], route_id: str, asset: Mapping[str, Any]) -> tuple[str, str]:
    receipt = _gallery_receipt_for_route(pack, route_id)
    if receipt is not None:
        provider = _provider_label(display_text(receipt.get("provider") or receipt.get("resolved_provider")))
        status = display_text(receipt.get("status"), fallback="generated image")
        return provider, status
    return _provider_label(display_text(asset.get("provider"), fallback="local generator")), "generated image"


def _gallery_receipt_for_route(
    pack: Mapping[str, Any], route_id: str, *, receipt_id: str = ""
) -> Mapping[str, Any] | None:
    for receipt in pack.get("receipts", []):
        if not isinstance(receipt, Mapping):
            continue
        if receipt.get("kind") != "image-generation":
            continue
        if display_text(receipt.get("route_id")) != route_id:
            continue
        if receipt_id and display_text(receipt.get("receipt_id")) != receipt_id:
            continue
        return receipt
    return None


def _receipt_public_block_reason(receipt: Mapping[str, Any]) -> str:
    status = display_text(receipt.get("status"))
    if status != "generated_live":
        return f"receipt status {status or '<missing>'} is not generated_live"
    for key in ("provider", "resolved_provider", "requested_provider", "model", "generation_mode"):
        value = display_text(receipt.get(key)).lower()
        for marker in ("manual-prompt", "offline", "fixture", "fake"):
            if marker in value:
                label = display_text(receipt.get(key), fallback=marker)
                return f"provider {label} is not public proof"
    return ""


def _route_argument(pack: Mapping[str, Any], route: Mapping[str, Any]) -> str:
    for value in (
        route.get("rationale"),
        route.get("thesis"),
        _section_body(route, preferred=("route", "argument", "rationale", "story", "system")),
        _comparison_read(pack, route),
    ):
        text = display_text(value)
        if text:
            return text
    return ""


def _visual_read(route: Mapping[str, Any], asset: Mapping[str, Any]) -> str:
    for value in (
        asset.get("caption"),
        asset.get("alt"),
        route.get("visual_read"),
        route.get("visualRead"),
        route.get("image_direction"),
        _section_body(route, preferred=("visual", "image", "composition", "look", "surface")),
    ):
        text = _public_non_telemetry_text(value)
        if text:
            return text
    return ""


def _section_body(route: Mapping[str, Any], *, preferred: Sequence[str]) -> str:
    sections = route.get("sections")
    if not isinstance(sections, Sequence) or isinstance(sections, (str, bytes)):
        return ""
    fallback = ""
    for section in sections:
        if not isinstance(section, Mapping):
            continue
        title = display_text(section.get("title") or section.get("label")).lower()
        body = display_text(section.get("body") or section.get("text") or section.get("copy"))
        if not body:
            continue
        if not fallback:
            fallback = body
        if any(marker in title for marker in preferred):
            return body
    return fallback


def _comparison_read(pack: Mapping[str, Any], route: Mapping[str, Any]) -> str:
    row = _route_comparison_row(pack, route)
    if not row:
        return ""
    parts = [
        display_text(row.get(key))
        for key in ("first_build_move", "best_for", "steal", "do_not_copy", "risk")
    ]
    return " ".join(part for part in parts if part)


def _route_comparison_row(pack: Mapping[str, Any], route: Mapping[str, Any]) -> Mapping[str, Any]:
    route_id = _route_id(route)
    route_title = display_text(route.get("title") or route.get("name"))
    candidates = pack.get("route_comparison") or pack.get("routeComparison") or route.get("route_comparison")
    if isinstance(candidates, Mapping):
        candidates = candidates.get("routes") or candidates.get("rows") or []
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        return {}
    for row in candidates:
        if not isinstance(row, Mapping):
            continue
        row_ids = [
            display_text(row.get(key))
            for key in ("route_id", "id", "route_ref", "route", "title", "name")
        ]
        if route_id in row_ids or (route_title and route_title in row_ids):
            return row
    return {}


def _public_non_telemetry_text(value: Any) -> str:
    text = display_text(value)
    if not text:
        return ""
    lowered = text.lower()
    telemetry_markers = (
        "generated proof",
        "public proof",
        "actual font loaded",
        "generated_live",
        "manual_prompt",
        "manual-prompt",
        "visual-direction-board",
        "fallback",
        "offline",
        "fixture",
        "fake",
        "provider",
        "receipt",
        "request_config",
        "asset_sha256",
        "sha256",
        "launch-gate",
    )
    if any(marker in lowered for marker in telemetry_markers):
        return ""
    if lowered in {"preview", "preview image"} or lowered.endswith(" preview"):
        return ""
    return text


def _type_summary(pack: Mapping[str, Any], route_id: str, route: Mapping[str, Any]) -> tuple[str, str, str, str]:
    option = _font_option_for_route(pack, route_id)
    preview = resolve_font_preview(option) if option else None
    family = display_text(
        option.get("name") if isinstance(option, Mapping) else "",
        fallback=display_text(preview.rendered_family if preview else "", fallback="Type system"),
    )
    type_direction = display_text(
        route.get("type") or route.get("typography"),
        fallback=display_text(option.get("sample_headline") if isinstance(option, Mapping) else "", fallback=family),
    )
    rationale = _public_type_rationale(
        option.get("why_london_chose_it") if isinstance(option, Mapping) else "",
        option.get("why_this_route_not_other_route") if isinstance(option, Mapping) else "",
    )
    best_use = display_text(option.get("best_use") if isinstance(option, Mapping) else "")
    return family, type_direction, rationale, best_use


def _font_option_for_route(pack: Mapping[str, Any], route_id: str) -> Mapping[str, Any]:
    for group in pack.get("font_options", []):
        if not isinstance(group, Mapping) or display_text(group.get("route_id")) != route_id:
            continue
        options = [option for option in group.get("options", []) if isinstance(option, Mapping)]
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


def _copy_preview_asset(item: GalleryItem, assets_dir: Path) -> str:
    if item.preview_source_path is None:
        return ""
    suffix = item.preview_source_path.suffix or ".png"
    file_name = f"{item.slug}{suffix}"
    target = assets_dir / file_name
    if item.preview_source_path.resolve() != target.resolve():
        with item.preview_source_path.open("rb") as source_file, target.open("wb") as target_file:
            shutil.copyfileobj(source_file, target_file)
    return f"assets/{file_name}"


def _unique_slug(slug: str, used: set[str]) -> str:
    candidate = slug
    counter = 2
    while candidate in used:
        candidate = f"{slug}-{counter}"
        counter += 1
    used.add(candidate)
    return candidate
