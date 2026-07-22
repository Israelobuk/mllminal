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
