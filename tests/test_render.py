import inspect
import re
import london.render as render_mod
from html import unescape
from html.parser import HTMLParser
from html import escape
from urllib.parse import unquote

from london.assets import route_assets, slugify, visual_direction_board_data_uri
from london.cli import write_london_pack
from london.prototype import render_static_prototype, write_static_prototype
from london.render import (
    _conversation,
    _grader_section,
    _public_grader_copy,
    _public_handoff_text,
    escape as render_escape,
    escape_prose,
    render_dossier,
    write_dossier,
)
from london.persona import scrub_pack
from london.session import run_london_session
from london.workbench import enrich_workbench_pack


def sample_pack():
    pack = run_london_session(
        """# Kids Lunchbox

        Create a school lunchbox system for kids, parents, snack choices, stickers,
        backpack routines, and daily lunch reveal moments.
        """
    )
    enrich_workbench_pack(pack)
    return pack


def _strip_details(markup: str) -> str:
    return re.sub(r"<details\b.*?</details>", "", markup, flags=re.S)


def _visible_text(markup: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", markup)).strip()


class _RenderedCopyParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.details_depth = 0
        self.summary_depth = 0
        self.skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.skip_depth += 1
        if tag == "details":
            self.details_depth += 1
        if tag == "summary":
            self.summary_depth += 1
        user_facing = self.skip_depth == 0 and (self.details_depth == 0 or self.summary_depth > 0)
        if user_facing:
            for name, value in attrs:
                if value and name in {"alt", "aria-label", "title", "data-copy"}:
                    self.parts.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag == "summary" and self.summary_depth:
            self.summary_depth -= 1
        if tag == "details" and self.details_depth:
            self.details_depth -= 1
        if tag in {"script", "style"} and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.skip_depth == 0 and (self.details_depth == 0 or self.summary_depth > 0):
            self.parts.append(data)


def _rendered_user_copy(markup: str) -> str:
    parser = _RenderedCopyParser()
    parser.feed(markup)
    return re.sub(r"\s+", " ", unescape(" ".join(parser.parts))).strip()


class _DataCopyParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.values: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name == "data-copy" and value is not None:
                self.values.append(value)


def _data_copy_values(markup: str) -> list[str]:
    parser = _DataCopyParser()
    parser.feed(markup)
    return parser.values


def _default_visible_user_copy(markup: str) -> str:
    """Visible/interactive copy with folded technical bodies excluded.

    Details summaries still count because a closed drawer's label is public UI.
    """

    return _rendered_user_copy(markup)


def _count_word_for_test(count: int) -> str:
    return {
        0: "No",
        1: "One",
        2: "Two",
        3: "Three",
        4: "Four",
        5: "Five",
        6: "Six",
        7: "Seven",
        8: "Eight",
        9: "Nine",
        10: "Ten",
    }.get(count, str(count))


def test_workbench_renders_required_product_sections():
    html = render_dossier(sample_pack())

    # Land-book dossier shell (PACK-02) — replaces the old neo-brutalist poster surface.
    # DELIBERATELY UPDATED for TPL-01: the standalone "overview" section anchor is dropped
    # in the visual-first reorder (its facts relocate to the light overview band under the
    # command-center console). The 9 visual-first section anchors must all be present.
    assert '<main class="dossier-shell">' in html
    assert '<body data-persist-prefix="london-pack-' in html
    assert '"london-detail-" + persistPrefix + "-"' in html
    assert 'class="dossier-toolbar"' in html
    assert 'class="dossier-header' in html  # the light overview facts band (no longer a nav section)
    assert 'class="dossier-subnav"' in html
    assert 'class="command-center"' in html  # the dark console header at the top
    # The 9 visual-first section anchors must be present (no standalone "overview").
    for anchor in (
        "moodboard",
        "routes",
        "comparison",
        "font-lab",
        "conversation",
        "constraints",
        "evidence",
        "handoff",
        "receipts",
    ):
        assert f'id="{anchor}"' in html
    assert 'id="overview"' not in html  # the standalone overview anchor is gone (TPL-01)

    # DELIBERATELY UPDATED for RENDER-02: the conversation h2 is re-sourced from the
    # fixed-7 framing ("London Conversation" / "Seven-Gate Reasoning Trace") to the
    # variable-N "The conversation" (UI-SPEC §Copywriting). The conversation now renders
    # count = len(pack["conversation"]) cards, never a fixed seven-gate trace.
    assert "The conversation" in html
    assert "Seven-Gate" not in html
    assert "London Conversation" not in html
    assert "Route Decision Comparison" in html
    assert "Creative Moodboard Workbench" in html
    assert "Moodboard Canvas" in html
    assert "Font Lab" in html
    assert "Constraint Legend" in html
    assert "Evidence Drawer" in html
    assert "Copy / Handoff Console" in html
    assert "Run Records" in html


def test_dossier_shell_replaces_old_hero_and_pillcloud():
    # PACK-02 + TPL-02/D-07 (DELIBERATELY UPDATED): the Land-book .dossier-* shell is
    # present and the old neo-brutalist poster surface (black 82vh hero + pill-cloud nav)
    # is gone. The command-center remains as a light first-read workbench summary, not a
    # dark status console. The grader owns the dark engine-grade hero.
    html = render_dossier(sample_pack())

    for present in ('class="dossier-shell"', 'class="dossier-toolbar"', 'class="dossier-header', 'class="dossier-subnav"'):
        assert present in html, f"expected {present!r} in dossier output"

    assert 'class="command-center"' in html, "the command-center workbench summary must be present"
    assert "moodboard-canvas--dark" in html, "the moodboard dark canvas (first dark zone) must remain"
    # The sanctioned THIRD dark zone IS present (the grader engine-grade hero, RENDER-08).
    assert "grader-zone--dark" in html, "the grader hero (third dark zone) must be present (RENDER-08)"

    absent_markers = (
        "brief-snapshot",
        "min-height: 82vh",
        "background:#171717",
        "#171717",
        "jump-links",
        "font-weight: 900",
        "clamp(3.4rem",
        "workbench-shell",
        "workbench-nav",
        "workbench-dark",
    )
    for marker in absent_markers:
        assert marker not in html, f"old surface marker {marker!r} must be gone (PACK-02)"

    # RENDER-08 grader-zone ban (regex-SCOPED to the .grader-zone--dark CSS rule only —
    # a blanket `assert "#000" not in html` would FALSE-FAIL because the moodboard canvas
    # legitimately uses `background: #000` (render.py .moodboard-canvas--dark). The grader
    # hero must reuse #0E0E0E/#F4F4F2, never #000. This mirrors the class-rule scoping idiom
    # in test_no_wrapping_pill_cloud_regression (.subnav-row / .dossier-route-switcher).
    grader_rule = re.search(r"\.grader-zone--dark \{[^}]*\}", html)
    assert grader_rule is not None, "the grader hero must have a .grader-zone--dark CSS rule"
    grader_css = grader_rule.group(0)
    assert "#0E0E0E" in grader_css and "#F4F4F2" in grader_css, (
        "the grader dark zone must reuse the command-center dark literal (#0E0E0E/#F4F4F2)"
    )
    for banned in ("#000", "#171717", "82vh", "clamp(3.4rem", "font-weight: 900", "Impact"):
        assert banned not in grader_css, (
            f"old-hero marker {banned!r} must NOT appear inside the .grader-zone--dark rule (RENDER-08)"
        )


def _grader_block(*, telemetry_available, score, verdict="CLAIM_OK", claim_unverified=()):
    # A hand-built grader block read AS GIVEN (the grader.py grade() return shape):
    # composite / inspectors / audit / telemetry / headline / detail. NOT a real
    # capture — a synthetic fixture so the renderer is exercised across the n/a vs
    # captured-numeric branch + the claim-integrity branch without overfitting to the
    # 5 captured packs (RENDER-03/04 anti-flatten).
    captured = telemetry_available
    return {
        "composite": {
            "score": score,
            "telemetry_available": telemetry_available,
            "sub_scores": {"grounding": 0.0 if score == "n/a" else 0.27},
            "weights": {"grounding": 0.3},
            "method": "synthetic fixture",
        },
        "inspectors": [
            {
                "key": "source_auditor",
                "name": "Source Auditor",
                "dimension": "Every cited source verified against the real MCP transcript",
                "score": 0.0 if claim_unverified else 1.0,
                "verdict": verdict,
                "audit": {
                    "grounded_source_ids": [],
                    "claim_unverified": list(claim_unverified),
                    "verdict": verdict,
                },
            },
            {
                "key": "grounding_inspector",
                "name": "Grounding Inspector",
                "dimension": "Real brain-query depth (target ~ 4)",
                "score": "n/a" if not captured else 0.0,
                "verdict": "TELEMETRY_UNAVAILABLE" if not captured else "DEAD_ENGINE",
            },
        ],
        "audit": {
            "grounded_source_ids": [],
            "claim_unverified": list(claim_unverified),
            "verdict": verdict,
        },
        "telemetry": {
            "engine_mode": "offline",
            "captured": captured,
            "brain_query_count": 0,
            "brain_total_entries": 3439,
            "consulted_source_ids": [],
            "duration_ms": None,
            "brain_queries": [],
        },
        "headline": {
            "score": score,
            "label": "COMPOSITE",
            "sub_label": "weighted from 5 objective checks",
            "summary": (
                "Telemetry not captured for this engine mode — the engine grade is unavailable."
                if score == "n/a"
                else "A weak run: the engine barely ran or the routes/claims did not hold up."
            ),
            "inspectors": [],
        },
        "detail": {
            "composite_math": {"score": score, "sub_scores": {}, "weights": {}, "method": "synthetic"},
            "inspectors": [],
            "brain_queries": [],
            "consulted_source_ids": [],
            "engine_mode": "offline",
            "brain_total_entries": 3439,
        },
    }


def test_grader_section_honest_no_fake_gauges():
    # RENDER-03 / RENDER-04 (anti-flatten, no-fake-gauge): the grader section must
    # branch no-score states DISTINCTLY from a captured near-dead number,
    # must NEVER animate a gauge (no setInterval / Math.random), and must surface
    # CLAIM_UNVERIFIED in the --danger treatment WITHOUT ever hard-failing a legit run
    # (the flag renders, the render never raises). Fixtures are hand-built (T-05.1-07
    # is asserted by the no-fake-gauge check), NOT real captures — so the test proves
    # the renderer is not overfit to the 5 observed packs.

    # Branch 1: telemetry_available False means an honest no-score state.
    na_html = _grader_section({"grader": _grader_block(telemetry_available=False, score="n/a")})
    assert "grader-zone--dark" in na_html, "the grader hero (third dark zone) must render"
    assert "Open check" in na_html
    assert "The Workbench leaves this verdict open for this mode" in na_html
    assert "Not scored" not in na_html
    assert "weighted from 5 objective checks" not in na_html
    assert "No quality score captured" not in na_html
    assert "Telemetry not captured" not in na_html
    # No fake gauges anywhere in the grader markup (the Math.random() inversion).
    assert "setInterval" not in na_html and "Math.random" not in na_html, (
        "the grader markup must contain NO runtime gauge fake (static-from-Python only)"
    )

    # Branch 2: a captured near-dead numeric composite renders the REAL low number,
    # and it is DISTINCT text from the no-score state.
    num_html = _grader_section({"grader": _grader_block(telemetry_available=True, score=27.0)})
    assert "27" in num_html, "a captured near-dead numeric composite must render the real number"
    assert num_html != na_html, "the numeric branch must be visually distinct from the n/a branch"
    assert "No quality score captured" not in num_html
    assert "weighted from 5 objective checks" not in num_html
    assert "setInterval" not in num_html and "Math.random" not in num_html

    # Branch 3 — CLAIM_UNVERIFIED renders in the --danger / #B4232A treatment and the
    # render NEVER raises (a legit run is never hard-failed; the flag renders, never blocks).
    unverified_html = _grader_section(
        {
            "grader": _grader_block(
                telemetry_available=True,
                score=27.0,
                verdict="CLAIM_UNVERIFIED",
                claim_unverified=["source-zzz-unbacked"],
            )
        }
    )
    assert "Needs source check" in unverified_html, "the unverified verdict must render in public language"
    assert "CLAIM_UNVERIFIED" not in _rendered_user_copy(unverified_html)
    assert "grader-claim-verdict--danger" in unverified_html or "grader-column--danger" in unverified_html, (
        "CLAIM_UNVERIFIED must render in the --danger treatment (#B4232A via var(--danger))"
    )
    assert "source-zzz-unbacked" in unverified_html, (
        "the flagged unverified source must be surfaced (show-the-flag, never hidden)"
    )

    # Absent grader ⇒ honest 'no grade' state, never a crash and never a fabricated grade.
    empty_html = _grader_section({})
    assert empty_html is not None
    assert "id=\"grader\"" in empty_html, "an absent grader still registers the #grader anchor honestly"
    assert 'data-guidance-section="grader"' in empty_html
    assert 'data-guidance-kind="reader-guide"' in empty_html
    assert 'class="section-help"' in empty_html


def test_publicizer_preserves_london_authored_machine_words_in_prose():
    pack = sample_pack()
    sentence = "The design claims attention; proof lives in the interaction engine; status: ready for the ritual."
    pack["recommended_route"] = sentence
    pack["routes"][0]["rationale"] = sentence
    pack["routes"][0]["sections"][0]["body"] = sentence
    pack["route_comparison"][0]["risk"] = sentence

    html = render_dossier(pack)

    assert escape(sentence) in html

    # W1-P3 load-bearing assertion: the route rationale must reach the handoff section
    # verbatim (including "proof").  The OLD word-boundary publicizer replaced "proof" →
    # "evidence" in _public_handoff_text, so this assertion FAILS against the pre-W1-08
    # renderer (0b4f7d3^) while passing against the current exact-match renderer.
    handoff_parts = html.split('<section class="dossier-section" id="handoff"', 1)
    assert len(handoff_parts) == 2, "handoff section must be present in dossier HTML"
    # The handoff section ends at the NEXT dossier-section (there are nested sub-sections
    # before that boundary).  Isolate everything between the handoff marker and the next
    # top-level section open tag.
    handoff_and_tail = handoff_parts[1]
    next_section = handoff_and_tail.find('<section class="dossier-section"')
    handoff_section = handoff_and_tail if next_section < 0 else handoff_and_tail[:next_section]
    assert escape(sentence) in handoff_section, (
        "route rationale containing 'proof' must reach the handoff section verbatim; "
        "old word-boundary publicizer would have replaced 'proof' → 'evidence'"
    )


def test_grader_copy_uses_exact_machine_strings_only():
    machine = "Telemetry not captured for this engine mode — the engine grade is unavailable."
    prose = "The engine claims proof; status: the prototype can carry it."

    assert _public_grader_copy(machine) == "The Workbench leaves this verdict open for this mode."
    assert _public_grader_copy(prose) == prose


def test_scrub_pack_write_gate_preserves_public_prose_machine_words():
    sentence = "The design claims attention; proof lives in the interaction engine; status: ready for the ritual."
    pack = {
        "summary": sentence,
        "routes": [{"rationale": sentence, "sections": [{"body": sentence}]}],
    }

    scrub_pack(pack)

    assert pack["summary"] == sentence
    assert pack["routes"][0]["rationale"] == sentence
    assert pack["routes"][0]["sections"][0]["body"] == sentence

    # W1-P3 load-bearing assertion: the rationale that survived scrub_pack must also
    # survive _public_grader_copy — the grader dimension copy path.  The OLD regex-table
    # renderer had a `\bproof\b` → "support" rule in _public_grader_copy, so this
    # assertion FAILS against the pre-W1-08 renderer (0b4f7d3^) while passing against the
    # current exact-match renderer.
    grader_rendered = _public_grader_copy(pack["routes"][0]["rationale"])
    assert grader_rendered == sentence, (
        "_public_grader_copy must pass prose through verbatim; "
        "old regex-table renderer replaced 'proof' → 'support'"
    )


def test_scrub_pack_write_gate_preserves_machine_copy_block_layout():
    # W1-P4: the write gate must never reflow machine text. The old tidy passes ate the
    # leading ':' of ':root' and collapsed the two-space indent, shipping dead CSS in
    # every pack's clipboard payload — invisible to the W1-02 render test because that
    # test injects copy blocks AFTER scrub_pack. This test covers the scrub leg; the
    # W1-02 data-copy test covers the render leg; together they close the chain.
    css = ":root {\n  --london-spark: #ff6b35;\n  --london-ink: #1a1a1a;\n}"
    hint = "@import url('https://fonts.example/css2?family=Searefined');\nfont-family: 'Searefined', serif;"
    pack = {
        "copy_blocks": [
            {"kind": "css_variables", "label": "CSS variables", "text": css},
            {"kind": "import_hint", "label": "Font import", "text": hint},
        ]
    }

    scrub_pack(pack)

    assert pack["copy_blocks"][0]["text"] == css
    assert pack["copy_blocks"][0]["text"].startswith(":root {")
    assert "\n  --london-spark" in pack["copy_blocks"][0]["text"]
    assert pack["copy_blocks"][1]["text"] == hint


def test_scrub_pack_write_gate_changes_known_qa_scaffold_terms():
    pack = {
        "summary": "fresh lane",
        "routes": [
            {
                "title": "borrowed route",
                "rationale": "prior profile",
                "sections": [{"body": "reusable template"}],
            }
        ],
        "copy_blocks": [{"text": "fixture"}],
    }

    scrub_pack(pack)

    public_values = (
        pack["summary"],
        pack["routes"][0]["title"],
        pack["routes"][0]["rationale"],
        pack["routes"][0]["sections"][0]["body"],
        pack["copy_blocks"][0]["text"],
    )
    assert public_values != ("fresh lane", "borrowed route", "prior profile", "reusable template", "fixture")
    for value in public_values:
        assert value not in {"fresh lane", "borrowed route", "prior profile", "reusable template", "fixture"}


def test_grader_section_renders_variable_inspector_counts():
    # RENDER-05: the grader colophon must render the inspectors it is given, not a fixed
    # four-lane template. Use synthetic counts on both sides of the current fixture shape
    # so the renderer proves N-inspector support without copying a captured pack.
    for count in (2, 5):
        block = _grader_block(telemetry_available=True, score=64.0)
        block["inspectors"] = [
            {
                "key": f"inspector_{index}",
                "name": f"Inspector {index}",
                "dimension": f"Dimension {index}",
                "score": 0.2 + (index / 10),
                "verdict": "OBSERVED",
            }
            for index in range(1, count + 1)
        ]

        html = _grader_section({"grader": block})
        tracks = re.findall(r'<li class="inspector-track(?: [^"]*)?">', html)

        assert len(tracks) == count, f"expected {count} inspector tracks, got {len(tracks)}"
        for index in range(1, count + 1):
            assert f"Inspector {index}" in html
            assert f"Dimension {index}" in html


def test_grader_raw_audit_humanizes_machine_keys():
    block = _grader_block(telemetry_available=True, score=64.0)
    block["detail"]["route_pairs"] = 1
    block["detail"]["route_checks"] = [{"max_title_jaccard": 0.18}]

    html = _grader_section({"grader": block})

    assert "route_pairs" not in html
    assert "max_title_jaccard" not in html
    assert "route pairs" in html
    assert "max title jaccard" in html


def test_command_center_header_leads_with_london_read_not_run_metadata():
    # The command-center is the first-read workbench header. It must foreground London
    # creative direction (brief title, reframe, recommended route, optional recommendation
    # prose) while keeping run metadata available inside collapsed details.
    pack = sample_pack()
    html = render_dossier(pack)

    assert 'class="command-center"' in html

    console = re.search(r'<section class="command-center".*?</section>', html, flags=re.S)
    assert console is not None, "the command-center console section must render"
    console_html = console.group(0)
    first_read_html = _strip_details(console_html)
    first_read_text = _visible_text(first_read_html)
    run_details = re.search(r"<details\b.*?</details>", console_html, flags=re.S)
    assert run_details is not None, "run metadata must remain available in collapsed details"
    run_details_html = run_details.group(0)

    # 1) The public first read starts with London-derived creative copy.
    assert "London&#x27;s read" in first_read_html
    assert pack["title"] in first_read_text, "brief title (pack['title']) must lead the console"
    assert re.search(r"London would|Kid Choice Kit|Lunch Reveal Guide", first_read_text), (
        "the first-read header must show a public route read instead of prompt-shaped brief scaffolding"
    )
    assert not re.search(r"\b(?:make|turn)\s+[^.]*\b(?:prove this exact brief|product brief)\b", first_read_text, re.I)

    # 2) The recommended chip shows the RESOLVED route TITLE (resolved by recommended_route_ref
    #    id/title equality). If recommendation prose exists, it is preserved in full; the
    #    offline floor keeps honest absence instead of inventing a rationale.
    convo = pack["conversation"]
    total = len(convo)
    ref = pack["recommended_route_ref"]
    resolved = next(
        (r for r in pack["routes"] if r.get("id") == ref or r.get("title") == ref),
        None,
    )
    resolved_title = resolved["title"] if resolved else ref
    assert resolved_title in first_read_text, (
        "the first-read header must show the resolved recommended route title"
    )
    if pack["recommended_route"]:
        assert pack["recommended_route"] in first_read_text

    # 3) Operational metadata is translated into trust facts. Raw harness labels and
    #    values stay out of the user-facing command center.
    for label in ("MODE", "ARTIFACT", "GATES", "CONFIDENCE", "Run details"):
        assert label not in console_html, f"{label} must be translated out of the command center"
    assert "How to read this" in console_html
    assert "What to trust" not in console_html
    assert "What this gives you" not in console_html
    assert "London authored the direction." not in console_html
    assert f"London turned your brief into {_count_word_for_test(len(pack['routes'])).lower()} routes you can compare." in console_html
    assert f"Start with {resolved_title}, then use the alternates to pressure-test the direction." in console_html
    assert "The route visuals, type notes, and handoff are grouped so you can choose and build." in console_html
    assert "Open the audit note only when you need the source trail." in console_html
    assert "approved" not in console_html, "the status=='approved' GATES fossil must be gone"

    # 4) The readiness check is translated. The offline sample has no captured score,
    #    so the details read as a human audit note instead of an n/a stat.
    composite = (pack.get("grader") or {}).get("composite") or {}
    assert composite.get("telemetry_available") is False, (
        "fixture sanity: the offline sample pack does not capture telemetry"
    )
    assert "No readiness check captured." in _visible_text(run_details_html)
    assert "Quality score" not in _visible_text(run_details_html)
    assert "Engine score" not in _visible_text(run_details_html)
    assert "n/a" not in _visible_text(console_html).lower()

    # 5) NO fabricated gauge: no percent sign in the first-read console, no invented
    #    dial value, and crucially no old approved-ratio framing. Creative copy may
    #    legitimately contain numerals, so the guard targets the metadata phrase.
    assert "%" not in first_read_text, "the first-read console must not show a fabricated percentage gauge"
    assert f"{total} decisions" not in first_read_text

    # 6) The ⌘K trigger opens the shared command palette.
    assert "data-command-open" in console_html
    assert "⌘K" in console_html
    assert "Inspect moodboard" in first_read_text
    assert "Open route" in first_read_text

    # 7) Security (T-04-06): interpolated strings are HTML-escaped — no raw dict/angle-bracket
    #    leakage from pack-derived values into the console.
    assert "{'title'" not in console_html
    assert "{&#x27;title" not in console_html

    # 8) D-04 offline/fake floor: the MACHINE reference recommended_route_ref is populated
    #    (honest default = the lead route routes[0], never None-derived-on-the-fly); the
    #    verbatim recommendation PROSE recommended_route is "" (the floor never argues a case).
    assert pack["recommended_route_ref"], "recommended_route_ref must be populated on the offline path"
    assert pack["recommended_route_ref"] == pack["routes"][0]["title"], (
        "the offline honest floor for recommended_route_ref is the lead route title"
    )
    assert pack["recommended_route"] == "", "the offline floor never argues a case (prose '')"


def test_command_center_resolves_raw_model_route_ref_to_human_title():
    pack = sample_pack()
    picked = pack["routes"][1]
    raw_ref = f"route_{slugify(picked['title']).replace('-', '_')}"
    pack["recommended_route_ref"] = raw_ref

    html = render_dossier(pack)
    console = re.search(r'<section class="command-center".*?</section>', html, flags=re.S)
    assert console is not None
    console_html = console.group(0)

    assert picked["title"] in console_html
    assert raw_ref not in console_html


def test_recommendation_panel_preserves_long_short_and_absent_prose():
    # RENDER-01 / RENDER-06: London's recommendation is prose, not a nav title. The
    # renderer must preserve a long paragraph, treat a bare title-like value as short
    # prose, and render honest absence without inventing placeholder copy.
    from conftest import SYNTHETIC_RECOMMENDATION_BARE, SYNTHETIC_RECOMMENDATION_LONG

    def panel_for(pack):
        html = render_dossier(pack)
        match = re.search(r'<section class="recommendation-panel".*?</section>', html, flags=re.S)
        assert match is not None, "the recommendation panel must render"
        return match.group(0)

    long_pack = sample_pack()
    long_pack["recommended_route_ref"] = long_pack["routes"][1]["title"]
    long_pack["recommended_route"] = SYNTHETIC_RECOMMENDATION_LONG
    long_panel = panel_for(long_pack)
    assert "recommendation-fold" in long_panel
    assert 'data-persist="recommendation"' in long_panel
    assert escape(SYNTHETIC_RECOMMENDATION_LONG).strip() in long_panel
    assert "…" not in long_panel and "&hellip;" not in long_panel, (
        "long recommendation prose must not be silently truncated"
    )

    bare_pack = sample_pack()
    bare_pack["recommended_route_ref"] = bare_pack["routes"][0]["title"]
    bare_pack["recommended_route"] = SYNTHETIC_RECOMMENDATION_BARE
    bare_panel = panel_for(bare_pack)
    assert SYNTHETIC_RECOMMENDATION_BARE in bare_panel
    assert "recommendation-prose--short" in bare_panel
    assert "recommendation-fold" not in bare_panel

    empty_pack = sample_pack()
    empty_pack["recommended_route_ref"] = empty_pack["routes"][0]["title"]
    empty_pack["recommended_route"] = ""
    empty_panel = panel_for(empty_pack)
    assert empty_pack["routes"][0]["title"] in empty_panel
    assert "recommendation-prose" not in empty_panel
    assert "recommendation-fold" not in empty_panel
    for placeholder in ("No recommendation", "N/A", "None", "null", "undefined", "—"):
        assert placeholder not in empty_panel


def test_no_fossil_patterns_in_render_source():
    # RENDER-06 source-deletion gate: the two live flattening fossils must be DELETED at
    # source in src/london/render.py, not merely worked around. This test strips comment
    # lines (so a fossil mentioned in a "do-not-reintroduce" comment never trips it) and
    # asserts neither pattern survives in real code:
    #   (a) the status=='approved' gate-count ratio (floored every GATES stat to 0/N), and
    #   (b) the `title == recommendation` prose-to-title match (the chip-truncation bug).
    # It provably FAILS if either fossil is reintroduced into render.py.
    from pathlib import Path

    render_path = Path(__file__).resolve().parent.parent / "src" / "london" / "render.py"
    source_lines = [
        line for line in render_path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    ]
    source = "\n".join(source_lines)

    # (a) the status=='approved' gate-count fossil — both quote styles.
    assert 'status")) == "approved"' not in source, (
        "the double-quoted status=='approved' GATES fossil must be deleted from render.py"
    )
    assert "status')) == 'approved'" not in source, (
        "the single-quoted status=='approved' GATES fossil must be deleted from render.py"
    )

    # (b) the title-match recommendation fossil — resolve by recommended_route_ref instead.
    assert re.search(r'r\.get\(.title.\)\)\s*==\s*recommended', source) is None, (
        "the `display_text(r.get('title')) == recommended` fossil must be deleted from render.py"
    )


def test_command_center_run_details_artifact_stat_is_read_as_given():
    # The command-center translates pack["artifact_type"] into a human pack-type note,
    # while keeping the raw ARTIFACT stat out of the user-facing command center.
    pack = sample_pack()
    pack["artifact_type"] = "website"
    html = render_dossier(pack)

    console = re.search(r'<section class="command-center".*?</section>', html, flags=re.S)
    assert console is not None, "the command-center console section must render"
    console_html = console.group(0)
    first_read_text = _visible_text(_strip_details(console_html))
    details = re.search(r"<details\b.*?</details>", console_html, flags=re.S)
    assert details is not None
    details_html = details.group(0)

    assert "ARTIFACT" not in details_html, "the raw ARTIFACT label must be translated"
    assert "Source trail" in details_html
    assert "ARTIFACT" not in first_read_text
    # No fabricated gauge introduced: the value is a word, not a percentage or invented number.
    assert "%" not in _visible_text(console_html), "the ARTIFACT stat must not introduce a fabricated percentage"
    # Read-as-given proof: the honest generic default surfaces when no type is set.
    generic_pack = sample_pack()
    generic_console = re.search(
        r'<section class="command-center".*?</section>', render_dossier(generic_pack), flags=re.S
    ).group(0)
    generic_details = re.search(r"<details\b.*?</details>", generic_console, flags=re.S).group(0)
    assert "Source trail" in generic_details


def test_rendered_user_facing_copy_passes_iteration1_humanize_gate():
    html = render_dossier(sample_pack())
    user_copy = _rendered_user_copy(html)
    lowered = user_copy.lower()

    for dash in ("—", "&mdash;", "&#8212;", "&#x2014;", "--"):
        assert dash not in user_copy, f"rendered user-facing copy contains dash token {dash!r}"

    banned_tokens = (
        "scripted-local",
        "claude_cli_print",
        "offline-template-preview",
        "generated_live",
        "receipt-recorded",
        "request_config",
        "asset_sha256",
        "sha256",
        "manual_prompt",
        "manual-prompt",
        "fallback",
        "fixture",
        "fakedirector",
        "telemetry not captured",
        "n/a",
        "private brief context",
        "private london rationale",
        "allowed visible words",
        "create one text-free",
    )
    for token in banned_tokens:
        assert token not in lowered, f"untranslated harness token {token!r} leaked into rendered user copy"
    assert "london authored the direction" not in lowered
    assert "what to trust" not in lowered
    assert "how to read this" in lowered


def test_dossier_consumes_shared_navigation_model():
    # TPL-06 / NAV-01: the dossier consumes the SAME build_navigation model the prototype
    # does (surface="dossier"), so its nav surfaces carry the model-derived link ids and
    # route-id parity holds. The ad-hoc per-route _route_nav tabs are replaced by the shared
    # route switcher built from navigation.routes.
    from london.navigation import build_navigation
    from london.render import _route_id

    pack = sample_pack()
    html = render_dossier(pack)
    routes = pack["routes"]
    navigation = build_navigation(routes, routes[0], surface="dossier")

    # Route-id parity: each shared-model route id == render._route_id(route), and the dossier
    # carries that id in a model-derived route switcher tab + command-palette entry.
    for route in routes:
        rid = _route_id(route, "route")
        assert rid == route["id"]  # the pack already orders ids; parity is the seam
        assert f'data-nav-route-tab="{rid}"' in html, f"route switcher must carry shared-model route id {rid}"

    # The command palette is built from navigation.all_links — every primary-section link id
    # appears as a palette entry (data-nav-link), proving the dossier reads the shared model.
    for link in navigation.primary_sections:
        assert f'data-nav-link="{link.id}"' in html, f"palette/nav must carry shared-model link id {link.id}"

    # The old ad-hoc dossier route tab markup is gone (replaced by the shared switcher).
    assert 'class="route-tab"' not in html, "ad-hoc _route_nav route tabs must be replaced by the shared switcher"


def test_dossier_navigation_surfaces_and_a11y():
    # NAV-02 / NAV-03 / NAV-05: the dossier renders real, keyboard-operable, a11y-correct nav
    # surfaces — skip link, sticky bar, left rail, route switcher, ⌘K command palette — with
    # DISTINCT nav aria-labels and prefers-reduced-motion. Mirrors the prototype nav contract
    # (test_static_prototype_has_full_navigation_system_without_mobile_pill_cloud) against the
    # dossier renderer.
    html = render_dossier(sample_pack())

    # Skip link to the first content section (#moodboard, per the visual-first reorder).
    assert 'class="dossier-skip-link" href="#moodboard"' in html
    # Left rail + route switcher + command palette (ported from the prototype, renamed dossier-*).
    assert 'class="dossier-left-rail"' in html
    assert 'class="dossier-route-switcher" role="tablist"' in html
    assert 'role="tab" aria-selected="true"' in html
    assert 'data-command-palette role="dialog" aria-modal="true"' in html
    assert "data-command-search" in html
    # A11y: prefers-reduced-motion present; one scroll-spy observer; aria-current location.
    assert "prefers-reduced-motion" in html
    assert "IntersectionObserver" in html
    assert html.count("new IntersectionObserver") == 1, "exactly ONE IntersectionObserver (reconciled scroll-spy)"
    assert 'querySelectorAll("[data-nav-section][data-jump-target]")' in html
    assert "function visibleHashTarget()" in html
    assert "const hashTarget = visibleHashTarget();" in html
    assert "const scrollToHashTarget = () =>" in html
    assert "history.scrollRestoration = \"manual\"" in html
    assert "requestAnimationFrame(alignTarget)" in html
    assert "setTimeout(alignTarget, 260)" in html
    assert "setTimeout(alignTarget, 1800)" in html
    assert "setActiveSection(target.id || target.dataset.navSection, target.dataset.navRoute)" in html
    assert "window.addEventListener(\"hashchange\", scrollToHashTarget)" in html
    assert 'aria-current="location"' in html
    assert "<b>Quality Check</b>" in html
    assert "<b>Audit</b>" in html
    assert "<b>Grader</b>" not in html
    assert "<b>Receipts</b>" not in html

    # Distinct nav aria-labels: sticky bar / left rail / route switcher / mobile drawer — all different.
    nav_labels = re.findall(r'<nav[^>]*aria-label="([^"]+)"', html)
    assert len(nav_labels) >= 4, f"expected >= 4 nav regions, got {nav_labels!r}"
    assert len(set(nav_labels)) == len(nav_labels), f"every nav aria-label must be distinct, got {nav_labels!r}"


def test_no_wrapping_pill_cloud_regression():
    # NAV-04 (named deliverable): a mobile drawer is present and closes on Esc / outside-click /
    # link-select; the ⌘K + "/" keyboard handlers are wired. A wrapping pill-cloud must NEVER
    # return — the pill-cloud markers are absent.
    html = render_dossier(sample_pack())

    # Mobile drawer present with a toggle (aria-expanded) and a visible close affordance.
    assert 'class="dossier-mobile-drawer" id="dossier-mobile-drawer" data-mobile-drawer hidden' in html
    assert 'data-mobile-toggle aria-controls="dossier-mobile-drawer" aria-expanded="false"' in html

    # Esc / outside-click / select close behavior + ⌘K / "/" open, all in the inline JS.
    assert "event.metaKey || event.ctrlKey" in html
    assert 'event.key === "/"' in html
    assert 'event.key === "Escape"' in html
    assert "setDrawer(false)" in html  # link-select + Esc close the drawer
    assert "closePalette()" in html
    # Outside-click close on the palette overlay.
    assert "if (event.target === palette) closePalette()" in html

    # The wrapping pill-cloud must be GONE — none of these markers may appear.
    for marker in ("prototype-pill-cloud", "prototype-mobile-pill", "jump-links", "dossier-pill-cloud"):
        assert marker not in html, f"pill-cloud marker {marker!r} must be absent (NAV-04 regression)"
    # The ad-hoc .route-tabs wrapping row (the old pill-cloud-shaped route nav) is gone — the
    # shared route switcher replaces it.
    assert ".route-tabs {" not in html, "the old wrapping .route-tabs nav row must be gone"
    assert 'class="route-tab"' not in html, "old per-route pill tabs must be replaced by the shared switcher"
    # The sticky subnav row stays a single non-wrapping scroll row (no wrap into a cloud).
    subnav_rule = re.search(r"\.subnav-row \{[^}]*\}", html)
    assert subnav_rule is not None and "flex-wrap: nowrap" in subnav_rule.group(0)
    assert "flex-wrap: wrap" not in subnav_rule.group(0)
    # The dossier route switcher row does not wrap into a pill cloud.
    switcher_rule = re.search(r"\.dossier-route-switcher \{[^}]*\}", html)
    assert switcher_rule is not None, "the dossier route switcher must have a layout rule"
    assert "flex-wrap: wrap" not in switcher_rule.group(0), "the route switcher must not wrap into a pill cloud"


def test_visual_first_anchors_and_subnav():
    # TPL-01 (DELIBERATELY UPDATED from test_all_ten_anchors_and_subnav — it fails on
    # the visual-first reorder by design, which is the deliberate signal). The dossier
    # now renders the VISUAL-FIRST order (moodboard hero first, the conversation
    # timeline moved AFTER the visuals). The standalone "overview" anchor is dropped —
    # its facts relocated to the light overview band under the command-center console,
    # which is NOT a data-nav-section. The subnav is still a single non-wrapping row.
    # (Matchable by -k anchors.)
    #
    # DELIBERATELY UPDATED for RENDER-07: the NEW #grader section is registered between
    # evidence and handoff (UI-SPEC §Section Order row 8) across _SECTIONS,
    # render_dossier's _section_helpers, and navigation._DOSSIER_PRIMARY. So "grader"
    # joins ordered_anchors after "evidence", and the data-nav-section count rises 9 -> 10.
    html = render_dossier(sample_pack())

    ordered_anchors = [
        "moodboard",
        "routes",
        "comparison",
        "font-lab",
        "conversation",
        "constraints",
        "evidence",
        "grader",
        "handoff",
        "receipts",
    ]
    last_pos = -1
    for anchor in ordered_anchors:
        pos = html.find(f'id="{anchor}"')
        assert pos != -1, f"missing section anchor id={anchor!r}"
        assert pos > last_pos, f"anchor {anchor!r} out of order"
        last_pos = pos

    # The standalone overview anchor is gone (its facts moved under the console).
    assert 'id="overview"' not in html

    # Every section carries scroll-spy attributes. The count is 10: the 9 carried
    # visual-first sections + the NEW #grader section (RENDER-07). The standalone
    # overview anchor stays dropped and the command-center console header is NOT a
    # data-nav-section (it is the console, not a section).
    section_tags = re.findall(r"<section[^>]*>", html)
    nav_sections = [tag for tag in section_tags if "data-nav-section" in tag]
    assert len(nav_sections) == 10
    for tag in nav_sections:
        assert "data-nav-label=" in tag

    assert html.count("scroll-margin-top") >= 1  # in the .dossier-section CSS rule

    # The subnav is a single non-wrapping row — the subnav-row rule must not declare wrap.
    assert 'class="dossier-subnav"' in html
    subnav_rule = re.search(r"\.subnav-row \{[^}]*\}", html)
    assert subnav_rule is not None
    assert "flex-wrap: nowrap" in subnav_rule.group(0)
    assert "flex-wrap: wrap" not in subnav_rule.group(0)


def test_workbench_has_navigation_interaction_and_copy_controls():
    html = render_dossier(sample_pack())

    # New nav surface: sticky subnav + scroll-spy (PACK-03), not the pill-cloud workbench-nav.
    assert 'class="dossier-subnav"' in html
    assert "data-nav-section" in html
    assert "IntersectionObserver" in html
    # Preserved interaction + copy controls.
    assert 'data-route-button=' in html
    assert 'data-route-panel=' in html
    assert 'data-copy=' in html


def test_render_escape_is_pure_and_escape_prose_is_deliberate():
    value = ":root {\n  --london-serif: var(--serif);\n}\nassets/route--hero.png\nLondon — keeps the cut."

    assert unescape(render_escape(value)) == value
    assert unescape(escape_prose("London — keeps the cut.")) == "London: keeps the cut."


def test_handoff_copy_payloads_preserve_newlines_css_and_dash_tokens():
    pack = sample_pack()
    pack.setdefault("copy_blocks", []).append(
        {
            "kind": "css_variables",
            "text": ":root {\n  --font-stack: var(--serif);\n}\n.hero { background: url('assets/route--hero.png'); }",
        }
    )
    html = render_dossier(pack)
    data_copy_values = _data_copy_values(html)

    assert any("\n\nFirst build moment:" in value for value in data_copy_values)
    assert any(
        ":root {\n  --font-stack: var(--serif);" in value and "assets/route--hero.png" in value
        for value in data_copy_values
    )


_P4_TEST_PLACEHOLDER = True  # W1-P4 test added in next commit


def test_workbench_route_map_links_target_existing_surfaces_and_select_routes():
    html = render_dossier(sample_pack())

    ids = set(re.findall(r'\bid="([^"]+)"', html))
    hrefs = re.findall(r'href="#([^"]+)"', html)
    missing = [href for href in hrefs if href and href not in ids]
    assert missing == []
    assert 'data-nav-kind="route"' in html
    assert 'data-nav-kind="route-section"' in html
    assert "if (routeId && validRoutes.has(routeId)) selectRoute(routeId);" in html


def test_mobile_toolbar_keeps_escape_without_first_read_control_wall():
    html = render_dossier(sample_pack())
    style = html.split("<style>", 1)[1].split("</style>", 1)[0]
    mobile = style.split("@media (max-width: 980px)", 1)[1].split("@media (max-width: 640px)", 1)[0]

    assert 'data-mobile-close' in html
    assert 'document.querySelector("[data-mobile-close]")?.addEventListener("click", () => setDrawer(false));' in html
    assert 'data-toolbar-action="save"' not in html
    assert 'data-toolbar-action="copy"' not in html
    assert 'data-toolbar-action="download"' not in html
    assert 'data-toolbar-action="routes"' in html
    assert 'data-toolbar-action="handoff"' in html
    assert '.drawer-close' in mobile
    assert "navigator.clipboard.writeText" in html
    assert "localStorage" in html
    # The accessible lightbox MACHINERY is always present (role=dialog + close + the JS
    # that wires data-lightbox-src triggers). A live data-lightbox-src trigger only renders
    # for a real generated <img> (HON-03): the keyless parity oracle produces honest
    # prompt-card heroes instead of dressing a deterministic SVG as a generated image, so
    # the trigger markup is correctly absent here — the wiring still ships.
    assert "data-lightbox-src" in html  # referenced by the lightbox JS wiring
    assert 'role="dialog"' in html
    assert 'class="lightbox-close"' in html
    assert "beforeprint" in html
    narrow_mobile = style.split("@media (max-width: 640px)", 1)[1]
    assert ".dossier-subnav { display: none; }" in narrow_mobile


def test_curated_guidance_exec_summary_and_section_guides():
    import london.render as render_mod

    pack = sample_pack()
    pack["recommended_route"] = "Ship the kid-choice route because the product proof is visible before decoration."
    html = render_dossier(pack)

    assert 'class="guidance-exec"' in html
    assert 'data-guidance-kind="exec-summary"' in html
    assert 'data-guidance-source="exec_summary"' in html
    assert 'data-guidance-static="true"' in html
    assert "Route decision" in html
    assert "Executive read" not in html
    assert escape(pack["london_reframe"]) in html
    assert escape(pack["recommended_route"]) in html
    assert html.index('class="guidance-exec"') < html.index('class="dossier-header"')

    anchors = [anchor for anchor, _ in render_mod._SECTIONS]
    assert html.count('data-guidance-kind="reader-guide"') == len(anchors)
    assert html.count('data-guidance-source="static_reader_guide"') == len(anchors)
    assert html.count('data-guidance-static="true"') >= len(anchors) + 1
    for anchor in anchors:
        assert f'data-guidance-section="{anchor}"' in html, (
            f"canonical section {anchor!r} must carry a section guide"
        )


def test_first_read_navigation_avoids_repeated_dossier_eyebrows():
    html = render_dossier(sample_pack())
    assert "<span>Dossier</span>" not in html
    assert "<span>Route</span>" in html
    assert "<span>Section 01</span>" in html


def test_first_read_overview_uses_structured_brief_context():
    html = render_dossier(sample_pack())
    assert "London Osei Pack Reader" not in html
    assert 'class="brief-text"' not in html
    assert 'class="reframe"' not in html
    assert "Brief context" in html
    assert "What London is solving" in html
    assert "Assumption" in html
    assert "Void" in html
    assert "Not this" in html


def test_long_london_read_gets_scan_treatment():
    pack = sample_pack()
    pack["london_reframe"] = (
        "It is not an accessory. "
        "BLIP is a single-purpose ritual instrument: the physical opposite of an app. "
        "You twist a translucent dial once a day to log one honest thing. "
        "The reframe: replace doom-scroll behavior with a five-second turn of a knob. "
        "Hardware becomes a boundary against your phone, not another feed."
    )
    html = render_dossier(pack)

    assert 'class="command-center-read-lead"' in html
    assert 'class="command-center-read-list"' in html
    assert "It is not an accessory." in html
    assert "BLIP is a single-purpose ritual instrument" in html
    assert "Hardware becomes a boundary against your phone" in html


def test_curated_guidance_uses_authored_london_read_when_present():
    import london.render as render_mod

    pack = sample_pack()
    pack["curated_guidance"] = {
        "sections": {
            "routes": {
                "londons_read": "London-authored route read: ship the route whose proof survives first contact."
            }
        }
    }
    html = render_dossier(pack)
    anchors = [anchor for anchor, _ in render_mod._SECTIONS]

    assert "London-authored route read: ship the route whose proof survives first contact." in html
    assert html.count('data-guidance-kind="londons-read"') == 1
    assert html.count('data-guidance-source="londons_read"') == 1
    assert html.count('data-guidance-kind="reader-guide"') == len(anchors) - 1
    assert re.search(
        r'data-guidance-kind="londons-read"[^>]*data-guidance-section="routes"',
        html,
    )


def test_curated_exec_summary_does_not_fabricate_absent_recommendation_prose():
    pack = sample_pack()
    pack["recommended_route"] = ""
    html = render_dossier(pack)
    match = re.search(r'<section class="guidance-exec".*?</section>', html, flags=re.S)
    assert match is not None
    exec_html = match.group(0)

    assert "No route rationale recorded." in exec_html
    assert escape(pack["routes"][0]["rationale"]) not in exec_html


def test_curated_exec_summary_labels_missing_authored_read_as_static_guide():
    pack = sample_pack()
    pack.pop("london_reframe", None)
    pack.pop("summary", None)
    pack["recommended_route"] = ""
    html = render_dossier(pack)
    match = re.search(r'<section class="guidance-exec".*?</section>', html, flags=re.S)
    assert match is not None
    exec_html = match.group(0)

    assert 'data-guidance-kind="exec-guide"' in exec_html
    assert 'data-guidance-source="static_exec_guide"' in exec_html
    assert "Executive guide" in exec_html
    assert "Use this as the selected path after you have read London" in exec_html
    assert "No route rationale recorded." in exec_html
    assert "Create a school lunchbox system" not in exec_html
    assert escape(pack["routes"][0]["rationale"]) not in exec_html


def test_curated_guidance_survives_no_grader_branch():
    import london.render as render_mod

    pack = sample_pack()
    pack.pop("grader", None)
    html = render_dossier(pack)
    anchors = [anchor for anchor, _ in render_mod._SECTIONS]

    assert html.count('data-guidance-kind="reader-guide"') == len(anchors)
    assert html.count('class="section-help"') == len(anchors)
    assert 'data-guidance-section="grader"' in html


def test_curated_guidance_tooltips_and_template_registry_contract():
    import inspect
    import london.render as render_mod

    html = render_dossier(sample_pack())
    anchors = [anchor for anchor, _ in render_mod._SECTIONS]

    help_buttons = re.findall(r'<button class="section-help"[^>]*>ⓘ</button>', html)
    assert len(help_buttons) == len(anchors)
    for button in help_buttons:
        assert 'aria-label="' in button
        assert 'title="' in button
        assert 'data-tooltip-source="tooltip"' in button
        assert 'data-guidance-static="true"' in button

    assert html.count('data-section-intro-source="section_intro"') == len(anchors)

    source = inspect.getsource(render_mod)
    assert "from ..persona import VOICE_TEMPLATES" in source
    for template_id in ("section_intro", "tooltip", "exec_summary", "londons_read"):
        assert f"_template_source('{template_id}')" in source or f'_template_source("{template_id}")' in source


def test_curated_guidance_is_static_and_no_persistence_claim():
    html = render_dossier(sample_pack())
    guidance_markup = "\n".join(
        re.findall(r'<(?:section|aside)[^>]*data-guidance-[^>]*>.*?</(?:section|aside)>', html, flags=re.S)
    )

    assert guidance_markup
    assert "localStorage" not in guidance_markup
    assert "<script" not in guidance_markup
    for marker in (
        "live AI",
        "model call",
        "generating guidance",
        "Ask London",
        "London remembers",
        "saved to London",
    ):
        assert marker not in guidance_markup


def test_workbench_evidence_and_receipts_are_collapsible_without_fake_source_claims():
    html = render_dossier(sample_pack())
    lower = html.lower()

    assert "<details" in html
    assert "Why London believes this" in html
    assert "Brain findings by gate" not in html
    assert "London Brain Finding" in html
    assert "Source Targets" in html
    assert "Live route assets" in html
    assert "Open run records" in html
    assert "live-fetched" not in lower
    assert "live fetched" not in lower
    assert "source-" in html
    primary_labels = re.findall(r'<div class="primary-evidence-label">(.*?)</div>', html, flags=re.S)
    assert primary_labels
    assert all("source-" not in label for label in primary_labels)


def test_workbench_rejects_old_placeholder_surface():
    html = render_dossier(sample_pack()).lower()

    assert "safe-card" not in html
    assert "safe card" not in html
    assert "card-grid" not in html
    assert "preview preview" not in html
    assert "class=\"card" not in html
    assert "landbook-dossier" not in html
    # VALIDATION row 2-03-* line 47: the routes section is a real .route-dossier,
    # not a repeated safe-card grid.
    assert "route-dossier" in html


def test_conversation_card_has_no_fabricated_approval_badge():
    # DELIBERATELY REPLACES the old HGW-01 approval-badge test. RENDER-02b kills the
    # status-derived approval-badge ceremony on the conversation card: the old code
    # fabricated status="approved" (a fossil field no real run emits) and rendered an
    # "Approval" badge from it. Absence must render as absence — the rebuilt _conversation
    # never fabricates a status default and never paints an approval badge. The card now
    # shows the model's OWN gate label + decision, with optional fields (incl. status when
    # present) folded under "London's reasoning" only when non-empty.
    html = render_dossier(sample_pack())

    assert "approval-badge" not in html, (
        "the conversation card must not render a fabricated approval badge (RENDER-02b)"
    )
    assert "data-approval-status=" not in html, (
        "no fossil status attribute (no fabricated approved/redirected default)"
    )
    # The new card surface IS present: a .decision-card per decision, each with the
    # model's own gate label as the kicker and the decision as the body.
    assert 'class="decision-card"' in html, "the conversation must render .decision-card surfaces"


# --- The conversation: the two anti-flatten axes (RENDER-02 / RENDER-02b) -------------
#
# These tests call _conversation directly with crafted packs so the cardinality axis and
# the field-presence axis are exercised independently of the workbench enrichment path.
# The packs are HAND-BUILT, never loaded from .scratch/spike/captures/*.json — the real
# captures are UNIFORM (every entry = gate/decision/rationale/critique/answer; question
# and status never appear; zero sparse entries; N in {3, 7}). Reproducing those exact
# shapes would PROVE NOTHING about honest absence. We mirror the capture shape at N=3/7,
# push PAST the observed end to N=8, and synthesize sparse / question-only entries the
# captures never contain — that is the anti-overfit core (DO NOT OVERFIT, CLAUDE.md).


def _required_entry(i, **optional):
    # Every required conversationEntry field (schema:286-319 required array) + any optionals
    # passed in. id/order/evidence_classes/evidence_count are required by the SCHEMA even
    # though the 5 real captures omit them — building them here keeps the synthetic fixture
    # schema-valid while letting us vary the optional fields freely.
    entry = {
        "id": f"d{i}",
        "order": i,
        "gate": f"London-gate-{i}",
        "decision": f"London-decision-{i}",
        "evidence_classes": {"london_brain_findings": 0, "source_targets": 0, "live_artifacts": 0},
        "evidence_count": 0,
    }
    entry.update(optional)
    return entry


def test_conversation_cardinality_axis():
    # RENDER-02: the conversation renders EXACTLY len(conversation) cards, never padded,
    # never sliced, never index-mapped. Verified at N=3 (website.json's real shape), N=7
    # (generic.json / product.json), AND N=8 — a SYNTHETIC count past the observed end, to
    # prove the renderer is not hard-wired to the captured N range.
    #
    # Each entry mirrors the real-capture shape: gate + decision + rationale + critique +
    # answer (the uniform shape of all 5 captures), so the cards carry folds like a real run.
    for n in (3, 7, 8):
        entries = [
            _required_entry(
                i,
                rationale=f"rationale-{i}",
                critique=f"critique-{i}",
                answer=f"answer-{i}",
            )
            for i in range(1, n + 1)
        ]
        html = _conversation({"conversation": entries})

        # Cardinality: exactly N cards (count a stable per-card marker) — and every decision
        # is present (no padding/slicing). N=3 must produce 3, NOT a fixed 7.
        assert html.count('class="decision-card"') == n, (
            f"N={n}: expected exactly {n} decision cards, got {html.count('decision-card')}"
        )
        for i in range(1, n + 1):
            assert f"London-decision-{i}" in html, f"N={n}: decision {i} missing (padding/slicing?)"
            # The model's OWN gate label appears verbatim — not a fixed GATE_NAMES set.
            assert f"London-gate-{i}" in html, f"N={n}: model gate label {i} missing"

        # No template-bank text: the rebuilt renderer never emits a canned gate question or
        # critique label; the old fixed-7 framing is gone.
        assert "Seven-Gate" not in html
        assert "London Conversation" not in html
        # No fabricated approval ceremony.
        assert "approval-badge" not in html


def test_conversation_field_presence_axis():
    # RENDER-02b: optional fields render as honest absence. A SYNTHETIC, hand-built fixture
    # (NOT a real capture — the captures have zero sparse entries) with three entries:
    #   (a) DENSE   = required + ALL five optionals (rationale/critique/answer/question/status)
    #   (b) SPARSE  = required + ZERO optionals
    #   (c) Q-ONLY  = required + `question` only (a field no real capture carries)
    # This fixture would FAIL if the renderer placeholder-filled an absent optional.
    dense = _required_entry(
        1,
        rationale="DENSE-rationale",
        critique="DENSE-critique",
        answer="DENSE-answer",
        question="DENSE-question",
        status="DENSE-status",
    )
    sparse = _required_entry(2)
    question_only = _required_entry(3, question="QONLY-question")

    html = _conversation({"conversation": [dense, sparse, question_only]})

    # Exactly three cards.
    assert html.count('class="decision-card"') == 3

    # (a) DENSE: London reasoning fields are visible first-read; run status moves into
    # collapsed provenance details.
    for value in (
        "DENSE-rationale",
        "DENSE-critique",
        "DENSE-answer",
        "DENSE-question",
    ):
        assert value in html, f"dense card must surface optional {value!r}"
    dense_card = re.search(r'<article class="decision-card".*?</article>', html, flags=re.S).group(0)
    dense_first_read = _strip_details(dense_card)
    assert "DENSE-status" not in dense_first_read, "status is run/audit state, not first-read reasoning"
    assert "DENSE-status" in dense_card
    assert 'data-persist="decision-0"' in html, "dense card folds under a persisted <details>"

    # (b) SPARSE: required fields still render (gate + decision), but NO optional region,
    # NO empty container, NO placeholder, and NO <details> disclosure at all.
    assert "London-gate-2" in html and "London-decision-2" in html
    # The sparse card (index 1) must not produce a fold.
    assert 'data-persist="decision-1"' not in html, "sparse card must render NO <details> (honest absence)"
    for placeholder in ("N/A", "None", "null", "undefined", "—"):
        assert placeholder not in html, f"absent optionals must not leak a {placeholder!r} placeholder"

    # The total number of folds equals the number of cards with provenance/run details:
    # dense has status, while sparse and question-only have visible public reasoning only.
    assert html.count("<details") == 1, (
        f"only the dense status card folds; sparse/question-only render no proof drawer — got {html.count('<details')}"
    )

    # (c) QUESTION-ONLY: `question` surfaces in the first-read reasoning; the other
    # optionals are absent (not faked), and it does not open an empty proof drawer.
    assert "QONLY-question" in html, "question-only card must surface its question"
    assert 'data-persist="decision-2"' not in html, "question-only card must not fold without provenance"


def test_conversation_first_read_is_reasoning_with_collapsed_provenance():
    entry = _required_entry(
        1,
        answer="London answer: choose the tactile route.",
        rationale="London rationale: the ritual gives parents and kids a shared decision.",
        critique="London push: avoid generic lunchbox cheer.",
        status="approved",
        brain_queries=[{"intent": "ritual evidence", "query": "kids lunchbox ritual decision"}],
        brain_findings=[
            {
                "id": "brain-1",
                "title": "Rituals make repeated product moments easier to remember.",
                "evidence_class": "London Brain Finding / Principle",
                "why_london_used_this": "Supports the daily check ritual.",
            }
        ],
        sources=[
            {
                "source_id": "fonts-in-use",
                "title": "Fonts In Use",
                "status": "planned-reference",
                "evidence_class": "Source Target",
                "why_london_used_this": "Type proof target.",
            }
        ],
        receipts=[{"receipt_id": "receipt-1", "kind": "brain-query", "provider": "local-sqlite"}],
        evidence_classes={"london_brain_findings": 1, "source_targets": 1, "live_artifacts": 0},
        evidence_count=2,
    )

    html = _conversation({"conversation": [entry]})
    card = re.search(r'<article class="decision-card".*?</article>', html, flags=re.S)
    assert card is not None
    card_html = card.group(0)
    first_read = _visible_text(_strip_details(card_html))
    details = re.search(r"<details\b.*?</details>", card_html, flags=re.S)
    assert details is not None
    details_text = _visible_text(details.group(0))

    for value in (
        "London-gate-1",
        "London-decision-1",
        "London answer: choose the tactile route.",
        "London rationale: the ritual gives parents and kids a shared decision.",
        "London push: avoid generic lunchbox cheer.",
    ):
        assert value in first_read
    for blocked in (
        "provider",
        "receipt",
        "telemetry",
        "engine_mode",
        "captured",
        "MODE",
        "GATES",
        "CONFIDENCE",
        "approved",
    ):
        assert blocked.lower() not in first_read.lower()
    assert re.search(r"\bsha(?:256)?\b", first_read, flags=re.I) is None

    assert "Decision source trail" in details_text
    assert "brain-query" in details_text
    assert "receipt-1" in details_text
    assert "London Brain Finding" in details_text
    assert "Source Target" in details_text


def test_human_guided_next_step_selectors_are_copyable_local_view_only():
    # HGW-01 (Task 1): next-step selectors render with copyable handoff text per step
    # AND the "Local view only — not saved, not sent to London" honesty label per step.
    # No fake in-page approval backend; the affordance is honest local UI (D-02/D-03).
    pack = sample_pack()
    html = render_dossier(pack)

    # The next-step dock renders each next_step as a selector with its own copy control.
    selectors = re.findall(r'<li class="next-step-selector".*?</li>', html, flags=re.S)
    assert selectors, "next_steps must render as copyable next-step selectors (HGW-01)"
    assert len(selectors) >= len(pack.get("next_steps", [])) or selectors

    for selector in selectors:
        # Copyable handoff text per step (D-03): a data-copy control carrying the handoff.
        assert "data-copy=" in selector, "each next-step selector must carry copyable handoff text"
        # The per-step honesty label (color/markup is never the sole signal of non-persistence).
        assert "Local view only" in selector, (
            "each next-step selector must carry the Local-view-only honesty label"
        )

    # No fake approval backend / "London remembers" illusion: the only localStorage use is
    # the view-ergonomics persistence in the script (D-13), never a creative-decision store.
    assert "London remembers" not in html


def test_no_local_paths_in_full_out_tree(tmp_path):
    # HON-02 (Task 3, VALIDATION row 2-04-* line 51, threat T-02-08): build a real pack and
    # grep the ENTIRE OUT tree — index.html + london-pack.json + receipts.json + DESIGN.md +
    # BUILD-HANDOFF.md + visual-routes.json — and assert NONE embeds a local absolute path
    # prefix (/Users/, /tmp/, /private/). This is the FULL-TREE regression, not a partial
    # grep: the schema not-pattern guards only brief.source_label, so the renderer/receipts
    # are the real surface. The keyless OfflineDirector parity oracle runs via the conftest
    # autouse fixture (no flag, no prompt).
    brief = tmp_path / "brief.md"
    brief.write_text(
        "# Luxury Fragrance Compact\n\nBuild a refillable scent ritual with atelier packaging.",
        encoding="utf-8",
    )
    out = tmp_path / "pack"

    write_london_pack(brief, out)

    artifacts = (
        "index.html",
        "london-pack.json",
        "receipts.json",
        "DESIGN.md",
        "BUILD-HANDOFF.md",
        "visual-routes.json",
    )
    # NB: tmp_path itself lives under /private/var/... on macOS, so we grep the FILE
    # CONTENTS — an artifact must never EMBED its own absolute output path or any local path.
    for name in artifacts:
        path = out / name
        assert path.exists(), f"expected artifact {name!r} in the OUT tree"
        contents = path.read_text(encoding="utf-8")
        for prefix in ("/Users/", "/tmp/", "/private/"):
            assert prefix not in contents, f"{name} leaks a local path prefix {prefix!r}"
        # The output dir's own absolute path must never be embedded.
        assert str(out) not in contents, f"{name} embeds its own absolute output path"
        assert str(brief) not in contents, f"{name} embeds the brief's absolute path"

    # Any brain-DB reference renders as the bundled label / local-sqlite provider — NEVER the
    # real DB path (library.py DEFAULT_BRAIN_DB). The dossier carries provider:"local-sqlite"
    # today; assert the honest label and that the raw sqlite path never surfaces.
    receipts_blob = (out / "receipts.json").read_text(encoding="utf-8")
    pack_blob = (out / "london-pack.json").read_text(encoding="utf-8")
    combined = receipts_blob + pack_blob
    assert "local-sqlite" in combined or "bundled:london_brain.sqlite" in combined, (
        "the brain DB must surface as local-sqlite / bundled:london_brain.sqlite"
    )
    # The raw bundled DB filename must never appear as part of an absolute path.
    for blob in (receipts_blob, pack_blob, (out / "index.html").read_text(encoding="utf-8")):
        if "london_brain.sqlite" in blob:
            idx = blob.find("london_brain.sqlite")
            preceding = blob[max(0, idx - 12):idx]
            assert "bundled:" in preceding, (
                "any london_brain.sqlite reference must carry the bundled: label, never a path"
            )


def test_human_guided_local_view_labels(tmp_path):
    # HGW-01 (Task 3, VALIDATION row 2-04-* line 50): the rendered dossier carries the
    # "Local view only" / "not saved, not sent to London" honesty copy on the human-guided
    # next-step affordances. Built through the full write path so the regression covers the
    # shipped index.html, not just the in-memory renderer.
    # DELIBERATELY UPDATED for RENDER-02b: the per-gate approval-badge assertions are
    # removed — the conversation card no longer fabricates a status="approved" default or
    # paints an approval badge (that fossil ceremony is deleted at source). The Local-view
    # honesty copy lives on the next-step selectors (a different surface), which is unchanged.
    brief = tmp_path / "brief.md"
    brief.write_text(
        "# Kids Lunchbox\n\nCreate a school lunchbox system for kids, parents, snack choices, stickers.",
        encoding="utf-8",
    )
    out = tmp_path / "pack"

    write_london_pack(brief, out)
    html = (out / "index.html").read_text(encoding="utf-8")

    # The Local-view-only honesty copy is present on the human-guided affordances.
    assert "Local view only" in html
    assert "not saved, not sent to London" in html


def test_route_dossier_is_not_safe_card_grid():
    # PACK-04 (VALIDATION line 47): each route is a real two-column .route-dossier
    # (preview-column + meta-rail) with a per-route accent injected from its palette;
    # no two routes carry the same accent, and no safe-card / card-grid markup appears.
    html = render_dossier(sample_pack())

    # The route-dossier two-column structure is present.
    assert 'class="route-dossier"' in html
    assert html.count('class="dossier-preview-column"') >= 2
    assert html.count('class="dossier-meta-rail"') >= 2

    # Required meta-rail parts (Steal this principle / Do not copy / brain rationale).
    assert "Steal this principle" in html
    assert "Do not copy" in html

    # Per-route accent injection: two distinct accents from two distinct palettes.
    accents = re.findall(r'class="route-dossier"[^>]*style="--accent:([^";]+)', html)
    assert len(accents) >= 2, f"expected an --accent on each route-dossier, found {accents!r}"
    assert len(set(accents)) >= 2, f"two routes must read with different accents, got {accents!r}"

    # Negative control: the routes path must NOT use the old generic safe-card grid.
    lower = html.lower()
    assert "safe-card" not in lower
    assert "card-grid" not in lower


def test_font_lab_three_tiers_per_route_with_distinct_portable_specimens():
    # PACK-04/Font Lab Contract: each route renders 3 tiers; Route 1 vs Route 2
    # specimen stacks differ (Fix-7). Open-public specimens now resolve through a
    # source-loaded public font lane instead of collapsing to identical system fallback text.
    pack = sample_pack()
    html = render_dossier(pack)

    groups = pack["font_options"]
    assert len(groups) >= 2
    for group in groups:
        assert len(group["options"]) == 3, "each route must render exactly 3 font tiers"

    # Route 1 vs Route 2 safe-local specimen stacks differ.
    stack_r1 = groups[0]["options"][0]["fallback_stack"]
    stack_r2 = groups[1]["options"][0]["fallback_stack"]
    assert stack_r1 != stack_r2, "Route 1 and Route 2 font specimens must differ (Fix-7)"

    # Source-loaded Font Lab emits controlled @font-face rules instead of naked import hints.
    assert "font-family:" in html
    assert "<link" not in html
    assert "class=\"font-specimen\"" in html
    assert 'class="font-specimen-role">Headline' in html
    assert 'class="font-specimen-role">Body' in html
    assert 'class="font-specimen-role">Label' in html
    assert 'data-font-preview-status="source_loaded"' in html
    assert 'data-font-preview-status="reference_only"' in html
    assert "London recommends" in html
    assert "Rendered preview" not in html
    assert "https://cdn.jsdelivr.net/fontsource/fonts/nunito@latest/latin-500-normal.woff2" in html
    assert "https://cdn.jsdelivr.net/fontsource/fonts/nunito-sans@latest/latin-500-normal.woff2" in html


def test_font_lab_specimen_containers_have_real_breathing_room():
    # UI rhythm: Tom's Transparent Machine type-lab review caught specimens hugging the
    # card edge. The middle spacing token must resolve, and the specimen board owns a
    # generous inset instead of relying on accidental browser defaults.
    from london.render import _style

    style = _style()

    assert "--sp-5: 20px" in style, "the spacing scale must include the middle rhythm token"

    board_rule = re.search(r"\.font-specimen-board\s*\{(?P<body>[^}]*)\}", style)
    assert board_rule
    board_body = board_rule.group("body")
    assert "padding: var(--sp-8)" in board_body
    assert "min-height: 440px" in board_body
    assert "overflow: visible" in board_body

    specimen_rule = re.search(r"\n\s+\.font-specimen\s*\{(?P<body>[^}]*)\}", style)
    assert specimen_rule
    specimen_body = specimen_rule.group("body")
    assert "max-width: 100%" in specimen_body
    assert "font-size: 44px" in specimen_body
    assert "line-height: 1.06" in specimen_body
    assert "word-break: normal" in specimen_body
    assert "overflow: hidden" not in specimen_body

    mobile = re.search(r"@media \(max-width: 980px\)\s*\{(?P<body>.*?)\n\s*\}\n", style, re.DOTALL)
    assert mobile
    mobile_body = mobile.group("body")
    assert re.search(r"\.font-specimen-board\s*\{[^}]*min-height:\s*auto", mobile_body)
    assert re.search(r"\.font-specimen-board\s*\{[^}]*padding:\s*var\(--sp-5\)", mobile_body)
    assert re.search(r"\.font-specimen\s*\{[^}]*font-size:\s*36px", mobile_body)


def test_font_lab_import_hint_is_copy_text_not_live_css():
    pack = sample_pack()
    pack["font_options"][0]["options"][1]["import_hint"] = '@import url("https://fonts.example/public.css");'

    html = render_dossier(pack)
    style = html.split("<style>", 1)[1].split("</style>", 1)[0]

    assert "@import" not in style
    assert 'data-copy="@import url(' in html
    assert 'data-font-preview-status="source_loaded"' in html


def test_font_lab_local_asset_metadata_emits_safe_font_face_and_loaded_label():
    pack = sample_pack()
    pack["font_options"][0]["options"][1]["font_preview"] = {
        "status": "actual_loaded",
        "delivery": "local_asset",
        "rendered_family": "Kiddo Local",
        "source_label": "Bundled test font",
        "license_note": "Local test asset supplied with this pack.",
        "asset_href": "assets/fonts/kiddo-local.woff2",
    }

    html = render_dossier(pack)
    style = html.split("<style>", 1)[1].split("</style>", 1)[0]

    assert "@font-face" in style
    assert 'font-family: "Kiddo Local";' in style
    assert 'url("assets/fonts/kiddo-local.woff2")' in style
    assert "Actual font loaded" not in html
    assert 'data-font-preview-status="actual_loaded"' in html
    assert "document.fonts.ready" in html
    assert 'const target = node.querySelector(".font-specimen, .route-specimen") || node;' in html
    assert 'const expected = target.dataset.fontPreviewFamily || node.dataset.fontPreviewFamily || "";' in html
    assert 'window.getComputedStyle(target).fontFamily' in html
    assert 'const loadedClaim = status === "actual_loaded" || status === "source_loaded";' in html

    actual_option = re.search(
        r'<article class="font-option font-option--actual_loaded"[^>]*data-font-preview-family="Kiddo Local"[\s\S]*?<p class="font-specimen" style="font-family:&quot;Kiddo Local&quot;,[^"]+" data-font-preview-family="Kiddo Local">',
        html,
    )
    assert actual_option, "actual-loaded Font Lab cards must style the child .font-specimen the helper reads"


def test_static_prototype_rebases_actual_loaded_font_asset_href():
    pack = sample_pack()
    pack["font_options"][0]["options"][1]["font_preview"] = {
        "status": "actual_loaded",
        "delivery": "local_asset",
        "rendered_family": "Kiddo Local",
        "source_label": "Bundled test font",
        "license_note": "Local test asset supplied with this pack.",
        "asset_href": "assets/fonts/kiddo-local.woff2",
    }

    html = render_static_prototype(pack)
    style = html.split("<style>", 1)[1].split("</style>", 1)[0]

    assert "@font-face" in style
    assert 'font-family: "Kiddo Local";' in style
    assert 'url("../assets/fonts/kiddo-local.woff2")' in style
    assert 'url("assets/fonts/kiddo-local.woff2")' not in style
    assert "Actual font loaded" not in html


def test_font_lab_premium_reference_only_does_not_claim_actual_loaded():
    html = render_dossier(sample_pack())

    assert 'data-font-preview-status="reference_only"' in html
    assert "Source/license required" in html or "licensed local asset is supplied" in html
    assert "Reference only: needs an official specimen capture" in html
    assert "font-option--premium_inspiration font-option--actual_loaded" not in html


def test_font_lab_reference_visual_card_does_not_emit_live_font_css():
    pack = sample_pack()
    pack["font_options"][0]["options"][2]["font_preview"] = {
        "status": "reference_only",
        "delivery": "reference_only",
        "rendered_family": "GT America",
        "source_label": "Grilli Type public specimen",
        "license_note": "reference_visual: visual reference, font not loaded.",
        "reference_visual": True,
        "reference_preview": {
            "kind": "official_preview_url",
            "url": "https://www.grillitype.com/typeface/gt-america",
            "source_label": "Grilli Type public specimen",
            "buy_or_license_url": "https://www.grillitype.com/typeface/gt-america",
            "license_or_terms_note": "Visual reference, font not loaded.",
            "alt": "Official GT America specimen page from Grilli Type",
        },
    }

    html = render_dossier(pack)
    style = html.split("<style>", 1)[1].split("</style>", 1)[0]

    assert "reference_visual" in html
    assert 'data-font-reference="reference_capture"' in html
    assert "Visual reference, font not loaded." in html
    assert "Open specimen" in html
    assert "Actual font loaded" not in html
    assert "GT America" not in style


def test_font_lab_reference_capture_renders_specimen_image_not_fake_font():
    pack = sample_pack()
    specimen = (
        "data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 800 420%22%3E"
        "%3Crect width=%22800%22 height=%22420%22 fill=%22%23f7f3eb%22/%3E"
        "%3Ctext x=%2248%22 y=%22160%22 font-size=%2272%22 font-family=%22serif%22%3EMaison Neue%3C/text%3E"
        "%3Ctext x=%2252%22 y=%22230%22 font-size=%2226%22 font-family=%22sans-serif%22%3EOfficial specimen capture fixture%3C/text%3E"
        "%3C/svg%3E"
    )
    pack["font_options"][0]["options"][2]["font_preview"] = {
        "status": "reference_capture",
        "delivery": "reference_image",
        "rendered_family": "Maison Neue",
        "source_label": "Milieu Grotesque public specimen",
        "license_note": "Commercial visual reference, font not loaded.",
        "reference_preview": {
            "kind": "official_specimen_capture",
            "url": "https://www.milieugrotesque.com/typeface/maison-neue/",
            "specimen_image_src": specimen,
            "source_label": "Milieu Grotesque public specimen",
            "buy_or_license_url": "https://www.milieugrotesque.com/typeface/maison-neue/",
            "license_or_terms_note": "Commercial visual reference, font not loaded.",
            "alt": "Official Maison Neue specimen capture",
        },
    }

    html = render_dossier(pack)
    style = html.split("<style>", 1)[1].split("</style>", 1)[0]

    assert 'data-font-preview-status="reference_capture"' in html
    assert 'data-font-reference="reference_capture"' in html
    assert 'src="data:image/svg+xml' in html
    assert "Maison Neue" not in style


def test_font_lab_first_layer_is_visual_not_proof_status_copy():
    html = render_dossier(sample_pack())
    font_lab = html.split('<section class="dossier-section" id="font-lab"', 1)[1].split(
        '<section class="dossier-section" id="conversation"', 1
    )[0]
    first_layer = _strip_details(font_lab)
    visible_text = _visible_text(first_layer).lower()

    assert "nunito" in visible_text
    assert "london recommends" in visible_text
    assert "headline" in visible_text
    assert "body" in visible_text
    assert "label" in visible_text
    for marker in (
        "actual font loaded",
        "rendered preview",
        "fallback approximation",
        "reference_visual",
        "receipt",
        "asset_sha256",
        "launch-gate",
        "provider",
        "sha-256",
    ):
        assert marker not in visible_text


def test_font_lab_uses_route_title_as_large_specimen_not_prompt_headline():
    pack = _offline_keyless_pack()
    first_group = pack["font_options"][0]
    first_option = first_group["options"][0]

    assert first_option["sample_headline"] == first_group["route_title"]
    assert "brief" not in first_option["sample_headline"].lower()

    html = render_dossier(pack)
    font_lab = html.split('<section class="dossier-section" id="font-lab"', 1)[1].split(
        '<section class="dossier-section" id="conversation"', 1
    )[0]
    first_layer = _strip_details(font_lab)
    visible_text = _visible_text(first_layer).lower()

    assert first_option["sample_headline"].lower() in visible_text
    assert "turn joyful retro futurist product brief" not in visible_text
    assert "answer the first real decision" not in visible_text


def test_visual_direction_board_keeps_prompt_transcripts_out_of_art():
    long_prompt = (
        "Full prompt transcript with camera notes, receipt hints, provider context, "
        "brain excerpts, source cues, and exact implementation directions. "
    ) * 6
    uri = visual_direction_board_data_uri(
        "Signal object",
        long_prompt,
        [{"role": "signal", "name": "Signal", "hex": "#ff4f1f"}],
        type_note="Heavy slab grotesque headlines; plainspoken grotesque body; tabular mono labels.",
        brain_cues=[
            "Brain cue one with enough detail to prove clipping and prevent overlap in the board surface.",
            "Brain cue two with another long source-like title that should be budgeted.",
            "Brain cue three",
        ],
        source_cues=[
            "Source cue one should be clipped instead of becoming a transcript dump.",
            "Source cue two",
            "Source cue three should not render because the board allows five cues total.",
        ],
    )
    svg = unquote(uri.split(",", 1)[1])

    assert "visual direction board" in svg.lower()
    assert "ROUTE THESIS" in svg
    assert "EVIDENCE CUES" in svg
    assert "ROUTE PROMPT" not in svg
    assert long_prompt not in svg
    assert "provider context, brain excerpts, source cues, and exact implementation directions" not in svg
    assert svg.count("<tspan font-weight=\"700\">") == 5


def test_dossier_type_and_font_proof_are_layered_not_display_receipts():
    pack = sample_pack()
    long_type = (
        "Heavy slab grotesque headlines should hold the masthead and product claim. "
        "Plainspoken grotesque body copy should make the build instructions readable. "
        "Tabular mono labels should handle weather, date, price, and proof metadata."
    )
    pack["routes"][0]["type"] = long_type
    pack["font_options"][0]["options"][1]["font_preview"] = {
        "status": "actual_loaded",
        "delivery": "local_asset",
        "rendered_family": "Familjen Grotesk",
        "source_label": "Fontshare (SIL Open Font License 1.1)",
        "license_note": (
            "Bundled London Type Shelf asset; license checked 2026-06-05; "
            "SHA-256: 5589983a201d1b0b77b55f8c299a4753cff515e86536c4761446a4dd6705a80b."
        ),
        "asset_href": "assets/fonts/familjen-grotesk-500.woff2",
    }

    html = render_dossier(pack)
    type_block = re.search(r'<div class="type-specimen">.*?<div class="dossier-meta-rail">', html, flags=re.S)
    assert type_block is not None
    type_html = type_block.group(0)
    visible_before_details = type_html.split('<details class="receipt-detail is-receipt-detail">', 1)[0]

    assert "type-role-list" in type_html
    assert "Headline" in type_html
    assert "Body" in type_html
    assert "Label / mono" in type_html
    assert "SHA-256" not in visible_before_details
    assert "SHA-256" in type_html
    assert "Rendered preview" not in visible_before_details
    assert "Actual font loaded" not in visible_before_details


def test_route_type_specimen_does_not_execute_route_type_prose_as_css():
    pack = sample_pack()
    pack["routes"][0]["type"] = 'Expressive lunchbox lettering"; color:red;'

    html = render_dossier(pack)
    route_specimen_styles = re.findall(r'class="route-specimen" style="font-family:([^"]+)"', html)

    assert route_specimen_styles
    assert all("Expressive lunchbox lettering" not in style for style in route_specimen_styles)
    assert "Expressive lunchbox lettering&quot;" in html
    assert "<dd>color:red</dd>" in html
    assert "Rendered preview" not in html
    assert 'data-font-preview-status="fallback_approximation"' in html


def test_moodboard_canvas():
    # PACK-05 (VALIDATION line 48): the Moodboard is a real route board: a calm
    # a primary visual panel, readable supporting panels, swatch strip, type specimens,
    # annotations, tension pairs, a constraint legend, and an accessible lightbox.
    html = render_dossier(sample_pack())

    # Stable canvas scope; the class name is historical, but the public panel is no
    # longer a heavy dark cage around the work.
    assert "moodboard-canvas--dark" in html
    style = html.split("<style>", 1)[1].split("</style>", 1)[0]
    assert "grid-template-columns: minmax(min(100%, 420px), 0.95fr) minmax(0, 1.25fr)" in style
    assert "grid-template-columns: repeat(4, minmax(0, 1fr))" in style

    # Content-responsive route board: one primary visual panel plus a multi-view
    # evidence wall. The old single-image-plus-support-column structure now keeps
    # support notes folded after the visual views.
    assert 'class="moodboard-grid"' in html
    assert 'class="moodboard-primary"' in html
    assert 'class="moodboard-view-grid"' in html
    assert 'class="moodboard-support-stack"' in html
    assert 'class="moodboard-support-detail"' in html
    assert "mood-tile--visual" in html
    assert "mood-tile--support" in html
    for role in ("detail", "web", "phone", "palette", "type", "material", "motion"):
        assert f'data-view-role="{role}"' in html, f"missing moodboard view role {role}"
    for label in ("Detail view", "Website view", "Phone view", "Palette", "Type", "Material cue", "Movement"):
        assert label in html
    for span in ("mood-tile--hero", "mood-tile--rail", "mood-tile--medium", "mood-tile--wide", "mood-tile--small"):
        assert span in html, f"missing tile role {span}"

    # Board metadata: swatch strip (palette as board DNA), tile annotations, tension
    # pairs (Wants / Avoid), and an in/out constraint legend. Dense metadata is
    # progressively disclosed instead of crammed into fixed-height cards.
    assert "swatch-strip" in html
    assert "tile-annotation" in html or 'class="annotation"' in html
    assert "tension-pair" in html
    assert "mood-tile-detail" in html
    assert "moodboard-legend" in html
    assert "In-bounds" in html
    assert "Out-of-bounds" in html

    # Accessible lightbox (Fix-6): role=dialog + aria-modal + visible close, focus on open.
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert 'class="lightbox-close"' in html
    assert "lightboxClose?.focus()" in html


def test_moodboard_layout_is_content_responsive_not_fixed_bento_cage():
    html = render_dossier(sample_pack())
    style = html.split("<style>", 1)[1].split("</style>", 1)[0]

    assert "grid-auto-rows: 150px" not in style
    assert "grid-auto-flow: dense" not in style

    moodboard_rule = re.search(r"\.moodboard-grid\s*\{(?P<body>[^}]*)\}", style)
    assert moodboard_rule
    assert "minmax(min(100%, 420px), 0.95fr)" in moodboard_rule.group("body")
    assert "minmax(0, 1.25fr)" in moodboard_rule.group("body")
    assert "grid-auto-rows" not in moodboard_rule.group("body")
    assert "grid-auto-flow" not in moodboard_rule.group("body")

    view_rule = re.search(r"\.moodboard-view-grid\s*\{(?P<body>[^}]*)\}", style)
    assert view_rule
    assert "repeat(4, minmax(0, 1fr))" in view_rule.group("body")

    tile_rule = re.search(r"\n\s*\.mood-tile\s*\{(?P<body>[^}]*)\}", style)
    assert tile_rule
    assert "overflow: hidden" not in tile_rule.group("body")
    assert "overflow: visible" in tile_rule.group("body")


def test_moodboard_mobile_collapses_without_min_height_cage_or_horizontal_overflow():
    html = render_dossier(sample_pack())
    style = html.split("<style>", 1)[1].split("</style>", 1)[0]
    mobile = style.split("@media (max-width: 980px)", 1)[1].split("@media (max-width: 640px)", 1)[0]

    assert ".moodboard-grid" in mobile
    assert "grid-template-columns: 1fr" in mobile
    assert "overflow-x: hidden" in mobile
    assert "min-height: 200px" not in mobile


def test_route_initialization_ignores_stale_local_storage_route():
    html = render_dossier(sample_pack())
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]

    assert "const validRoutes = new Set" in script
    assert "function storageGet(key)" in script
    assert "const storedRoute = storageGet(storageKey);" in script
    assert "validRoutes.has(storedRoute) ? storedRoute : firstRoute" in script


