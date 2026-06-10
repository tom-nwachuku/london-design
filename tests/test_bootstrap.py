from typer.testing import CliRunner

from london.cli import app


def test_cli_help_loads():
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "London Osei" in result.output
