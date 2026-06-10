# London Provider Registry

London runs locally first for the brain, session, pack, workbench, and
prototype. Image generation is different: normal runs do not fake concept art.
They either use a ready local/API generator or export route-specific visual
direction boards that are clearly labeled as direction, not generated art.

## Image Ladder

London reports the image ladder in these public tiers:

1. Configured API/live providers: Gemini, OpenAI, BFL/FLUX, fal, Replicate.
   These are all metered image lanes. Gemini is the preferred receipt-backed
   package lane when paid image generation is explicitly enabled. OpenAI is the
   taste benchmark/comparison lane until London has enough package-native OpenAI
   receipts. API image lanes are available to auto mode only when
   `image.allow_paid = true` and `image.spend_limit_usd` covers the estimated
   route count.
2. Free/local generators: Automatic1111, ComfyUI with
   `LONDON_COMFYUI_WORKFLOW`, and Draw Things as the recommended free/local Mac
   path, subject to local compute, model downloads, disk space, and explicit
   command-template setup. A detected Draw Things binary is not enough for auto
   generation; London selects it only when `LONDON_DRAW_THINGS_COMMAND` can run
   through the same prompt-file/output-file receipt contract as other local
   generators.
3. Generic bring-your-own command: `external-cmd` for local scripts, GPU tools,
   or wrappers that receive `{prompt_file}` and `{output}` and write a real image
   file. Receipts expose only the command basename, never command templates or
   local paths.
4. Experimental network provider: Pollinations, opt-in only when
   `image.allow_experimental_free_network = true`.
5. Honest visual direction board: palette swatches, type specimen, composition
   grid, route prompt, London Brain cues, and source cues. Perchance stays
   manual-only; London does not automate Perchance browser or HTTP access.

`--images fixture` is the only public CLI path that emits deterministic SVG
system sketches. `--images none` disables generated images but still keeps the
route prompt and visual direction board for handoff.

## Setup Commands

```bash
london setup
london setup --json
london setup --plan
london setup --install draw-things
london setup --install comfyui
london providers detect --local --json
london providers recommend
london image try "kids lunchbox ritual kit" --provider auto-local --out /tmp/london-image-try
london image try "kids lunchbox ritual kit" --provider comfyui --out /tmp/london-comfyui-try
london image try "kids lunchbox ritual kit" --provider draw-things --out /tmp/london-draw-things-try
```

Setup reports provider states such as `ready_generate`,
`detected_needs_setup`, `missing`, `failed`, and `manual_only`. Auto mode calls
only providers marked `ready_generate`.

## Environment Variables

