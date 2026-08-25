from typer.testing import CliRunner

from mllminal.cli.main import create_app
from mllminal.config import Settings


def test_cli_exposes_latency_benchmark_command(tmp_path) -> None:
    app = create_app(Settings(data_dir=tmp_path, workspace_root=tmp_path))

    result = CliRunner().invoke(app, ["benchmark", "latency", "--help"])

    assert result.exit_code == 0, result.stdout
    assert "latency" in result.stdout.lower()
