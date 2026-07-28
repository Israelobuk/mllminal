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


def test_learning_offline_train_reports_an_unpromoted_candidate(tmp_path) -> None:
    from mllminal.learning.contracts import TrainingExperience
    from mllminal.learning.replay import LearningRepository

    settings = Settings(data_dir=tmp_path, workspace_root=tmp_path)
    repository = LearningRepository(settings.database_path)
    repository.initialize()
    for source_id, action in (
        ("one", "present"),
        ("two", "present"),
        ("three", "defer"),
        ("four", "defer"),
    ):
        repository.save_training_experience(
            TrainingExperience(
                policy_domain="SUGGESTION_RANKING",
                source_record_type="suggestion_feedback",
                source_record_id=source_id,
                context_features={"occurrence_count": 0.5},
                candidate_actions=("present", "defer"),
                selected_action=action,
                baseline_score=0.5,
                reward=1.0,
                reward_components={"feedback": 1.0},
                privacy_approved=True,
                eligible_for_training=True,
            )
        )

    result = runner.invoke(
        create_app(settings),
        ["learning", "offline-train", "SUGGESTION_RANKING", "--epochs", "2", "--hidden-size", "8"],
    )

    assert result.exit_code == 0
    assert "Candidate lifecycle: TRAINED" in result.stdout
    assert "Automatic promotion: Disabled" in result.stdout
