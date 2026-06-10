# Phase 3: Typography & Color Tools

## Typography Research (London's workflow)

### Step 1: Fonts In Use (fontsinuse.com)
London's #1 cited resource (7 videos). "One of the best reference tools for typography on the internet."
- Search by category, industry, or year
- See fonts in REAL applications (packaging, posters, books, digital)
- Document: which fonts do brands in THIS space actually use?

### Step 2: Fontshare (fontshare.com)
100+ curated free fonts. Has a "Pairs" section.
- Browse headline + body combinations
- Download to `projects/<name>/assets/fonts/`
- Never use Google Fonts when Fontshare has the option

### Step 3: Font Sniper (Raycast extension)
Identifies fonts from any website loaded in browser.
- When you see a font on a reference site and need to ID it

### Anti-Pattern: DaFont
London explicitly says to stop downloading from DaFont for professional work.

## Color Research

### Study Complete Brand Systems
London studies systems with hex, RGB, CMYK, Pantone values:
- Gap Brand Guideline (Pantone 655 blue)
- Bolt Brand Guideline (primary/secondary + gradients)
- The North Face (#D12224 red, grey shades, white)

### London's Color Philosophy
- Bold, vibrant, intentional — never arbitrary
- Colors serve brand personality and era reference
- Retro-inspired: orange, mint green, pastel pink, yellow
- "Bold colors paired with sophisticated packaging"

## Design System Generation

### ui-ux-pro-max skill
```bash
python3 ~/.claude/skills/ui-ux-pro-max/scripts/search.py \
  "search terms matching aesthetic direction" \
  --design-system --persist -p "ProjectName"
```
Generates `design-system/MASTER.md` with tokens: colors, type scale, spacing, effects.