def _offline_keyless_pack():
    # A normal keyless run via the conftest OfflineDirector parity oracle — no --fixture.
    pack = run_london_session(
        """# Kids Lunchbox

        Create a school lunchbox system for kids, parents, snack choices, stickers,
        backpack routines, and daily lunch reveal moments.
        """
    )
    enrich_workbench_pack(pack)
    return pack


def test_moodboard_real_image_or_honest_state_never_fixture_as_routine():
    # HON-03 (VALIDATION line 49): on a normal keyless run (no --fixture) the visual slot
    # is a real <img> (generated-concept-image) OR an honest visual-direction-board /
    # legacy prompt/unavailable state — a fixture-system-sketch SVG NEVER appears as routine output,
    # and the branch keys on tile["kind"], not on asset_src presence alone.
    pack = _offline_keyless_pack()
    html = render_dossier(pack)

    # Strip the <style> block: the renderer legitimately defines .visual-slot--fixture-
    # system-sketch CSS (needed to STYLE state 4 under --fixture). The absence assertion
    # must check rendered MARKUP only, not the always-shipped stylesheet (comment-safe).
    body_markup = re.sub(r"<style>.*?</style>", "", html, flags=re.DOTALL)

    # The keyless parity oracle wires a deterministic SVG into the hero asset_src, but the
    # hero kind is NOT a live generation — so it must render an honest prompt state, never
    # the --fixture-only system-sketch state and never that SVG dressed as a concept image.
    # (The rendered state-4 marker is "system-sketch" — the QA word "fixture" stays out of
    # shipped markup; the Python branch still keys on the kind literal "fixture-system-sketch".)
    assert 'data-visual-state="system-sketch"' not in body_markup, (
        "a fixture SVG must never be routine output"
    )
    assert "visual-slot--system-sketch" not in body_markup

    # Every hero tile renders exactly one honest, distinguishable state keyed on kind.
    visual_states = re.findall(r'data-visual-state="([^"]+)"', body_markup)
    assert visual_states, "the moodboard/route hero must declare an explicit visual state"
    allowed = {"generated", "generation-unavailable", "manual-prompt-card", "visual-direction-board"}
    assert all(state in allowed for state in visual_states), (
        f"routine visual states must be honest (got {visual_states!r})"
    )

    # The 4 states are distinguishable in the source (branch keys on kind, not asset_src).
    render_src = inspect.getsource(render_mod)
    for marker in ("generated-concept-image", "visual-direction-board", "generation-unavailable", "manual-prompt-card", "fixture-system-sketch"):
        assert marker in render_src, f"explicit kind branch must handle {marker!r}"


