from typer.testing import CliRunner

from document_enhancer.cli import app

runner = CliRunner()


def test_help_is_available() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "docenhance" in result.stdout
    assert "doctor" in result.stdout


def test_version_is_available() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "0.1.0"


def test_config_json_is_stable_and_non_secret() -> None:
    result = runner.invoke(app, ["config", "show", "--json"])
    assert result.exit_code == 0
    assert '"backend": "developer_api"' in result.stdout
    assert "api_key" not in result.stdout.lower()
