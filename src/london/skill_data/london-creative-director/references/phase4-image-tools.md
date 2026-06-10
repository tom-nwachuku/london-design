# Phase 4: Image Direction Tools

## Art-Directed Photography Sources

### Death to Stock (deathtostock.com) — PRIMARY
London's go-to (6 video citations). "The only super art-directed stock imagery website."
- Non-hero lifestyle/environmental imagery
- Section backgrounds, email campaigns, lifestyle filler
- Updated weekly with high-quality content

### The Dieline (thedieline.com) — FOR PACKAGING
"The design internet's packaging library." Award-winning packaging systems.
- Study before designing ANY packaging element
- "Bypass generic Canva templates and Instagram scrolls"

### Additional Sources
- **Unsplash** — higher quality than generic stock, but still curated needed
- **Brand-specific lookbooks** — via International Library of Fashion Research
- **LABETT** (iPhone app) — photo editing with "savage" filters for on-brand treatment

## AI Image Generation

### media-pipeline MCP (Gemini)
```
mcp__media-pipeline__create_asset({
  prompt: "detailed prompt",
  outputPath: "projects/<name>/assets/images/<filename>.png",
  aspectRatio: "16:9"
})
```
Best for: lifestyle, environmental, atmospheric shots.

### BFL FLUX (check BFL_API_KEY first)
```bash
echo $BFL_API_KEY  # verify key exists
curl -s -X POST "https://api.bfl.ai/v1/flux-2-pro" \
  -H "x-key: $BFL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "...", "width": 1024, "height": 1344}'
```
Best for: product photography, hero shots, detail macro. Higher quality than Gemini for products.

### Prompt Formula
[Subject] + [Attributes] + [Environment] + [Style] + [Lighting] + [Composition]
- No negative prompts — describe what you WANT
- Specify lighting — biggest impact on quality
- Natural prose, not comma-separated tags
- Hex colors: use #RRGGBB with description ("deep amber #C17F24")

## Verification Protocol
After EVERY generation:
1. Open the image
2. Does it show the RIGHT product? (not a different product category)
3. Does it match the aesthetic direction from Phase 2?
4. Is the lighting/composition professional?
5. If NO to any → regenerate with adjusted prompt
6. Update tool usage tracker count

## Image Count Guidelines
- Single product page: ~15 images
- Full brand pitch: ~30+ images
- Product line with variants: ~50+ images
- London uses MASSIVE image libraries. More is better.