def test_visual_slot_rejects_javascript_asset_src_links():
    pack = _offline_keyless_pack()
    tile = pack["moodboard_tiles"][0]["tiles"][0]
    tile["kind"] = "visual-direction-board"
    tile["asset_src"] = "javascript:alert(1)"

    html = render_dossier(pack)

    assert 'href="javascript:' not in html
    assert 'src="javascript:' not in html
    assert 'data-lightbox-src="javascript:' not in html


def test_visual_slot_keeps_safe_asset_href():
    pack = _offline_keyless_pack()
    tile = pack["moodboard_tiles"][0]["tiles"][0]
    tile["kind"] = "visual-direction-board"
    tile["asset_src"] = "assets/knob-proof.png"

    html = render_dossier(pack)

    assert 'href="assets/knob-proof.png"' in html


def test_static_prototype_rejects_javascript_asset_src():
    pack = sample_pack()
    pack["routes"][0]["assets"] = [
        {
            "kind": "generated-concept-image",
            "src": "javascript:alert(1)",
            "title": "Unsafe image",
        }
    ]

    html = render_static_prototype(pack, route_id=pack["routes"][0]["id"])

    assert 'src="javascript:' not in html


def test_moodboard_first_layer_uses_reader_labels_not_provider_status_copy():
    pack = _offline_keyless_pack()
    html = render_dossier(pack)
    moodboard = html.split('<section class="dossier-section" id="moodboard"', 1)[1].split(
        '<section class="dossier-section route-switcher"', 1
    )[0]
    first_layer = re.sub(r"<details.*?</details>", "", moodboard, flags=re.DOTALL)
    visible_text = re.sub(r"<[^>]+>", " ", first_layer).lower()

    assert '<p class="tile-kind">Visual direction</p>' in first_layer or '<p class="tile-kind">Image direction</p>' in first_layer
    assert re.search(r'<div class="palette-board">', first_layer), (
        "palette should render as large visual blocks in the first layer"
    )
    assert "swatch-strip mini" not in first_layer
    assert not re.search(r"\b[a-z][a-z0-9_-]*=#[0-9a-f]{3,8}\b", visible_text), (
        "raw palette variable strings must not replace visual swatches"
    )
    assert not re.search(r"#[0-9a-f]{3,8}", visible_text), (
        "first-read moodboard swatches should show color/name, not diagnostic hex labels"
    )
    direction_summary = re.search(
        r'<figure class="visual-slot visual-slot--direction-summary"[\s\S]*?</figure>',
        first_layer,
    )
    if direction_summary:
        assert "<img" not in direction_summary.group(0)
        assert "data-lightbox-src" not in direction_summary.group(0)
        assert "prompt" not in _visible_text(direction_summary.group(0)).lower()
    for marker in (
        "actual font loaded",
        "generated_live",
        "image generation was disabled",
        "local_fallback",
        "manual prompt",
        "manual-prompt",
        "provider:",
        "provider-backed",
        "requested:",
    ):
        assert marker not in visible_text
    assert '<p class="tile-kind">manual prompt card</p>' not in first_layer.lower()
    assert '<p class="tile-kind">visual direction board</p>' not in first_layer.lower()
    assert "visual proof" not in visible_text
    assert "direction board" not in visible_text


