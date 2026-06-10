"""Honesty grep guard (HON-01) — properties 7 (no-QA-vocab) + 8 (mode-blind render).

The QA vocabulary and the director-mode identifiers must NEVER reach a user-facing
surface. They live ONLY in receipts/debug (the offline origin marker, the director
receipt). This guard greps:

  * the pack's user-facing creative prose (``creative_prose_strings`` — receipts, debug
    source-refs, the deterministic RAG brain-query templates, the source plan and gate
    plumbing are deliberately EXCLUDED, exactly as HON-01 requires), and
  * the rendered ``index.html`` (dossier) + ``prototype/index.html`` with the evidence /
    debug-receipt / receipts ``<details>`` drawers stripped (``strip_debug_drawers``).

Property 7 (no-QA-vocab) is paired with the ``qa_vocab_pack`` negative control — the
guard MUST fail on a pack whose creative prose carries the QA register. Property 8
(mode-blind render) asserts no director-mode word (offline / deterministic / the director
class names) survives on the visible creative surface — the renderer cannot reveal which
director ran (ENG-06).

All packs are built keyless via ``FakeDirector`` (TST-04 — no live model).
"""

from __future__ import annotations

from london.cli import write_london_pack
from london.director import FakeDirector

from conftest import (
    BANNED_TEMPLATE_NAMES,
    BRIEFS,
    creative_prose_strings,
    strip_debug_drawers,
)

# The 6 banned QA phrases + the three "this is a test/no-model surface" tells the plan
# names (``fixture`` / ``offline`` / ``deterministic``). None may appear user-facing.
_BANNED_QA_PHRASES = (
    "fresh lane",
    "borrowed route",
    "prior profile",
    "recycled profile",
    "reusable template",
    "fixture",
    "offline",
    "deterministic",
)

# Director-mode identifiers — the words that would reveal WHICH director ran. These live
# only in the receipts stamp (offline-template-preview / the director class name) and must
# never leak onto the visible creative surface (property 8 / ENG-06).
_DIRECTOR_MODE_WORDS = (
    "offlinedirector",
    "claudecodedirector",
    "fakedirector",
    "offline-template-preview",
    "in_session",
    "claude_cli_print",
    "in-session model",
    "no-model",
)


def _write_model_pack(tmp_path, brief_key: str = "fragrance"):
    brief = tmp_path / "brief.md"
    brief.write_text(BRIEFS[brief_key], encoding="utf-8")
    out = tmp_path / "pack"
    pack = write_london_pack(brief, out, director=FakeDirector())
    dossier = (out / "index.html").read_text(encoding="utf-8")
    prototype = (out / "prototype" / "index.html").read_text(encoding="utf-8")
    return pack, dossier, prototype


def _prose_blob(pack: dict) -> str:
    return "\n".join(creative_prose_strings(pack)).lower()


# --- Property 7: no QA-vocab in user-facing pack prose ------------------------------


def test_pack_creative_prose_has_no_qa_vocabulary(tmp_path):
    pack, _, _ = _write_model_pack(tmp_path)
    blob = _prose_blob(pack)
    for phrase in _BANNED_QA_PHRASES:
        assert phrase not in blob, f"QA-vocab {phrase!r} leaked into user-facing pack prose"


def test_property_7_negative_control_qa_vocab_pack_is_rejected(qa_vocab_pack):
    # The guard MUST fail on a pack whose creative prose carries the QA register — this is
    # the negative control that proves property 7 has teeth (Pitfall 8). At least one of
    # the banned phrases must be detected by the SAME extraction the positive test uses.
    blob = "\n".join(creative_prose_strings(qa_vocab_pack)).lower()
    assert any(phrase in blob for phrase in _BANNED_QA_PHRASES), (
        "honesty guard failed to detect QA-vocab in the known-bad qa_vocab_pack"
    )


# --- Property 7 over rendered HTML (receipts/debug drawers excluded) -----------------


def test_rendered_html_has_no_qa_vocabulary_outside_receipts(tmp_path):
    _, dossier, prototype = _write_model_pack(tmp_path)
    for label, html in (("dossier", dossier), ("prototype", prototype)):
        visible = strip_debug_drawers(html).lower()
        for phrase in _BANNED_QA_PHRASES:
            assert phrase not in visible, f"QA-vocab {phrase!r} visible in rendered {label}"


def test_qa_vocab_survives_only_inside_excluded_debug_drawers(tmp_path):
    # Proof the EXCLUSION is real and not over-broad: the RAG brain-query templates legit-
    # imately carry "fresh lane proof" and they DO appear in the raw dossier — but ONLY
    # inside the evidence <details> drawers that strip_debug_drawers removes. If a future
    # change moved that text onto the visible surface, the test above would catch it.
    _, dossier, _ = _write_model_pack(tmp_path)
    raw = dossier.lower()
    visible = strip_debug_drawers(dossier).lower()
    assert "fresh lane" in raw, "expected the RAG brain-query template to appear in the raw dossier"
    assert "fresh lane" not in visible, "RAG brain-query text must be confined to the debug drawer"


# --- Property 8: mode-blind render --------------------------------------------------


def test_rendered_html_is_director_mode_blind(tmp_path):
    _, dossier, prototype = _write_model_pack(tmp_path)
    for label, html in (("dossier", dossier), ("prototype", prototype)):
        visible = strip_debug_drawers(html).lower()
        for word in _DIRECTOR_MODE_WORDS:
            assert word not in visible, f"director-mode word {word!r} leaked into rendered {label}"


def test_pack_creative_prose_is_director_mode_blind(tmp_path):
    pack, _, _ = _write_model_pack(tmp_path)
    blob = _prose_blob(pack)
    for word in _DIRECTOR_MODE_WORDS:
        assert word not in blob, f"director-mode word {word!r} leaked into pack prose"


# --- Cross-check: no memorized template name on the model creative surface ----------


def test_no_memorized_template_name_on_model_creative_surface(tmp_path):
    pack, dossier, prototype = _write_model_pack(tmp_path)
    prose = "\n".join(creative_prose_strings(pack))
    visible_dossier = strip_debug_drawers(dossier)
    visible_prototype = strip_debug_drawers(prototype)
    for banned in BANNED_TEMPLATE_NAMES:
        assert banned not in prose, f"memorized name {banned!r} in model pack prose"
        assert banned not in visible_dossier, f"memorized name {banned!r} visible in dossier"
        assert banned not in visible_prototype, f"memorized name {banned!r} visible in prototype"
