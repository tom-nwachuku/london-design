from london.cli import main
from london.intake import build_intake_markdown, render_intake_html


def test_intake_html_is_open_text_not_closed_picker():
    html = render_intake_html()

    assert "London Intake" in html
    assert 'textarea id="brief"' in html
    assert "required" in html
    assert "<details" in html
    for label in ("Refusals", "Anti-audience", "Seeds", "Artifact hint"):
        assert label in html

    for closed_control in ("<select", 'type="radio"', 'type="checkbox"', "<datalist"):
        assert closed_control not in html
    for fake_backend in ("localStorage", "fetch(", "XMLHttpRequest", "form action="):
        assert fake_backend not in html
    assert "artifact:" not in html
    assert "--artifact" not in html


def test_intake_markdown_preserves_uncertainty_without_artifact_override():
    markdown = build_intake_markdown(
        "Build a repair ritual for a family lunchbox.",
        refusals="none yet",
        anti_audience="enterprise dashboards",
        seeds="school stickers, backpack reveal",
        artifact_hint="product",
    )

    assert "Build a repair ritual for a family lunchbox." in markdown
    assert "none yet" in markdown
    assert "enterprise dashboards" in markdown
    assert "school stickers" in markdown
    assert "I think this might be: product" in markdown
    assert "London may reframe this. This is not an artifact override." in markdown
    assert "\nartifact:" not in markdown
    assert "--artifact" not in markdown


def test_intake_requires_brief_for_markdown():
    try:
        build_intake_markdown("")
    except ValueError as exc:
        assert "required" in str(exc)
    else:  # pragma: no cover - this path is the failure mode
        raise AssertionError("empty intake brief must fail")


def test_intake_cli_writes_html_and_prints_markdown(tmp_path, capsys):
    out = tmp_path / "intake.html"
    main(["intake", "--out", str(out)])

    assert out.exists()
    assert "London Intake" in out.read_text(encoding="utf-8")

    main(
        [
            "intake",
            "--print-markdown",
            "--brief",
            "Build a field kit for anxious pet weather.",
            "--anti-audience",
            "generic weather apps",
            "--artifact-hint",
            "app",
        ]
    )
    output = capsys.readouterr().out

    assert "# London Intake Brief" in output
    assert "Build a field kit for anxious pet weather." in output
    assert "generic weather apps" in output
    assert "I think this might be: app" in output
    assert "\nartifact:" not in output