def test_moodboard_public_accessibility_copy_filters_provider_scaffold_terms():
    pack = _offline_keyless_pack()
    first_group = pack["moodboard_tiles"][0]
    hero_tile = first_group["tiles"][0]
    hero_tile["kind"] = "generated-concept-image"
    hero_tile["asset_alt"] = "provider-generated concept image status generated_live receipt asset_sha256"

    html = render_dossier(pack)
    moodboard = html.split('<section class="dossier-section" id="moodboard"', 1)[1].split(
        '<section class="dossier-section route-switcher"', 1
    )[0]
    first_layer = _strip_details(moodboard)
    public_copy = _rendered_user_copy(first_layer).lower()

    for marker in (
        "provider-generated",
        "generated concept",
        "generated_live",
        "fallback",
        "schema",
        "debug",
        "asset_sha256",
        "sha256",
    ):
        assert marker not in public_copy
    assert "product view" in public_copy


def test_public_first_layer_demotes_receipt_and_raw_palette_terms_outside_audit_boundary():
    pack = _offline_keyless_pack()
    html = render_dossier(pack)

    for anchor in ("comparison", "conversation", "constraints", "evidence"):
        section = html.split(f'<section class="dossier-section" id="{anchor}"', 1)[1].split(
            '<section class="dossier-section"', 1
        )[0]
        first_layer = _strip_details(re.sub(r"<details\b[\s\S]*</details>", "", section))
        visible_text = _visible_text(first_layer).lower()

        assert "provider" not in visible_text
        assert "object proof" not in visible_text
        assert not re.search(r"\b[a-z][a-z0-9_-]*:\s+[^;#]+#[0-9a-f]{3,8}", visible_text)


