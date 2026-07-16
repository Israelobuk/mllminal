from typer.testing import CliRunner

from mllminal.cli.main import create_app
from mllminal.config import Settings

runner = CliRunner()


def test_learning_status_and_train_commands_report_safe_lifecycle(tmp_path) -> None:
    app = create_app(Settings(data_dir=tmp_path, workspace_root=tmp_path))

    status = runner.invoke(app, ["learning", "status"])
    training = runner.invoke(app, ["learning", "train"])

    assert status.exit_code == 0
    assert "Automatic promotion: Disabled" in status.stdout
    assert training.exit_code == 1
    assert "minimum eligible experience threshold" in training.stdout
