from typer.testing import CliRunner

from mllminal.cli.main import create_app
from mllminal.config import Settings


def test_learning_governance_commands_are_registered(tmp_path) -> None:
    runner = CliRunner()
    app = create_app(Settings(data_dir=tmp_path, workspace_root=tmp_path))

    evaluate = runner.invoke(app, ["learning", "evaluate", "policy_v1"])
    compare = runner.invoke(app, ["learning", "compare", "policy_v1", "policy_v0"])
    promote = runner.invoke(app, ["learning", "promote", "policy_v1"])
    rollback = runner.invoke(app, ["learning", "rollback"])

    assert evaluate.exit_code != 2
    assert compare.exit_code != 2
    assert promote.exit_code != 2
    assert rollback.exit_code != 2