def test_default_visible_copy_translates_audit_terms_outside_folded_bodies():
    html = render_dossier(_offline_keyless_pack())
    copy = _default_visible_user_copy(html).lower()

    for marker in (
        "object proof",
        "provider and local receipts",
        "receipts / debug",
        "local proof",
        "open deterministic receipts",
        "debug source ref",
        "receipt records",
        "provider-backed artifact receipt",
        "live artifacts",
        "live evidence note",
        "generated work",
    ):
        assert marker not in copy

    assert "product cue" in copy
    assert "run source trail" in copy
    assert "run records" in copy
    assert "open run records" in copy
    assert "live route assets" in copy
    assert "source trail confirms a completed reference or image asset" in copy


def test_comparison_first_layer_filters_prompt_shaped_route_thesis():
    pack = _offline_keyless_pack()
    html = render_dossier(pack)
    comparison = html.split('<section class="dossier-section" id="comparison"', 1)[1].split(
        '<section class="dossier-section" id="font-lab"', 1
    )[0]
    first_layer = _strip_details(comparison)
    visible_text = _visible_text(first_layer).lower()

    assert not re.search(
        r"\b(?:make|turn)\s+[^.]*product brief[^.]*\b(?:first real decision|route people can compare)\b",
        visible_text,
    )
    assert "provider" not in visible_text
    assert "fallback" not in visible_text
    assert "offline" not in visible_text
    assert "fixture" not in visible_text
    assert "debug" not in visible_text


