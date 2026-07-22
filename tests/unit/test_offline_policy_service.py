from mllminal.learning.contracts import PolicyDomain, TrainingExperience
from mllminal.learning.offline_service import OfflinePolicyDataService
from mllminal.learning.replay import LearningRepository


def _experience(source_id: str) -> TrainingExperience:
    return TrainingExperience(
        policy_domain=PolicyDomain.SUGGESTION_RANKING,
        source_record_type="suggestion_feedback",
        source_record_id=source_id,
        context_features={"occurrence_count": 0.5},
        candidate_actions=("present", "defer"),
        selected_action="present",
        baseline_score=0.5,
        reward=1.0,
        reward_components={"feedback": 1.0},
        privacy_approved=True,
        eligible_for_training=True,
    )


def test_snapshot_service_persists_a_domain_specific_parquet_snapshot(tmp_path) -> None:
    repository = LearningRepository(tmp_path / "state.db")
    repository.initialize()
    for source_id in ("one", "two", "three"):
        repository.save_training_experience(_experience(source_id))

    snapshot = OfflinePolicyDataService(repository, tmp_path / "offline").snapshot(
        PolicyDomain.SUGGESTION_RANKING,
        seed=7,
    )

    assert snapshot.storage_path is not None
    assert repository.get_replay_snapshot(snapshot.snapshot_id) == snapshot


def test_training_service_persists_an_unpromoted_domain_candidate(tmp_path) -> None:
    from mllminal.learning.contracts import PolicyLifecycle, RunStatus
    from mllminal.learning.offline_service import OfflinePolicyTrainingService
    from mllminal.learning.offline_training import OfflineTrainingConfig

    repository = LearningRepository(tmp_path / "state.db")
    repository.initialize()
    for source_id, action in (
        ("one", "present"),
        ("two", "present"),
        ("three", "defer"),
        ("four", "defer"),
    ):
        repository.save_training_experience(
            _experience(source_id).model_copy(update={"selected_action": action})
        )

    result = OfflinePolicyTrainingService(repository, tmp_path / "offline").train(
        PolicyDomain.SUGGESTION_RANKING,
        OfflineTrainingConfig(seed=7, epochs=2, hidden_size=8),
        timeout_seconds=30,
    )

    assert result.worker.status == "COMPLETED"
    assert result.training_run.status is RunStatus.COMPLETED
    assert result.candidate.lifecycle is PolicyLifecycle.TRAINED
    assert result.candidate.replay_snapshot_id == result.snapshot.snapshot_id
    assert result.candidate.checkpoint_sha256 == result.worker.checkpoint_sha256
    assert repository.get_policy_version(result.candidate.id) == result.candidate
