# London

**A creative director in your terminal.** Give London a one-line brief; get back a complete, opinionated creative direction — research, a reframe, competing visual routes, typography and color with rationale, a moodboard, image prompts (or generated images), and a build-ready handoff — as a single self-contained HTML dossier.


## Try it in 60 seconds — no API key, no signup

```bash
uv tool install london-design   # or: pip install london-design

london examples/brief.md --offline --out my-first-pack
open my-first-pack/index.html
```

The `--offline` demo is honest about what it is — a deterministic sample showing the dossier, not the model's thinking. The real thing needs a model (below), and the output is labeled so you always know which one you got.

## The defining idea

London runs **inside a model** — the model does the creative thinking; everything else is honest plumbing around it. There is no template bank pretending to be taste. Three ways to give him a brain:

| Mode | When | Needs |
|---|---|---|
| **In-session** | You're inside Claude Code — London detects it | Nothing. No key. |
| **API key** | Standalone terminal | `ANTHROPIC_API_KEY` |
| **Offline** | Demo / CI / no model | Nothing — clearly labeled deterministic sample |

No silent fallbacks: if London can't reach a model he says so and stops — he never quietly degrades to canned output.

## London can't grade his own homework

Every run ships with an independent audit. Five named inspectors check London's *claims* against the run's *actual telemetry*:

- **Source Auditor** — every cited source ID verified against what was really consulted; unverifiable citations get flagged, not hidden
- **Grounding Inspector** — how deeply he actually queried his design brain
- **Distinctness Referee** — are the routes *genuinely* different (perceptual color distance, not vibes)
- **Output Manifest** — required regions at honest cardinality, no padding
- **Type Selection Referee** — the font lab offers real range, not three safe defaults

When telemetry isn't available the grader says **n/a** — never a fabricated number. A score you can't trust is worse than no score.

## What's in a pack

```
my-first-pack/
├── index.html        ← the dossier: moodboard, routes, comparison,
│                       font lab, conversation, evidence, grader, handoff
├── prototype/        ← interactive static prototype
├── london-pack.json  ← the full structured direction (schema-validated)
├── DESIGN.md         ← handoff for your designer
└── BUILD-HANDOFF.md  ← handoff for your builder
```

Everything is self-contained — no server, no build step, no remote assets. Copy the folder anywhere and open `index.html`.

## Images (optional, never silent spend)

London writes image prompts by default — copyable cards in the dossier. If you want him to generate:

```bash
london setup        # guided setup — shows exactly what each lane costs
```

Local generators (ComfyUI, Automatic1111, Draw Things) are free lanes. Cloud lanes (Gemini, OpenAI, BFL/FLUX, fal, Replicate) are **metered and gated**: nothing paid runs without `image.allow_paid=true` plus a spend limit, and London refuses up front when the estimated run cost exceeds it. The OpenAI default is 4K/high (~$0.25/image) — `london config set image.quality standard` downshifts it.

## The brain

London ships with a distilled, sanitized design brain (SQLite, ~4.6 MB) — principles, critique approaches, and workflow knowledge he queries while directing. It contains no raw source media. Swap in your own with `london brain install`.

## Honesty rules (the part we're most proud of)

- Variable-shape output is rendered as given — no padding, no averaging, no template flattening
- Generated vs. fallback vs. manual artifacts are always labeled in the dossier and receipts
- Secrets are presence-checked only — never printed, never stored, never in support reports
- The launch gate (`london launch-gate`) fails honestly when a pack has no live proof — including on our own demo

## Requirements

Python ≥ 3.11. macOS / Linux. `uv` recommended.

## License

MIT