| Provider | Variables | Notes |
| --- | --- | --- |
| Gemini | `GEMINI_API_KEY` or `GOOGLE_API_KEY`; optional `LONDON_GEMINI_IMAGE_MODEL`, `LONDON_GEMINI_API_VERSION`, `LONDON_GEMINI_IMAGE_ASPECT_RATIO`, `LONDON_GEMINI_IMAGE_SIZE`, `LONDON_GEMINI_RESPONSE_MODALITIES`, `LONDON_GEMINI_REQUEST_CONFIG_MODE` | Metered image lane. Default image model is Gemini Pro Image Preview, `gemini-3-pro-image-preview`, at REST `v1beta`, `16:9`, `4K`; London uses a $0.25/image ceiling for spend preflight. Use `gemini-3.1-flash-image` / Nano Banana 2 as the high-efficiency fallback and `gemini-2.5-flash-image` only as a cheaper/object-preserving fallback or adapter-debug lane. |
| BFL / FLUX | `BFL_API_KEY`; optional `LONDON_BFL_BASE_URL`, `LONDON_BFL_MODEL_PATH`, `LONDON_BFL_IMAGE_WIDTH`, `LONDON_BFL_IMAGE_HEIGHT`, `LONDON_BFL_MAX_POLLS`, `LONDON_BFL_POLL_SECONDS` | Metered lane; auto uses it only when paid use is explicitly enabled. Default explicit BFL generation uses `/v1/flux-2-pro-preview`; set `LONDON_BFL_MODEL_PATH=/v1/flux-2-pro` when a fixed snapshot is required. |
| OpenAI | `OPENAI_API_KEY`; optional `LONDON_OPENAI_IMAGE_MODEL`, `LONDON_OPENAI_IMAGE_SIZE`, `LONDON_OPENAI_IMAGE_QUALITY`, `LONDON_OPENAI_IMAGE_OUTPUT_FORMAT`, `LONDON_OPENAI_IMAGE_OUTPUT_COMPRESSION`, `LONDON_OPENAI_IMAGE_BACKGROUND`, `LONDON_OPENAI_IMAGE_MODERATION` | Metered image/language lane through London direct HTTPS adapter. Default image model is `gpt-image-2`, `3840x2160`, `quality=high`; London uses a $0.35/image ceiling for spend preflight and receipts the exact request options. |
| fal | `FAL_KEY` or `FAL_API_KEY` | Metered FLUX API lane; gated by estimated spend before any provider call. |
| Replicate | `REPLICATE_API_TOKEN` or `REPLICATE_API_KEY` | Metered Replicate FLUX lane; gated by estimated spend before any provider call. |
| Firecrawl | `FIRECRAWL_API_KEY` | Optional public web extraction for source packs. |
| Automatic1111 | `LONDON_AUTOMATIC1111_URL` | Defaults to `http://127.0.0.1:7860`; ready when `/sdapi/v1/sd-models` responds. |
| ComfyUI | `LONDON_COMFYUI_URL`, `LONDON_COMFYUI_WORKFLOW`; optional `LONDON_COMFYUI_MODEL_PROFILE`, `LONDON_COMFYUI_PROFILE`, `LONDON_COMFYUI_MODEL_FAMILY`, `LONDON_COMFYUI_LICENSE_POSTURE`, `LONDON_COMFYUI_COMMERCIAL_USE`, `LONDON_COMFYUI_CHECKPOINTS`, `LONDON_COMFYUI_MAX_POLLS`, `LONDON_COMFYUI_POLL_SECONDS` | Local workflow runner. Workflow JSON must exist and a ComfyUI server must answer before auto generation is ready. Receipts record model profile/family, workflow filename/hash, license posture, commercial-use posture, and checkpoint count, never absolute workflow or checkpoint paths. |
| Draw Things CLI | `LONDON_DRAW_THINGS_COMMAND`, `LONDON_DRAW_THINGS_CLI` | Recommended free/local Mac path, subject to local compute and model setup. `LONDON_DRAW_THINGS_COMMAND` must include `{prompt_file}` and `{output}`; `{cli}` is filled from `LONDON_DRAW_THINGS_CLI` or a discovered `draw-things-cli` / `draw-things` binary. A binary by itself is `detected_needs_setup`, not ready. |
| External command | `LONDON_EXTERNAL_IMAGE_COMMAND` or `LONDON_LOCAL_IMAGE_COMMAND` | Bring-your-own local pipe. The command receives `{prompt_file}` and `{output}` placeholders and must write a real image file. Receipts show the command name only, never local output paths. |
| External command options | `LONDON_EXTERNAL_IMAGE_OUTPUT_DIR`, `LONDON_EXTERNAL_IMAGE_RESULT`, `LONDON_EXTERNAL_IMAGE_TIMEOUT`, `LONDON_EXTERNAL_IMAGE_EXTENSION` | Optional local command controls. Use them for a stable output directory/result path without exposing those paths in pack artifacts. |
| InvokeAI | `LONDON_INVOKEAI_URL` | Detected for setup visibility only until a verified output + receipt adapter lands. |

London reports only whether keys exist. It never prints, saves, hashes,
uploads, prefixes, suffixes, or length-reports key values.

London does not auto-read `.env`. Use environment variables, a secret manager,
or an explicit env file for one command:

```bash
cp .env.example .env
chmod 600 .env
$EDITOR .env
london setup --env-file .env
```

