from typer.testing import CliRunner

from mllminal.cli.main import create_app
from mllminal.config import Settings

runner = CliRunner()


def test_models_commands_show_and_change_persisted_provider(tmp_path) -> None:
    app = create_app(Settings(data_dir=tmp_path, workspace_root=tmp_path))

    initial = runner.invoke(app, ["models"])
    switched = runner.invoke(app, ["models", "use", "deterministic"])
    current = runner.invoke(app, ["models", "provider"])
    tested = runner.invoke(app, ["models", "test"])

    assert initial.exit_code == 0
    assert "Qwen" in initial.stdout
    assert switched.exit_code == 0
    assert "Deterministic fixture" in switched.stdout
    assert current.stdout.strip() == "deterministic"
    assert tested.exit_code == 0
    assert "does not contact a model server" in tested.stdout


def test_qwen_model_commands_report_probe_result(tmp_path) -> None:
    async def available(_config) -> bool:
        return True

    app = create_app(Settings(data_dir=tmp_path, workspace_root=tmp_path), model_probe=available)

    status = runner.invoke(app, ["models", "status"])
    tested = runner.invoke(app, ["models", "test"])

    assert status.exit_code == 0
    assert "Connection: Available" in status.stdout
    assert tested.exit_code == 0
    assert "Qwen model is available" in tested.stdout
