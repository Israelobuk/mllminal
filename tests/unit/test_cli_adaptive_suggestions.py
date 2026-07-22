from typer.testing import CliRunner

from mllminal.cli.main import create_app
from mllminal.config import Settings
from mllminal.contracts import utc_now
from mllminal.mining.contracts import MinedStep, WorkflowCandidate

runner = CliRunner()


def test_suggestion_and_preference_cli_commands_use_durable_state(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path, workspace_root=tmp_path)
    now = utc_now()
    candidate = WorkflowCandidate(
        id="candidate-cli",
        application="explorer",
        steps=[
            MinedStep(application="explorer", kind="control.invoked"),
            MinedStep(application="explorer", kind="control.invoked"),
        ],
        occurrences=5,
        confidence=0.8,
        first_seen=now,
        last_seen=now,
        source_event_ids=["event-cli"],
    )
    app = create_app(settings)
    proposed = runner.invoke(
        app,
        [
            "suggestions",
            "propose",
            '{"candidate": ' + candidate.model_dump_json() + ', "verification_available": true}',
        ],
    )

    assert proposed.exit_code == 0
    listed = runner.invoke(app, ["suggestions", "list"])
    preference = runner.invoke(
        app,
        [
            "preferences",
            "set",
            (
                '{"preference": {"scope": "workflow", '
                '"candidate_id": "candidate-cli", "enabled": false}}'
            ),
        ],
    )

    assert listed.exit_code == preference.exit_code == 0
    assert "candidate-cli" in listed.stdout
    assert '"enabled":false' in preference.stdout
