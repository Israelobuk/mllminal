import subprocess
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from mllminal.learning.contracts import (
    ACTION_SPACE_VERSION,
    FEATURE_VERSION,
    EvaluationReport,
    ExperienceOutcome,
    ExperienceRecord,
    PolicyAction,
    PolicyDecision,
    PolicyDomain,
    PolicyLifecycle,
    PromotionDecision,
    PromotionOutcome,
    RewardBreakdown,
    RollbackRecord,
    TrainingRun,
)
from mllminal.learning.replay import LearningRepository


def _experience(decision: PolicyDecision, *, reward: float, key: str) -> ExperienceRecord:
    component = "verification_passed" if reward >= 0 else "task_failure"
    breakdown = RewardBreakdown.model_validate({component: reward, "total": reward})
    return ExperienceRecord(
        task_id=decision.task_id,
        decision_id=decision.id,
        idempotency_key=key,
        selected_action=decision.selected_action,
        outcome=ExperienceOutcome(
            terminal=True,
            verification_passed=reward >= 0,
            task_failed=reward < 0,
        ),
        reward=breakdown,
        status="ELIGIBLE",
    )


def _repository(path: Path, *, capacity: int = 10_000) -> LearningRepository:
    repository = LearningRepository(path)
    repository.initialize()
    repository.update_settings(replay_capacity=capacity)
    return repository


def test_defaults_and_policy_v0_are_bootstrapped(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "state.db")

    settings = repository.get_settings()
    policy = repository.get_promoted_policy()

    assert settings.enabled is True
    assert settings.automatic_promotion_enabled is False
    assert settings.minimum_experience_count == 100
    assert settings.replay_capacity == 10_000
    assert settings.seed == 42
    assert settings.confidence_threshold == 0.65
    assert policy.version == 0
    assert policy.name == "policy_v0"
    assert policy.feature_version == FEATURE_VERSION
    assert policy.action_space_version == ACTION_SPACE_VERSION
    assert policy.checkpoint_sha256 is None


