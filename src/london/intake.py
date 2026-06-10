from __future__ import annotations

from html import escape
from pathlib import Path


INTAKE_FIELDS: tuple[dict[str, str], ...] = (
    {
        "id": "refusals",
        "label": "Refusals",
        "summary": "What this should not become",
    },
    {
        "id": "anti_audience",
        "label": "Anti-audience",
        "summary": "Who this is not for",
    },
    {
        "id": "seeds",
        "label": "Seeds",
        "summary": "References, fragments, instincts",
    },
)


def build_intake_markdown(
    brief: str,
    *,
    refusals: str = "",
    anti_audience: str = "",
    seeds: str = "",
    artifact_hint: str = "",
) -> str:
    """Build the markdown brief emitted by the intake container.

    The optional inputs are feed notes, not directives. They are preserved as open
    text and never converted into front matter or CLI flags, so they cannot override
    London's artifact resolution order.
    """

    brief_text = _clean_required(brief)
    sections = [
        "# London Intake Brief",
        "",
        "## Brief",
        "",
        brief_text,
        "",
        "## Optional feeds",
        "",
        "These notes are open context for London. They are not prescriptions.",
        "",
        "### Refusals",
        "",
        _optional_text(refusals),
        "",
        "### Anti-audience",
        "",
        _optional_text(anti_audience),
        "",
        "### Seeds",
        "",
        _optional_text(seeds),
    ]
    hint = artifact_hint.strip()
    if hint:
        sections.extend(
            [
                "",
                "### Artifact hint",
                "",
                f"I think this might be: {hint}",
                "",
                "London may reframe this. This is not an artifact override.",
            ]
        )
    return "\n".join(sections).strip() + "\n"


