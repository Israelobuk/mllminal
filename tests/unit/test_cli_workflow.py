import json

from typer.testing import CliRunner

from mllminal.cli.main import create_app
from mllminal.config import Settings
from mllminal.workflow.contracts import (
    WorkflowDefinition,
    WorkflowPermission,
    WorkflowStep,
    WorkflowVerification,
)

runner = CliRunner()


def test_cli_exposes_durable_workflow_execution_and_recovery_commands(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path, workspace_root=tmp_path)
    app = create_app(settings)
    definition = WorkflowDefinition(
        name="cli fixture",
        permissions=[WorkflowPermission(capability="fixture.ok", scope="fixture")],
        steps=[
            WorkflowStep(
                capability="fixture.ok",
                order=1,
                approval_required=False,
                verification=WorkflowVerification(expected={"ok": True}),
            )
        ],
    )
    created = runner.invoke(app, ["workflow", "create", definition.model_dump_json()])
    assert created.exit_code == 0, created.stdout
    workflow_id = json.loads(created.stdout)["id"]
    activated = runner.invoke(app, ["workflow", "activate", workflow_id])
    assert activated.exit_code == 0, activated.stdout
    preview = runner.invoke(app, ["workflow", "preview", workflow_id])
    assert preview.exit_code == 0, preview.stdout
    run_id = json.loads(preview.stdout)["id"]

    execution = runner.invoke(app, ["workflow", "execution", run_id])
    attempts = runner.invoke(app, ["workflow", "attempts", run_id])
    checkpoints = runner.invoke(app, ["workflow", "checkpoints", run_id])
    resume = runner.invoke(app, ["workflow", "resume", run_id])

    assert execution.exit_code == attempts.exit_code == checkpoints.exit_code == 0
    assert json.loads(execution.stdout)["id"] == run_id
    assert json.loads(attempts.stdout) == []
    assert json.loads(checkpoints.stdout) == []
    assert resume.exit_code != 0