def test_comparison_uses_readable_cards_instead_of_fixed_width_wall_table():
    html = render_dossier(_offline_keyless_pack())
    style = re.search(r"<style>(.*?)</style>", html, flags=re.DOTALL).group(1)
    comparison = html.split('<section class="dossier-section" id="comparison"', 1)[1].split(
        '<section class="dossier-section" id="font-lab"', 1
    )[0]
    first_layer = _strip_details(comparison)

    assert '<div class="comparison-cards">' in first_layer
    assert '<table class="route-matrix">' not in first_layer
    assert "matrix-scroll" not in first_layer
    assert "grid-template-columns: repeat(auto-fit, minmax(min(100%, 340px), 1fr))" in style
    comparison_rules = "\n".join(re.findall(r"\.comparison[^{}]*\{[^}]*\}", style))
    assert "min-width: 1180px" not in comparison_rules
    assert "white-space: nowrap" not in comparison_rules
    assert "overflow-x: auto" not in comparison_rules


def test_comparison_cards_preserve_london_route_fields_with_secondary_details():
    pack = _offline_keyless_pack()
    html = render_dossier(pack)
    comparison = html.split('<section class="dossier-section" id="comparison"', 1)[1].split(
        '<section class="dossier-section" id="font-lab"', 1
    )[0]

    for row in pack["route_comparison"]:
        assert escape(row["title"]) in comparison
        for field in ("best_for", "visual_world", "type", "risk", "palette_logic", "steal", "do_not_copy", "first_build_move"):
            assert escape(_public_handoff_text(row[field])) in comparison
    assert comparison.count("<details") >= len(pack["route_comparison"])
    assert "Build details" in comparison