def test_experience_and_replay_survive_restart_and_exclude_duplicates(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    repository = _repository(database)
    decision = PolicyDecision(task_id="task-1", selected_action=PolicyAction.ANSWER_DIRECTLY)
    repository.save_decision(decision, decision_sequence=1)
    experience = _experience(decision, reward=2.0, key="terminal-1")

    saved, created = repository.save_experience(experience, decision_sequence=1)
    duplicate, duplicate_created = repository.save_experience(experience, decision_sequence=1)
    replay, replay_created = repository.add_replay_entry(
        experience.id, features=(0.0,) * 15, action=PolicyAction.ANSWER_DIRECTLY, reward=2.0
    )
    replay_duplicate, replay_duplicate_created = repository.add_replay_entry(
        experience.id, features=(0.0,) * 15, action=PolicyAction.ANSWER_DIRECTLY, reward=2.0
    )

    restarted = LearningRepository(database)
    assert created is True and duplicate_created is False and duplicate.id == saved.id
    assert replay_created is True and replay_duplicate_created is False
    assert replay_duplicate.experience_id == replay.experience_id
    assert restarted.get_experience(experience.id).idempotency_key == "terminal-1"
    assert restarted.count_replay_entries() == 1


def test_replay_sampling_is_seeded_balanced_weighted_and_capacity_pruned(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "state.db", capacity=4)
    for sequence, reward in enumerate((0.0, -4.0, -1.0, 1.0, 10.0), start=1):
        decision = PolicyDecision(
            task_id=f"task-{sequence}", selected_action=PolicyAction.ANSWER_DIRECTLY
        )
        repository.save_decision(decision, decision_sequence=sequence)
        experience = _experience(decision, reward=reward, key=f"terminal-{sequence}")
        repository.save_experience(experience, decision_sequence=sequence)
        repository.add_replay_entry(
            experience.id,
            features=(float(sequence),) + (0.0,) * 14,
            action=PolicyAction.ANSWER_DIRECTLY,
            reward=reward,
        )

    assert repository.count_experiences() == 5
    assert repository.count_replay_entries() == 4
    uniform_a = repository.sample_replay(3, seed=7, reward_balanced=False)
    uniform_b = repository.sample_replay(3, seed=7, reward_balanced=False)
    balanced = repository.sample_replay(4, seed=42, reward_balanced=True)

    assert [item.experience_id for item in uniform_a] == [item.experience_id for item in uniform_b]
    assert sum(item.reward < 0 for item in balanced) == 2
    assert sum(item.reward >= 0 for item in balanced) == 2
    assert all(0.25 <= repository.replay_weight(item.experience_id) <= 4.0 for item in balanced)
    repository.mark_replay_consumed(balanced[0].experience_id)
    assert repository.get_replay_entry(balanced[0].experience_id).consumed_at is not None


def test_global_events_are_ordered_and_replay_after_sequence(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "state.db")

    first = repository.append_event("learning.settings.updated", {"enabled": True})
    second = repository.append_event("learning.training.started", {"eligible_count": 100})

    assert (first.sequence, second.sequence) == (1, 2)
    assert [event.sequence for event in repository.list_events(after_sequence=1)] == [2]


def test_policy_versions_are_sequential_and_only_one_is_promoted(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "state.db")

    first = repository.create_policy_version(checkpoint_sha256="a" * 64)
    second = repository.create_policy_version(checkpoint_sha256="b" * 64)
    repository.promote_policy(second.id, reason="evaluation passed", idempotency_key="promote-2")
    repeated, changed = repository.promote_policy(
        second.id, reason="evaluation passed", idempotency_key="promote-2"
    )

    assert (first.version, second.version) == (1, 2)
    assert repository.get_promoted_policy().id == second.id
    assert repeated.id == second.id and changed is False
    with pytest.raises(IntegrityError), repository.transaction() as database:
        database.execute(
            text("UPDATE policy_versions SET promoted = 1 WHERE id = :id"),
            {"id": first.id},
        )


def test_learning_json_does_not_persist_sensitive_payload_fields(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    repository = _repository(database)
    decision = PolicyDecision(task_id="task-1", selected_action=PolicyAction.STOP_SAFELY)
    repository.save_decision(decision, decision_sequence=1)
    experience = _experience(decision, reward=-2.0, key="terminal-safe")
    repository.save_experience(experience, decision_sequence=1)

    connection = create_engine(f"sqlite:///{database}").connect()
    stored = " ".join(
        str(row[0])
        for table in ("policy_decisions", "experiences", "learning_events")
        for row in connection.execute(text(f"SELECT payload_json FROM {table}"))
    ).lower()
    assert not {
        "messages",
        "tool_arguments",
        "tool_output",
        "file_contents",
        "auth_error",
        "secret",
    } & set(stored.replace('"', "").split())


def _upgrade_in_clean_process(database: Path, revision: str) -> None:
    script = (
        "from pathlib import Path; from alembic import command; "
        "from alembic.config import Config; import sys; "
        "config=Config(); config.set_main_option('script_location', sys.argv[2]); "
        "config.set_main_option('sqlalchemy.url', f'sqlite:///{Path(sys.argv[1]).as_posix()}'); "
        "command.upgrade(config, sys.argv[3])"
    )
    subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(database),
            str(Path("src/mllminal/migrations").resolve()),
            revision,
        ],
        check=True,
    )


def _alembic_config(database: Path) -> Config:
    config = Config()
    config.set_main_option("script_location", str(Path("src/mllminal/migrations").resolve()))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database.as_posix()}")
    return config


def test_migration_0003_preserves_existing_provider_and_session_data(tmp_path: Path) -> None:
    database = tmp_path / "migration.db"
    config = _alembic_config(database)
    _upgrade_in_clean_process(database, "0002_provider_metadata")
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO sessions (id, workspace_root, created_at) "
                "VALUES ('s1', '/tmp', CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO tasks "
                "(id, session_id, title, goal, state, origin_interface, created_at, updated_at) "
                "VALUES ('t1', 's1', 'title', 'goal', 'CREATED', 'api', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO provider_responses (id, task_id, metadata_json) "
                "VALUES ('p1', 't1', '{}')"
            )
        )

    command.upgrade(config, "0003_learning_foundation")

    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT workspace_root FROM sessions WHERE id='s1'")) == "/tmp"
        )
        assert (
            connection.scalar(text("SELECT metadata_json FROM provider_responses WHERE id='p1'"))
            == "{}"
        )
    assert "learning_settings" in inspect(engine).get_table_names()

    command.downgrade(config, "0002_provider_metadata")
    tables = set(inspect(engine).get_table_names())
    assert {"sessions", "tasks", "provider_responses"} <= tables
    assert "learning_settings" not in tables


