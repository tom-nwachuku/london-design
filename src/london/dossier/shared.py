from __future__ import annotations

from html import escape
from typing import Any, Mapping, Sequence

from ..text import display_text
from ..workbench import enrich_workbench_pack


def _as_mappings(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _prepared_pack(pack: Mapping[str, Any]) -> dict[str, Any]:
    prepared = dict(pack)
    required = (
        "conversation",
        "route_comparison",
        "font_options",
        "moodboard_tiles",
        "copy_blocks",
        "next_steps",
        "evidence_summary",
    )
    if not all(key in prepared for key in required):
        enrich_workbench_pack(prepared)
    return prepared


def _provider_label(value: str) -> str:
    labels = {
        "bfl": "BFL",
        "gemini": "Gemini",
        "openai": "OpenAI",
        "claude-image": "Claude image",
        "external-cmd": "Local generator",
        "draw-things": "Draw Things",
        "manual-prompt": "Manual prompt",
    }
    return labels.get(value.strip().lower(), value.strip() or "Local generator")


def _clip_detail(value: str, max_chars: int = 118) -> str:
    text = " ".join(display_text(value).replace("\n", " ").split())
    if len(text) <= max_chars:
        return text
    return f"{text[: max(0, max_chars - 3)].rstrip(' ,.;:-')}..."


def _type_role_rows(type_direction: str) -> list[tuple[str, str]]:
    text = " ".join(display_text(type_direction).replace("\n", " ").split())
    if not text:
        return []
    chunks = [
        chunk.strip(" .;:")
        for chunk in text.replace(";", ".").split(".")
        if chunk.strip(" .;:")
    ]
    rows: list[tuple[str, str]] = []
    used_labels: set[str] = set()
    for chunk in chunks:
        lower = chunk.lower()
        if "headline" in lower or "masthead" in lower or "display" in lower:
            label = "Headline"
        elif "body" in lower or "paragraph" in lower or "plainspoken" in lower:
            label = "Body"
        elif "mono" in lower or "label" in lower or "tabular" in lower:
            label = "Label / mono"
        elif "reference" in lower or "inspiration" in lower:
            label = "Reference"
        else:
            label = "Direction"
        if label in used_labels and label != "Direction":
            label = "Direction"
        used_labels.add(label)
        rows.append((label, _clip_detail(chunk, 132)))
        if len(rows) >= 4:
            break
    return rows or [("Direction", _clip_detail(text, 132))]


def _render_type_roles(type_direction: str, *, wrap: bool = False, class_name: str = "type-role-list") -> str:
    rows = _type_role_rows(type_direction)
    if not rows:
        return ""
    items = "".join(
        f"""
        <div>
          <dt>{escape(label)}</dt>
          <dd>{escape(value)}</dd>
        </div>"""
        for label, value in rows
    )
    if not wrap:
        return items
    return f'<dl class="{escape(class_name, quote=True)}">{items}</dl>'


def _public_type_rationale(primary: Any, secondary: Any = "") -> str:
    for value in (primary, secondary):
        text = _strip_type_provenance(display_text(value))
        if text:
            return text
    return ""


def _strip_type_provenance(value: str) -> str:
    text = " ".join(display_text(value).split())
    if not text:
        return ""
    source_markers = (
        "fontshare",
        "google fonts",
        "sourced",
        "source",
        "license",
        "licens",
        "commercial",
        "bundled",
        "sha",
        "proof",
    )
    clauses = []
    for sentence in text.replace("; ", ". ").split(". "):
        candidate = sentence.strip(" .")
        if not candidate:
            continue
        lowered = candidate.lower()
        if any(marker in lowered for marker in source_markers):
            for divider in (" - ", " \u2014 ", " \u2013 "):
                if divider in candidate:
                    tail = candidate.split(divider, 1)[1].strip(" .")
                    if tail and not any(marker in tail.lower() for marker in source_markers):
                        clauses.append(tail)
                    break
            continue
        clauses.append(candidate)
    return ". ".join(clauses[:2])
