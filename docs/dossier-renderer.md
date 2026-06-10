# Workbench Renderer

The static rendering surface is now the Pack Reader / Creative Moodboard
Workbench. The renderer accepts a dict-like London Pack and produces
deterministic HTML without provider keys, network calls, screenshots, or
archive-only assets.

## Modules

- `london.render.render_dossier(pack)` returns the workbench HTML.
- `london.render.write_dossier(pack, path)` writes `index.html`.
- `london.prototype.render_static_prototype(pack, route_id=None)` returns one
  first-pass prototype route.
- `london.prototype.write_static_prototype(pack, out_dir, route_id=None)` writes
  `prototype/index.html`.
- `london.workbench.enrich_workbench_pack(pack)` derives Pack Reader fields from
  the session pack.

## Pack Shape

The renderer is intentionally tolerant and will derive missing workbench fields
from the pack when needed. The full public output includes:

- `conversation`
- `route_comparison`
- `font_options`
- `moodboard_tiles`
- `copy_blocks`
- `next_steps`
- `evidence_summary`
- `routes`, each with route text, palette, tags, assets, sections, critique, and
  handoff implications

Palette values can be hex strings or dictionaries with `hex`, `name`, and
`role`. Assets can provide `src`, `title`, `alt`, `caption`, and `prompt`.
Prompt-card assets do not require `src`; the renderer displays them as copyable
handoff panels. Deterministic SVG system sketches are fixture-only, so the
generated workbench and prototype remain honest without Gemini, BFL/FLUX,
OpenAI, Firecrawl, Playwright, or any provider key.

## Visual Contract

The workbench uses an editorial studio layout:

- brief snapshot and sticky navigation
- seven-gate London conversation
- route switcher and comparison matrix
- moodboard canvas with bento tiles
- Font Lab with three options per route
- evidence drawer and receipts
- copy/handoff console

Tests reject old placeholder/grid language by checking HTML structure, class
names, copy controls, collapsible evidence, and route-specific prototype output.