def render_intake_html() -> str:
    """Render the self-contained static intake surface."""

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>London Intake</title>
    <style>
      :root {{
        --ink: #151514;
        --paper: #f7f4ef;
        --card: #fffdfa;
        --line: #d8d0c4;
        --muted: #6f675f;
        --accent: #a33f2f;
        --focus: #1d5f74;
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        min-height: 100vh;
        color: var(--ink);
        background: var(--paper);
      }}
      main {{
        width: min(1120px, calc(100vw - 32px));
        margin: 0 auto;
        padding: 32px 0;
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(320px, 0.85fr);
        gap: 24px;
      }}
      header {{
        grid-column: 1 / -1;
        display: flex;
        align-items: end;
        justify-content: space-between;
        gap: 20px;
        border-bottom: 1px solid var(--line);
        padding-bottom: 18px;
      }}
      h1, h2, p {{ margin: 0; }}
      h1 {{ font-size: 2rem; font-weight: 760; }}
      .honesty {{ color: var(--muted); font-size: 0.95rem; }}
      form, .preview {{
        background: var(--card);
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 18px;
      }}
      form {{ display: grid; gap: 16px; }}
      label, summary {{ font-weight: 700; }}
      textarea, input {{
        width: 100%;
        border: 1px solid var(--line);
        border-radius: 6px;
        background: #fff;
        color: var(--ink);
        font: inherit;
        line-height: 1.45;
        padding: 12px;
      }}
      textarea:focus, input:focus, button:focus {{
        outline: 3px solid color-mix(in srgb, var(--focus) 28%, transparent);
        border-color: var(--focus);
      }}
      textarea {{ min-height: 180px; resize: vertical; }}
      .optional textarea {{ min-height: 104px; margin-top: 8px; }}
      details {{
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 12px;
        background: #fbf8f2;
      }}
      details[open] {{ display: grid; gap: 12px; }}
      summary {{ cursor: pointer; }}
      .field {{ display: grid; gap: 8px; }}
      .field span {{ color: var(--muted); font-size: 0.9rem; }}
      .actions {{ display: flex; gap: 10px; flex-wrap: wrap; }}
      button {{
        border: 1px solid var(--ink);
        border-radius: 6px;
        background: var(--ink);
        color: var(--paper);
        font: inherit;
        font-weight: 700;
        padding: 10px 14px;
        cursor: pointer;
      }}
      button.secondary {{ background: transparent; color: var(--ink); }}
      .preview {{ display: grid; gap: 14px; align-content: start; }}
      pre {{
        margin: 0;
        white-space: pre-wrap;
        word-break: break-word;
        border: 1px solid var(--line);
        border-radius: 8px;
        background: #111;
        color: #f7f4ef;
        min-height: 360px;
        padding: 14px;
        font: 0.92rem ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      }}
      .command {{
        border-left: 3px solid var(--accent);
        padding-left: 12px;
        color: var(--muted);
        font-size: 0.92rem;
      }}
      @media (max-width: 860px) {{
        main {{ grid-template-columns: 1fr; }}
        header {{ align-items: start; flex-direction: column; }}
      }}
    </style>
  </head>
  <body>
    <main>
      <header>
        <div>
          <h1>London Intake</h1>
          <p class="honesty">Local draft only. Nothing is saved or sent.</p>
        </div>
        <p class="command">Run the copied brief with <code>london brief.md</code></p>
      </header>
      <form data-intake-form>
        <div class="field">
          <label for="brief">Brief</label>
          <textarea id="brief" name="brief" required data-brief placeholder="Paste the real brief here."></textarea>
        </div>
        <details class="optional">
          <summary>Optional feeds</summary>
          {_optional_fields_html()}
          <div class="field">
            <label for="artifact_hint">Artifact hint</label>
            <span>London may reframe it.</span>
            <input id="artifact_hint" name="artifact_hint" data-artifact-hint placeholder="website, app, product, brand, service, something else">
          </div>
        </details>
        <div class="actions">
          <button type="button" data-copy>Copy brief</button>
          <button type="button" class="secondary" data-download>Download markdown</button>
        </div>
      </form>
      <section class="preview" aria-label="Markdown preview">
        <h2>Markdown</h2>
        <pre data-preview aria-live="polite"></pre>
      </section>
    </main>
    <script>
      const fields = {{
        brief: document.querySelector("[data-brief]"),
        refusals: document.querySelector("[data-field='refusals']"),
        antiAudience: document.querySelector("[data-field='anti_audience']"),
        seeds: document.querySelector("[data-field='seeds']"),
        artifactHint: document.querySelector("[data-artifact-hint]"),
        preview: document.querySelector("[data-preview]")
      }};
      const optional = value => value.trim() || "None yet.";
      const build = () => {{
        const parts = [
          "# London Intake Brief",
          "",
          "## Brief",
          "",
          fields.brief.value.trim(),
          "",
          "## Optional feeds",
          "",
          "These notes are open context for London. They are not prescriptions.",
          "",
          "### Refusals",
          "",
          optional(fields.refusals.value),
          "",
          "### Anti-audience",
          "",
          optional(fields.antiAudience.value),
          "",
          "### Seeds",
          "",
          optional(fields.seeds.value)
        ];
        const hint = fields.artifactHint.value.trim();
        if (hint) {{
          parts.push("", "### Artifact hint", "", `I think this might be: ${{hint}}`, "", "London may reframe this. This is not an artifact override.");
        }}
        return parts.join("\\n").trim() + "\\n";
      }};
      const sync = () => {{ fields.preview.textContent = build(); }};
      document.querySelector("[data-intake-form]").addEventListener("input", sync);
      document.querySelector("[data-copy]").addEventListener("click", async () => {{
        await navigator.clipboard.writeText(build());
      }});
      document.querySelector("[data-download]").addEventListener("click", () => {{
        const blob = new Blob([build()], {{ type: "text/markdown" }});
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "london-brief.md";
        a.click();
        URL.revokeObjectURL(url);
      }});
      sync();
    </script>
  </body>
</html>
"""


def write_intake_html(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_intake_html(), encoding="utf-8")


def _optional_fields_html() -> str:
    blocks = []
    for field in INTAKE_FIELDS:
        field_id = field["id"]
        blocks.append(
            f"""
          <div class="field">
            <label for="{escape(field_id, quote=True)}">{escape(field["label"])}</label>
            <span>{escape(field["summary"])}</span>
            <textarea id="{escape(field_id, quote=True)}" name="{escape(field_id, quote=True)}" data-field="{escape(field_id, quote=True)}" placeholder="None yet."></textarea>
          </div>"""
        )
    return "".join(blocks)


def _clean_required(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Intake brief is required")
    return cleaned


def _optional_text(value: str) -> str:
    cleaned = value.strip()
    return cleaned or "None yet."
