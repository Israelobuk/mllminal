import pytest

from mllminal.learning.contracts import PolicyDomain, TrainingExperience
from mllminal.learning.offline_features import TrainingFeatureEncoder


def _experience(features: dict[str, float]) -> TrainingExperience:
    return TrainingExperience(
        policy_domain=PolicyDomain.SUGGESTION_RANKING,
        source_record_type="suggestion_feedback",
        source_record_id="feedback-1",
        context_features=features,
        candidate_actions=("present", "defer"),
        selected_action="present",
        baseline_score=0.7,
        reward=1.0,
        reward_components={"accepted": 1.0},
        privacy_approved=True,
        eligible_for_training=True,
    )


def test_suggestion_feature_encoder_is_versioned_and_deterministic() -> None:
    encoder = TrainingFeatureEncoder.for_domain(PolicyDomain.SUGGESTION_RANKING)

    first = encoder.encode(_experience({"occurrence_count": 6.0, "rejection_rate": 0.2}))
    second = encoder.encode(_experience({"rejection_rate": 0.2, "occurrence_count": 6.0}))

    assert first == second
    assert len(first) == encoder.dimension
    assert all(-1.0 <= value <= 1.0 for value in first)


def test_feature_encoder_rejects_sensitive_or_unknown_feature_names() -> None:
    encoder = TrainingFeatureEncoder.for_domain(PolicyDomain.SUGGESTION_RANKING)

    with pytest.raises(ValueError, match="not allowed"):
        encoder.encode(_experience({"password": 1.0}))
