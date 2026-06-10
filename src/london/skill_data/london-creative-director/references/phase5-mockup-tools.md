# Phase 5: Layout & Mockup Tools

## superdesign MCP — Quick Layout Exploration
```
mcp__superdesign__superdesign_generate({
  design_type: "component",
  prompt: "detailed description of the section",
  framework: "react",
  variations: 3
})
```
Generate 2-3 variations per section. Open in browser. React. Pick the best.

View all mockups:
```
mcp__superdesign__superdesign_live_gallery({ port: 3001 })
```

## 21st.dev Magic MCP — Component Inspiration
```
mcp__magic__21st_magic_component_inspiration({
  message: "description of what you need",
  searchQuery: "search terms"
})
```
Browse BEFORE building each component type. Don't reinvent what exists.

## Variant.com — High-Fidelity React Explorations
Tom runs prompts in Variant.com browser. London writes the prompts.

**Prompt template:**
```
Create a [component type] for [brand name].
Background: [hex color] ([description]).
Typography: [display font] (headlines), [body font] (body).
Accent: [accent color — material reference].
Effect: [specific effect being explored].
Context: [project context, aesthetic direction].
Reference sites: [2-3 benchmark sites].
```

Write prompts. Hand to Tom. Wait for screenshots. Extract patterns.

## Direct HTML/CSS Prototypes
For interactive elements or specific micro-interactions:
1. Write a quick HTML file with inline styles
2. Open in browser
3. Evaluate: does the interaction feel right?
4. Iterate before committing to the full build

## Web Design Reference Sites

### Godly.website
"Best-in-class, constantly updated web design."
Visit before designing any web experience. Study what's cutting edge.

### Commerce Cream (commercecream.com)
Beautiful Shopify stores. Art direction + conversion balance.
Visit for e-commerce, product pages, checkout flows.

### Cargo.site
"More creative and design-forward templates."
Layout inspiration. Use aesthetic ideas, build elsewhere.

### Mobbin (mobbin.com)
Real UI/UX from best apps. Component patterns archive.

## Emerging Tools (Research)
- **Google Stitch** (stitch.withgoogle.com) — AI UI generation, Gemini-powered
- **Trellis 3D** (trellis3d.net) — 3D asset generation from text/images (Microsoft, 2B params)