Config files store preferences only, never raw keys:

```toml
[image]
primary = "auto"
backups = ["gemini", "openai", "manual-prompt"]
allow_paid = false
spend_limit_usd = 1.00
allow_experimental_free_network = false
```

`london setup` discloses the metered image ceilings currently used for
preflight. To downshift image spend, run `london config set image.quality
standard` or pass `--image-quality model-default`; to disable generated images
entirely, pass `--images none`.

## ComfyUI Local Lab

ComfyUI is a local workflow runner, not one model. London keeps the executable
provider as `comfyui`, then uses model-profile metadata to make receipts honest:

- FLUX.1 schnell is the safer permissive local default (`apache-2.0`,
  commercial use permitted).
- Ideogram 4 is a strong design/layout/typography prototype profile, but public
  weights are non-commercial unless licensed.
- HiDream-I1 is a commercial-friendly local quality candidate, but hardware
  requirements are high.
- Ideogram Partner Nodes/API lanes are paid/cloud ComfyUI credits, not free
  local generation.

London marks ComfyUI `ready_generate` only when both a running ComfyUI server and
a workflow JSON are configured. `london setup --install comfyui` is guidance
only; it does not install GPU software, download weights, or launch ComfyUI.

```bash
pip install comfy-cli
comfy install
comfy launch

cat > "$HOME/.config/london/live-comfyui-ideogram.env" <<'EOF'
LONDON_COMFYUI_URL=http://127.0.0.1:8188
LONDON_COMFYUI_WORKFLOW=/path/to/ideogram-4-london-workflow.json
LONDON_COMFYUI_MODEL_PROFILE=ideogram-4
LONDON_COMFYUI_MODEL_FAMILY=ideogram-4
LONDON_COMFYUI_LICENSE_POSTURE=non-commercial-public-weights
LONDON_COMFYUI_COMMERCIAL_USE=not-permitted-without-commercial-license
EOF

london setup --env-file "$HOME/.config/london/live-comfyui-ideogram.env"

london image try "poster system for a joyful lunchbox ritual kit" \
  --provider comfyui \
  --out /tmp/london-comfyui-ideogram-try \
  --env-file "$HOME/.config/london/live-comfyui-ideogram.env"
```

## Provider Model Map

London's current Phase 8 image defaults are opinionated:

- Taste benchmark: OpenAI `gpt-image-2`, through `/v1/images/generations`,
  defaulting to high-quality 4K landscape.
- Best Gemini package lane: `gemini-3-pro-image-preview` / Nano Banana Pro,
  defaulting to 4K.
- High-efficiency fallback: Gemini `gemini-3.1-flash-image` / Nano Banana 2.
- Cheap/object-preserving fallback: Gemini `gemini-2.5-flash-image` / original
  Nano Banana.
- Premium comparison lane: BFL `/v1/flux-2-pro-preview`, with `/v1/flux-2-pro`
  as the pinned reproducibility endpoint.
- If a Gemini Pro smoke returns `404`, first check that the request uses
  `gemini-3-pro-image-preview` on REST `v1beta`, then check billing/account
  access and request config before treating it as a taste failure.
- Local image lab: ComfyUI with named profiles. Use FLUX.1 schnell as the safer
  permissive local default; expose Ideogram 4 as an opt-in design/typography
  lane labeled non-commercial unless a commercial license is configured; treat
  Partner Nodes/API lanes as paid/cloud, not local/free.
- Do not auto-rank BFL above Gemini/OpenAI just because it is premium. London's
  launch proof cares about taste, product-object feel, real receipts, and spend
  discipline.

Live provider receipts record the safe request config: endpoint/model path,
image size/aspect ratio, quality/output format where relevant, polling behavior,
estimated cost, spend limit, and the fact that secrets and signed delivery URLs
were not printed or stored.

`chromadb` stays in base dependencies because London uses it as the derived
retrieval path for the public taste brain. Missing live provider keys are not
blockers; the local session path still exports visual direction boards and
receipts.
