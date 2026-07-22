import pytest

from mllminal.learning.contracts import PolicyDomain, TrainingExperience
from mllminal.learning.offline import build_replay_snapshot


def _experience(source_id: str) -> TrainingExperience:
    return TrainingExperience(
        policy_domain=PolicyDomain.SUGGESTION_RANKING,
        source_record_type="suggestion_feedback",
        source_record_id=source_id,
        context_features={"occurrence_count": 6.0},
        candidate_actions=("present", "defer"),
        selected_action="present",
        baseline_score=0.7,
        reward=1.0,
        reward_components={"accepted": 1.0},
        privacy_approved=True,
        eligible_for_training=True,
    )


def test_replay_snapshot_digest_is_stable_for_the_same_evidence_and_seed() -> None:
    experiences = [_experience("feedback-2"), _experience("feedback-1")]

    first = build_replay_snapshot(
        experiences, policy_domain=PolicyDomain.SUGGESTION_RANKING, seed=7
    )
    second = build_replay_snapshot(
        list(reversed(experiences)), policy_domain=PolicyDomain.SUGGESTION_RANKING, seed=7
    )

    assert first.dataset_digest == second.dataset_digest
    assert first.included_experience_ids == second.included_experience_ids
    assert first.experience_count == 2


def test_replay_snapshot_is_durable_and_cannot_be_mutated(tmp_path) -> None:
    from mllminal.learning.replay import LearningRepository

    repository = LearningRepository(tmp_path / "learning.db")
    repository.initialize()
    snapshot = build_replay_snapshot(
        [_experience("feedback-1")], policy_domain=PolicyDomain.SUGGESTION_RANKING, seed=7
    )

    repository.save_replay_snapshot(snapshot)

    assert repository.get_replay_snapshot(snapshot.snapshot_id) == snapshot
    with pytest.raises(ValueError, match="immutable"):
        repository.save_replay_snapshot(snapshot.model_copy(update={"dataset_digest": "0" * 64}))
