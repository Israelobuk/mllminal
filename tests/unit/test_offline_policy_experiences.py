from mllminal.learning.contracts import PolicyDomain, TrainingExperience
from mllminal.learning.replay import LearningRepository


def _experience() -> TrainingExperience:
    return TrainingExperience(
        policy_domain=PolicyDomain.SUGGESTION_RANKING,
        source_record_type="suggestion_feedback",
        source_record_id="feedback-1",
        context_features={"occurrence_count": 6.0},
        candidate_actions=("present", "defer"),
        selected_action="present",
        baseline_score=0.7,
        reward=1.0,
        reward_components={"accepted": 1.0},
        privacy_approved=True,
        eligible_for_training=True,
    )


def test_training_experience_is_durable_and_idempotent_by_source(tmp_path) -> None:
    repository = LearningRepository(tmp_path / "learning.db")
    repository.initialize()

    first, created = repository.save_training_experience(_experience())
    second, repeated = repository.save_training_experience(_experience())

    assert created is True
    assert repeated is False
    assert second.experience_id == first.experience_id
    assert repository.list_training_experiences(PolicyDomain.SUGGESTION_RANKING) == [first]