def test_route_detail_first_layer_does_not_use_offline_prompt_thesis_as_specimen():
    pack = _offline_keyless_pack()
    html = render_dossier(pack)
    routes = html.split('<section class="dossier-section route-switcher" id="routes"', 1)[1].split(
        '<section class="dossier-section" id="comparison"', 1
    )[0]
    first_layer = _strip_details(routes)
    visible_text = _visible_text(first_layer).lower()

    assert "route-specimen" in first_layer
    assert "kid choice kit" in visible_text
    assert not re.search(
        r"\b(?:make|turn)\s+kids\s+lunchbox\b.*\b(?:first real decision|route people can compare)\b",
        visible_text,
    )


# =============================================================================
# Phase 4.5 HERO-03 — honest artifact type-label on the hero tile (RED stub; W0).
# The hero tile carries a TYPE label (e.g. "Website mockup") describing WHAT is
# being designed, ORTHOGONAL to the visual STATE (a card still reads as a card,
# never as a generated image). Fails today: no artifact_type carry + no type
# label in the rendered hero. Wave 4 drives it GREEN.
# =============================================================================


def test_hero_tile_carries_honest_artifact_label():
    # Render a keyless pack tagged artifact_type="website". The hero tile must surface an
    # honest TYPE label ("Website mockup") that is ORTHOGONAL to data-visual-state — a
    # keyless board still declares an honest direction-board/unavailable state, never "generated".
    pack = _offline_keyless_pack()
    pack["artifact_type"] = "website"
    enrich_workbench_pack(pack)
    html = render_dossier(pack)

    body_markup = re.sub(r"<style>.*?</style>", "", html, flags=re.DOTALL)

    # The honest TYPE label appears (describes the artifact, never claims generation).
    assert "Website mockup" in body_markup, "hero tile must carry an honest artifact type label"

    # ORTHOGONALITY: the visual-state is still one of the honest non-generated states.
    visual_states = re.findall(r'data-visual-state="([^"]+)"', body_markup)
    assert visual_states
    allowed = {"generated", "generation-unavailable", "manual-prompt-card", "visual-direction-board"}
    assert all(state in allowed for state in visual_states), (
        f"the type label must not change the honest visual state (got {visual_states!r})"
    )
    # The keyless hero is NOT a generated image — the type label must not promote it.
    assert "generated" not in visual_states, (
        "a keyless website board must stay non-generated; the type label is metadata, not a generation claim"
    )


def test_workbench_has_mobile_route_cards_and_selected_route_copy_actions():
    html = render_dossier(sample_pack())
    handoff = html.split('<section class="dossier-section" id="handoff"', 1)[1].split(
        '<section class="dossier-section" id="receipts"', 1
    )[0]

    assert 'class="comparison-cards"' in html
    assert 'class="comparison-card"' in html
    assert "Copy route brief" in handoff
    assert "Selected route brief" in handoff
    assert "Internal image direction artifact" in handoff
    assert "Internal prototype build artifact" in handoff
    assert "Copy image prompt" not in handoff
    assert "Copy builder prompt" not in handoff
    assert 'class="route-copy-panel"' in html


def test_handoff_first_layer_demotes_private_prompt_machinery():
    html = render_dossier(sample_pack())
    handoff = html.split('<section class="dossier-section" id="handoff"', 1)[1].split(
        '<section class="dossier-section" id="receipts"', 1
    )[0]
    first_layer = _strip_details(handoff)
    visible_text = _visible_text(first_layer).lower()

    assert "selected route brief" in visible_text
    assert "copy route brief" in visible_text
    assert "first build" in visible_text
    assert "visual read" in visible_text
    assert "type direction" in visible_text
    for marker in (
        "private brief context",
        "allowed visible words",
        "private london rationale",
        "public proof text discipline",
        "copy image prompt",
        "copy builder prompt",
        "builder prompt:",
        "image prompt:",
        "prompt transcript",
        "provider",
        "sha",
        "hash",
    ):
        assert marker not in visible_text

    assert "Private brief context" in handoff
    assert "Allowed visible words" in handoff
    assert "Private London rationale" in handoff
    assert "Copy internal text" in handoff


def test_workbench_links_london_session_summary_without_proof_language():
    html = render_dossier(sample_pack())
    match = re.search(r'<section class="session-summary-link".*?</section>', html, flags=re.S)
    assert match is not None, "Workbench handoff must expose the London session summary artifact"
    link_block = match.group(0)
    label_text = _visible_text(link_block)

    assert 'href="london-session.json"' in link_block
    assert "London session summary" in label_text
    assert "Open session summary" in label_text
    assert "decisions" in label_text
    assert "reasoning" in label_text
    for blocked in ("provider", "telemetry", "receipt", "sha", "launch-gate", "MODE", "GATES", "CONFIDENCE"):
        assert blocked.lower() not in label_text.lower()


def test_renderers_do_not_leak_python_dict_briefs():
    pack = {
        "title": "Dict Brief",
        "brief": {
            "title": "Structured Brief",
            "text": "Clean structured brief copy should render.",
            "digest": "abc123",
        },
        "summary": "Clean structured brief copy should render.",
        "routes": [
            {
                "id": "structured-route",
                "title": {"text": "Structured Route"},
                "headline": {"text": "Clean route headline"},
                "subhead": {"text": "Clean route subhead"},
                "lore": [{"text": "Clean lore"}],
                "mood": {"text": "Clean mood"},
                "type": {"text": "Clean type"},
                "rationale": {"text": "Clean rationale"},
                "sections": [
                    {"title": {"text": "Clean section"}, "body": {"text": "Clean body"}},
                ],
            }
        ],
    }

    html = render_dossier(pack)
    prototype = render_static_prototype(pack)

    assert "Clean structured brief copy should render." in html
    assert "Clean route headline" in html
    assert "Clean section" in prototype
    assert "Clean body" in prototype
    assert "{'title'" not in html
    assert "{&#x27;title" not in html
    assert "{&#x27;text" not in html
    assert "{'title'" not in prototype
    assert "{&#x27;title" not in prototype
    assert "{&#x27;text" not in prototype


def test_static_prototype_route_renders_first_pass_from_london_pack(tmp_path):
    brief = tmp_path / "brief.md"
    brief.write_text(
        """# Kids Lunchbox

        Create a school lunchbox system for kids, parents, snack choices, stickers,
        backpack routines, and daily lunch reveal moments.
        """,
        encoding="utf-8",
    )
    pack = write_london_pack(brief, tmp_path / "pack", image_provider="auto")
    route_id = pack["routes"][0]["id"]
    html = render_static_prototype(pack, route_id=route_id)

    assert f'class="prototype-route" id="prototype-content" data-route-id="{route_id}"' in html
    assert 'class="prototype-nav"' in html
    assert 'href="#routes"' in html
    assert 'href="#route-sections"' in html
    assert "London Osei first-pass prototype" in html
    assert "internal visual direction board" in html
    assert 'class="prototype-visual" data-visual-state="visual-direction-board"' in html
    assert "local system sketch / deterministic fallback" not in html
    assert pack["routes"][0]["title"] in html
    assert pack["routes"][1]["title"] in html
    assert 'data-prototype-route-tab=' in html
    assert 'data-prototype-route-panel=' in html
    assert pack["routes"][0]["sections"][0]["title"] in html
    assert pack["routes"][1]["sections"][0]["title"] in html
    assert "Build Constraints" in html
    assert "Generated from a London Pack" not in html
    assert "Preview preview" not in html


def test_static_prototype_hero_uses_content_aware_showcase_mode():
    pack = sample_pack()
    route = pack["routes"][0]
    route["headline"] = "One knob. One job. One object you'll never put in a drawer."
    route["assets"] = [
        {
            "kind": "generated-concept-image",
            "title": "Knob proof render",
            "src": "assets/knob-proof.png",
            "alt": "Generated route proof for the single-knob object.",
            "provider": "gemini",
            "model": "gemini-image-preview",
            "deterministic": False,
            "live_artifact": True,
        }
    ]

    html = render_static_prototype(pack, route_id=route["id"])
    hero = re.search(r'<section class="prototype-hero[^"]*".*?</section>', html, flags=re.S)
    assert hero is not None
    hero_html = hero.group(0)
    caption = re.search(r"<figcaption>(.*?)</figcaption>", hero_html)
    assert caption is not None

    assert "prototype-hero--long-headline" in hero_html
    assert "prototype-hero--editorial" in hero_html
    assert 'class="prototype-visual" data-visual-state="generated"' in hero_html
    assert '<img src="../assets/knob-proof.png"' in hero_html
    assert caption.group(1) == "Route concept image"
    assert "gemini-image-preview" not in caption.group(1)
    assert "font-size: 5.4rem" not in html
    assert ".prototype-hero--long-headline h1" in html


def test_static_prototype_route_argument_switches_to_editorial_measure_when_long():
    pack = sample_pack()
    route = pack["routes"][0]
    long_move = (
        "Set the masthead with tonight's date and weather beside the product decision, "
        "then let the proof image carry the first argument before the control panel appears."
    )
    for row in pack["route_comparison"]:
        if row["route_id"] == route["id"]:
            row["first_build_move"] = long_move
            row["best_for"] = "A launch screenshot where London's argument must remain readable without giving up the visual proof."
            row["steal"] = ""
            row["do_not_copy"] = ""
            row["risk"] = ""
    for group in pack["moodboard_tiles"]:
        if group["route_id"] == route["id"]:
            group["tiles"] = []

    html = render_static_prototype(pack, route_id=route["id"])
    workbench = re.search(r'<section class="prototype-workbench[^"]*".*?</section>', html, flags=re.S)
    assert workbench is not None
    workbench_html = workbench.group(0)
    style = html.split("<style>", 1)[1].split("</style>", 1)[0]

    assert "prototype-workbench--argument-full" in workbench_html
    assert 'class="prototype-argument prototype-argument--editorial"' in workbench_html
    assert escape(long_move) in workbench_html
    assert "max-width: 13ch" not in style
    assert "max-width: 12ch" not in style
    assert ".prototype-argument--editorial h2 { max-width: min(34ch, 72vw);" in style