def test_repository_crud_counts_and_idempotent_rollback(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "state.db")
    run = TrainingRun()
    repository.save_training_run(run)
    first = repository.create_policy_version(checkpoint_sha256="a" * 64)
    second = repository.create_policy_version(checkpoint_sha256="b" * 64)
    report = EvaluationReport(
        training_run_id=run.id,
        candidate_policy_id=second.id,
        sample_count=10,
        mean_reward=1.0,
        safe_action_rate=1.0,
        passed=True,
    )
    repository.save_evaluation_report(report)
    promotion = PromotionDecision(
        policy_version_id=second.id,
        evaluation_report_id=report.id,
        outcome=PromotionOutcome.APPROVED,
        reason="passed",
    )
    repository.save_promotion_record(promotion)
    rollback = RollbackRecord(
        from_policy_version_id=second.id,
        to_policy_version_id=first.id,
        reason="regression",
    )
    repository.save_rollback_record(rollback)

    assert repository.get_training_run(run.id) == run
    assert repository.count_training_runs() == 1
    assert repository.get_evaluation_report(report.id) == report
    assert repository.count_evaluation_reports() == 1
    assert repository.get_policy_version(first.id) == first
    assert repository.count_policy_versions() == 3
    assert repository.get_promotion_record(promotion.id) == promotion
    assert repository.count_promotion_records() == 1
    assert repository.get_rollback_record(rollback.id) == rollback
    assert repository.count_rollback_records() == 1

    repository.promote_policy(second.id, reason="passed", idempotency_key="promote-second")
    applied, changed = repository.rollback_policy(
        first.id, reason="regression", idempotency_key="rollback-first"
    )
    repeated, repeated_changed = repository.rollback_policy(
        first.id, reason="regression", idempotency_key="rollback-first"
    )

    assert applied.to_policy_version_id == first.id
    assert changed is True
    assert repeated.id == applied.id and repeated_changed is False
    assert repository.get_promoted_policy().id == first.id


def test_offline_candidate_provenance_survives_restart(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    repository = _repository(database)
    candidate = repository.create_policy_version(
        checkpoint_sha256="a" * 64,
        policy_domain=PolicyDomain.SUGGESTION_RANKING,
        replay_snapshot_id="snapshot-1",
        feature_schema_version="training_features_v1",
        training_config={"hidden_size": 8, "epochs": 2},
        training_seed=7,
        parent_policy_id="policy_v0",
    )
    evaluated = repository.update_offline_candidate(
        candidate.id,
        lifecycle=PolicyLifecycle.EVALUATED,
        evaluation_metrics={"candidate_accuracy": 0.75},
        baseline_metrics={"heuristic_accuracy": 0.5},
        safety_checks={"privacy_approved": True, "no_safety_regression": True},
    )

    restarted = LearningRepository(database)
    restored = restarted.get_policy_version(candidate.id)

    assert restored == evaluated
    assert restored.policy_domain is PolicyDomain.SUGGESTION_RANKING
    assert restored.replay_snapshot_id == "snapshot-1"
    assert restored.feature_schema_version == "training_features_v1"
    assert restored.training_config == {"hidden_size": 8, "epochs": 2}
    assert restored.training_seed == 7
    assert restored.evaluation_metrics["candidate_accuracy"] == 0.75
    assert restored.baseline_metrics["heuristic_accuracy"] == 0.5
    assert restored.safety_checks["privacy_approved"] is True
    assert restored.lifecycle is PolicyLifecycle.EVALUATED
