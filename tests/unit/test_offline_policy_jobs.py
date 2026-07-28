import time
from pathlib import Path

from mllminal.learning.contracts import PolicyDomain, TrainingExperience
from mllminal.learning.offline_jobs import OfflineTrainingJobManager
from mllminal.learning.offline_training import OfflineTrainingConfig
from mllminal.learning.replay import LearningRepository


def _experience(source_id: str, value: float, action: str) -> TrainingExperience:
    return TrainingExperience(
        policy_domain=PolicyDomain.SUGGESTION_RANKING,
        source_record_type="suggestion_feedback",
        source_record_id=source_id,
        context_features={"occurrence_count": value},
        candidate_actions=("present", "defer"),
        selected_action=action,
        baseline_score=0.5,
        reward=1.0,
        reward_components={"accepted": 1.0},
        privacy_approved=True,
        eligible_for_training=True,
    )


def _repository(path: Path) -> LearningRepository:
    repository = LearningRepository(path)
    repository.initialize()
    for source_id, value, action in (
        ("one", 0.9, "present"),
        ("two", 0.8, "present"),
        ("three", 0.1, "defer"),
        ("four", 0.2, "defer"),
    ):
        repository.save_training_experience(_experience(source_id, value, action))
    return repository


def _wait_for_terminal(manager: OfflineTrainingJobManager, job_id: str) -> object:
    for _ in range(200):
        status = manager.status(job_id)
        if status.status in {"COMPLETED", "FAILED", "CANCELLED"}:
            return status
        time.sleep(0.05)
    raise AssertionError("offline job did not reach a terminal state")


def test_offline_job_manager_reports_durable_completion(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "learning.db")
    manager = OfflineTrainingJobManager(repository, tmp_path / "offline")
    try:
        job = manager.submit(
            PolicyDomain.SUGGESTION_RANKING,
            OfflineTrainingConfig(seed=11, epochs=2, hidden_size=8),
            timeout_seconds=30,
        )
        completed = _wait_for_terminal(manager, job.job_id)
        assert completed.status == "COMPLETED"
        assert completed.training_run_id is not None
        assert completed.candidate_policy_id is not None
        assert any(
            event.event_type == "learning.offline_job.completed"
            for event in repository.list_events()
        )
    finally:
        manager.close()


def test_offline_job_manager_propagates_cancellation(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "learning.db")
    manager = OfflineTrainingJobManager(repository, tmp_path / "offline")
    try:
        job = manager.submit(
            PolicyDomain.SUGGESTION_RANKING,
            OfflineTrainingConfig(seed=11, epochs=5000, hidden_size=8),
            timeout_seconds=30,
        )
        manager.cancel(job.job_id)
        cancelled = _wait_for_terminal(manager, job.job_id)
        assert cancelled.status == "CANCELLED"
        assert cancelled.failure_reason == "training_cancelled"
    finally:
        manager.close()