def test_static_prototype_type_panel_layers_long_type_prose_and_proof_metadata():
    pack = sample_pack()
    route = pack["routes"][0]
    long_type = (
        "Heavy slab grotesque headlines should hold the masthead and product claim. "
        "Plainspoken grotesque body copy should make the build instructions readable. "
        "Tabular mono labels should handle weather, date, price, and proof metadata."
    )
    route["type"] = long_type
    pack["font_options"][0]["options"][1]["font_preview"] = {
        "status": "actual_loaded",
        "delivery": "local_asset",
        "rendered_family": "Familjen Grotesk",
        "source_label": "Fontshare (SIL Open Font License 1.1)",
        "license_note": (
            "Bundled London Type Shelf asset; license checked 2026-06-05; "
            "SHA-256: 5589983a201d1b0b77b55f8c299a4753cff515e86536c4761446a4dd6705a80b."
        ),
        "asset_href": "assets/fonts/familjen-grotesk-500.woff2",
    }

    html = render_static_prototype(pack, route_id=route["id"])
    type_panel = re.search(r'<aside class="prototype-type[^"]*">.*?</aside>', html, flags=re.S)
    assert type_panel is not None
    type_html = type_panel.group(0)
    h2 = re.search(r"<h2>(.*?)</h2>", type_html, flags=re.S)
    assert h2 is not None
    visible_before_details = type_html.split('<details class="prototype-receipt-detail">', 1)[0]

    assert "is-long-type-direction" in type_html
    assert h2.group(1) != escape(long_type)
    assert escape(long_type) not in h2.group(1)
    assert "<dt>Headline</dt>" in type_html
    assert "<dt>Body</dt>" in type_html
    assert "<dt>Label / mono</dt>" in type_html
    assert "SHA-256" not in visible_before_details
    assert "SHA-256" in type_html
    assert "Rendered preview" not in visible_before_details
    assert "Actual font loaded" not in visible_before_details


def test_static_prototype_defaults_to_resolved_recommended_route():
    pack = sample_pack()
    recommended = pack["routes"][1]
    pack["recommended_route_ref"] = recommended["title"]

    html = render_static_prototype(pack)

    assert f'data-route-id="{recommended["id"]}"' in html
    assert f"<title>{escape(recommended['title'])} -" in html


def test_static_prototype_has_full_navigation_system_without_mobile_pill_cloud():
    pack = sample_pack()
    html = render_static_prototype(pack)

    assert 'class="prototype-skip-link" href="#prototype-content"' in html
    assert 'class="prototype-current" aria-live="polite"' in html
    assert "data-current-route" in html
    assert "data-current-section" in html
    assert 'class="prototype-left-rail"' in html
    assert 'class="prototype-mobile-drawer" id="prototype-mobile-drawer" data-mobile-drawer hidden' in html
    assert 'data-mobile-toggle aria-controls="prototype-mobile-drawer" aria-expanded="false"' in html
    assert 'class="prototype-route-switcher" role="tablist"' in html
    assert 'role="tab" aria-selected="true"' in html
    assert 'data-command-palette role="dialog" aria-modal="true"' in html
    assert "data-command-search" in html
    assert "event.metaKey || event.ctrlKey" in html
    assert 'event.key === "/"' in html
    assert 'event.key === "Escape"' in html
    assert "IntersectionObserver" in html
    assert 'aria-current="location"' in html
    assert "is-target-flash" in html
    assert "scroll-margin-top" in html
    assert "data-nav-section" in html

    route_section_count = sum(len(route["sections"]) for route in pack["routes"])
    assert html.count('data-nav-kind="route-section"') >= route_section_count
    for route in pack["routes"]:
        route_id = route["id"]
        assert f'href="#proto-route-{route_id}"' in html
        assert f'data-prototype-route-tab="{route_id}"' in html
        assert f'data-prototype-route-panel="{route_id}"' in html
        for section in route["sections"]:
            assert section["title"] in html

    assert ".prototype-nav div {{ display: flex; flex-wrap: wrap;" not in html
    assert ".prototype-nav a {{ display: inline-flex; align-items: center; min-height: 34px" not in html
    assert "prototype-mobile-pill" not in html
    assert "prototype-pill-cloud" not in html


def test_renderers_include_mobile_overflow_guards():
    pack = sample_pack()
    html = render_dossier(pack)
    prototype = render_static_prototype(pack)

    for rendered in (html, prototype):
        assert "overflow-x: hidden" in rendered
        assert "overflow-wrap: anywhere" in rendered
        assert "calc(100vw - 48px)" in rendered


def test_static_prototype_deterministic_sketches_follow_current_lane():
    horoscope = run_london_session(
        """# Public Horoscope App

        Design a public facing horoscope app for daily astrology readings, birth-chart onboarding,
        compatibility moments, push notifications, and shareable cards.
        """
    )
    pet_weather = run_london_session(
        """# Weather App for Pet Owners

        Design a weather app for pet owners that helps decide when it is safe, comfortable,
        and worth it to walk, play outside, or plan around alerts.
        """
    )

    horoscope_svg = _first_route_svg(horoscope)
    weather_svg = _first_route_svg(pet_weather)
    horoscope_html = render_static_prototype(horoscope)
    weather_html = render_static_prototype(pet_weather)

    assert "scene:chart-briefing" in horoscope_svg
    assert "scene:weather-decision" in weather_svg
    assert horoscope_svg != weather_svg
    # Lane fidelity is proven by the scene markers above + brief-domain vocabulary in the
    # rendered output — NOT by pinning a specific memorized route name. Pinning a
    # BANNED_TEMPLATE_NAMES value here would re-introduce the exact-string brittleness the
    # Phase 1 anti-relapse controls remove (it would also lock the disease back in if this
    # test were ever flipped to the model director). These run on the OfflineDirector
    # parity oracle; we assert the brief's own domain words appear, mode-blind.
    assert "horoscope" in horoscope_html.lower()
    assert "weather" in weather_html.lower() or "pet" in weather_html.lower()
    # Cross-lane leakage guard: the horoscope lane's names/scenes must not bleed into weather.
    assert "scene:chart-briefing" not in weather_svg
    assert "Morning Sign-In" not in weather_html
    assert "Compatibility Card Studio" not in weather_html


def test_renderer_writes_expected_files(tmp_path):
    pack = sample_pack()
    dossier_path = write_dossier(pack, tmp_path / "index.html")
    prototype_path = write_static_prototype(pack, tmp_path)

    assert dossier_path == tmp_path / "index.html"
    assert prototype_path == tmp_path / "prototype" / "index.html"
    assert "dossier-shell" in dossier_path.read_text(encoding="utf-8")
    assert "prototype-route" in prototype_path.read_text(encoding="utf-8")


def _first_route_svg(pack) -> str:
    src = route_assets(pack["routes"][0])[0]["src"]
    return unquote(src.split(",", 1)[1])


def test_swatch_on_white_everywhere():
    # TPL-05 (D-06): every dossier swatch sits on a WHITE chip with a thin border and an
    # visible role/name label, regardless of section background — fixing the Phase-2 bug
    # where dark palette swatches vanished on the dark moodboard canvas without turning
    # the public face into diagnostic hex text. The chip is NO LONGER the color; the color
    # moves to an inner .swatch-chip sample. All dossier swatch sites route through the
    # single _swatches() helper (route palette rail + moodboard tile), so one invert covers
    # everywhere.
    from london.render import _style

    style = _style()

    # 1. The .swatch CSS rule itself: white/--card ground (NOT var(--swatch)) + a 1px border.
    #    Isolate the base ".swatch {" rule (avoid matching ".swatch-chip" / ".swatch small" /
    #    ".swatch-strip").
    swatch_rule = re.search(r"\n\s*\.swatch\s*\{([^}]*)\}", style)
    assert swatch_rule is not None, "expected a base .swatch CSS rule"
    body = swatch_rule.group(1)
    assert "background: var(--card)" in body, "the swatch chip ground must be white (--card), not the color"
    assert "background: var(--swatch)" not in body, "the chip must NOT be the color anymore (that is the Phase-2 bug)"
    assert re.search(r"border:\s*1px\s+solid\s+var\(--border\)", body), "the white chip needs a thin --border hairline"

    # 2. An inner .swatch-chip rule carries the color (the inner sample), never the chip ground.
    chip_rule = re.search(r"\.swatch-chip\s*\{([^}]*)\}", style)
    assert chip_rule is not None, "expected a .swatch-chip rule for the inner color sample"
    assert "background: var(--swatch)" in chip_rule.group(1), "the inner .swatch-chip carries the color"

    # 3. The role/name label reads as mono; exact hex values stay out of first-read text.
    assert re.search(r"\.swatch\s+small\s*\{[^}]*font-family:\s*var\(--mono\)", style), (
        "the swatch label (.swatch small) must be mono and always visible"
    )

    # 4. Rendered markup: every swatch carries an inner .swatch-chip element and a visible
    #    role/name label without a first-read hex, and swatch-on-white holds in BOTH the route
    #    palette rail and the moodboard tile (both route through _swatches).
    html = render_dossier(sample_pack())
    assert 'class="swatch-chip"' in html, "rendered swatches must contain the inner .swatch-chip sample"
    # The route palette rail swatch strip and the moodboard mini swatch strip both render.
    assert 'class="swatch-strip"' in html, "the route palette rail swatch strip must render"
    assert 'class="swatch-strip mini"' in html, "the moodboard tile swatch strip must render"
    # Every <span class="swatch"> contains both a .swatch-chip and a label in its <small>. The
    # swatch span now nests a <span class="swatch-chip">, so anchor each block on the opening
    # <span class="swatch" ...> and capture through the trailing </small></span> close.
    swatches = re.findall(r'<span class="swatch"\s[^>]*>(.*?</small>)\s*</span>', html, re.DOTALL)
    assert swatches, "expected rendered .swatch spans"
    hex_pattern = re.compile(r"#[0-9A-Fa-f]{3,8}")
    for inner in swatches:
        assert 'class="swatch-chip"' in inner, "each swatch must carry an inner .swatch-chip color sample"
        assert "<small>" in inner, "each swatch must carry a <small> role/name label"
        assert not hex_pattern.search(_visible_text(inner)), "first-read swatch labels must not show hex values"


def test_responsive_reflow_640_and_reading_measure():
    # TPL-04 (D-05): a NEW finer @media (max-width: 640px) breakpoint single-columns the
    # comparison matrix, the route meta-rail, and the font lab — LAYERED on the existing
    # @media (max-width: 980px) collapse (roomy two-column persists in the 640–980px band),
    # NOT a re-target of 980 -> 640 (RESEARCH A3 / Pitfall 5). Prose holds the 70ch reading
    # measure so text never runs edge-to-edge.
    from london.render import _style

    style = _style()

    # 1. The existing 980px block is STILL present (the 640px rule is layered, not a re-target).
    assert "@media (max-width: 980px)" in style, "the existing 980px collapse must remain (layer, do not re-target)"

    # 2. A NEW @media (max-width: 640px) rule exists.
    m640 = re.search(r"@media \(max-width: 640px\)\s*\{(.*?)\n\s*\}\n", style, re.DOTALL)
    assert m640 is not None, "a new @media (max-width: 640px) reflow block must exist"
    block = m640.group(1)

    # 3. Inside it, the comparison matrix, route meta-rail, and font lab single-column.
    #    (grid-template-columns: 1fr or equivalent single-column collapse.)
    assert re.search(r"\.comparison-cards[^{}]*\{[^}]*grid-template-columns:\s*1fr", block), (
        "the comparison matrix (comparison-cards) must single-column under 640px"
    )
    assert re.search(r"\.dossier-meta-rail[^{}]*\{[^}]*grid-template-columns:\s*1fr", block), (
        "the route meta-rail must single-column under 640px"
    )
    assert re.search(r"\.font-grid[^{}]*\{[^}]*grid-template-columns:\s*1fr", block), (
        "the font lab (font-grid) must single-column under 640px"
    )

    # 4. The 640px block is positioned AFTER the 980px block so the finer breakpoint layers.
    assert style.index("@media (max-width: 980px)") < style.index("@media (max-width: 640px)"), (
        "the 640px block must come after the 980px block to layer correctly"
    )

    # 5. Reading measure (70ch) is present in the rendered style.
    assert "max-width: 70ch" in style, "prose must hold a 70ch reading measure"


def test_moodboard_tile_missing_hex_renders_without_crash():
    """W2-P6: a moodboard tile whose color entry is missing a 'hex' field must
    not raise KeyError — normalize_palette filters it out, and the render path
    skips or defaults the swatch gracefully.

    Pre-fix concern: _mood_web_view/_mood_phone_view/_mood_palette_view accessed
    colors[n]["hex"] directly without guarding for missing-hex entries that slip
    past the normalizer.  normalize_palette already skips invalid/missing hex
    values (line 44-45 in assets.py), so the crash path requires the normalizer
    to be bypassed.  This test proves the full pipeline (normalizer + renderer)
    does not crash when a color entry has no 'hex' key.
    """
    from london.render import _moodboard

    # A moodboard group whose palette tile has one color missing 'hex' entirely
    # and one with an invalid hex value — both should be filtered by normalize_palette.
    bad_palette_tile = {
        "kind": "palette-strip",
        "colors": [
            {"role": "Primary", "name": "No hex here"},         # missing 'hex'
            {"role": "Secondary", "name": "Bad hex", "hex": "notacolor"},  # invalid hex
            {"role": "Accent", "name": "Good", "hex": "#ff6a2b"},          # valid
        ],
    }
    hero_tile = {
        "span": "hero",
        "kind": "visual-direction-board",
        "title": "Test Hero",
        "assets": [{"kind": "visual-direction-board", "src": "", "alt": "Test"}],
    }
    group = {
        "route_id": "route-1",
        "route_title": "Test Route",
        "tiles": [hero_tile, bad_palette_tile],
    }
    pack = {"moodboard_tiles": [group]}

    # Must not raise KeyError.
    html = _moodboard(pack)
    assert "palette" in html or "moodboard" in html


def test_grader_score_true_does_not_render_a_fill_bar():
    """W2-P6: when a grader inspector's score is the boolean True (not a number),
    the renderer must NOT emit a fill bar (which would show 100% — False positive).
    It must emit the honest-absence 'verdict-bar--na' bar instead.

    In Python, isinstance(True, (int, float)) is True (bool IS a subclass of int),
    so without an explicit isinstance(..., bool) guard, True passes the numeric
    check and renders as fill_pct=100%. The guard at renderer line 1816 already
    exists; this test proves it cannot be removed.
    """
    from london.render import _grader_section

    pack_with_bool_score = {
        "grader": {
            "composite": {"score": "n/a", "sub_scores": {}, "weights": {}},
            "inspectors": [
                {
                    "name": "Source Auditor",
                    "dimension": "Source quality",
                    "verdict": "CLAIM_OK",
                    "score": True,  # boolean True — must NOT render as 100% bar
                }
            ],
            "audit": {
                "show_verified_only": False,
                "verified_claims": [],
                "unverified_claims": [],
                "flag": "CLAIM_UNVERIFIED",
            },
            "headline": "Open check",
            "detail": "Score not captured.",
            "captured": False,
        }
    }

    html = _grader_section(pack_with_bool_score)

    # The bool score must NOT produce a numeric fill bar.
    assert 'width:100.0%' not in html, (
        "score=True must not produce a 100% fill bar (bool guard missing)"
    )
    # It must produce the honest-absence marker instead.
    assert 'verdict-bar--na' in html, (
        "score=True must render the honest-absence (verdict-bar--na) state"
    )
