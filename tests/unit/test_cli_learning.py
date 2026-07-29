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


def test_learning_policy_train_uses_authenticated_daemon_and_safe_output(tmp_path) -> None:
    class FakeDaemonClient:
        def __init__(self, _settings) -> None:
            self.calls = []

        async def offline_train(self, payload, *, idempotency_key):
            self.calls.append((payload, idempotency_key))
            return {
                "snapshot": {
                    "snapshot_id": "snapshot-1",
                    "policy_domain": "SUGGESTION_RANKING",
                },
                "training_run": {"id": "run-1", "status": "COMPLETED"},
                "candidate": {
                    "id": "candidate-1",
                    "lifecycle": "TRAINED",
                    "name": "policy_v1",
                },
                "worker": {"status": "COMPLETED", "worker_pid": 1234},
            }

    clients = []

    def factory(settings):
        client = FakeDaemonClient(settings)
        clients.append(client)
        return client

    app = create_app(
        Settings(data_dir=tmp_path, workspace_root=tmp_path),
        daemon_client_factory=factory,
    )

    result = runner.invoke(
        app,
        [
            "learning",
            "policy",
            "train",
            "--domain",
            "SUGGESTION_RANKING",
            "--epochs",
            "2",
            "--hidden-size",
            "8",
        ],
    )

    assert result.exit_code == 0
    assert "Worker job ID: 1234" in result.stdout
    assert "Training run ID: run-1" in result.stdout
    assert "Candidate policy ID: candidate-1" in result.stdout
    assert "snapshot-1" in result.stdout
    assert "source_record_id" not in result.stdout
    assert clients[0].calls == [
        (
            {
                "policy_domain": "SUGGESTION_RANKING",
                "epochs": 2,
                "hidden_size": 8,
                "seed": 42,
                "learning_rate": 0.01,
                "cpu_threads": 1,
                "timeout_seconds": 30.0,
            },
            "cli-learning-policy-train-SUGGESTION_RANKING",
        )
    ]


def test_learning_active_commands_are_daemon_backed_and_json_safe(tmp_path) -> None:
    class FakeDaemonClient:
        async def active_policy_bindings(self):
            return [
                {
                    "policy_domain": "SUGGESTION_RANKING",
                    "status": "ACTIVE",
                    "candidate_id": "candidate-1",
                }
            ]

        async def active_policy_binding(self, domain):
            return {"policy_domain": domain, "status": "ACTIVE", "candidate_id": "candidate-1"}

        async def enable_active_policy(self, domain, payload, *, idempotency_key):
            return {
                "policy_domain": domain,
                "status": "ACTIVE",
                "candidate_id": payload["candidate_id"],
            }

        async def disable_active_policy(self, domain, *, idempotency_key):
            return {"policy_domain": domain, "status": "INACTIVE"}

    app = create_app(
        Settings(data_dir=tmp_path, workspace_root=tmp_path),
        daemon_client_factory=lambda _settings: FakeDaemonClient(),
    )

    listed = runner.invoke(app, ["learning", "active", "list", "--json"])
    shown = runner.invoke(app, ["learning", "active", "show", "SUGGESTION_RANKING", "--json"])
    enabled = runner.invoke(
        app,
        ["learning", "active", "enable", "SUGGESTION_RANKING", "candidate-1", "--json"],
    )
    disabled = runner.invoke(app, ["learning", "active", "disable", "SUGGESTION_RANKING", "--json"])

    assert listed.exit_code == shown.exit_code == enabled.exit_code == disabled.exit_code == 0
    assert "candidate-1" in listed.stdout
    assert "SUGGESTION_RANKING" in shown.stdout
    assert "INACTIVE" in disabled.stdout
