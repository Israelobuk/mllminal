from mllminal.learning.contracts import PolicyDomain, TrainingExperience
from mllminal.learning.offline_evaluation import evaluate_offline_baselines
from mllminal.learning.offline_features import TrainingFeatureEncoder


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


def test_offline_baselines_include_deterministic_and_sklearn_metrics() -> None:
    metrics = evaluate_offline_baselines(
        [
            _experience("one", 0.9, "present"),
            _experience("two", 0.8, "present"),
            _experience("three", 0.1, "defer"),
            _experience("four", 0.2, "defer"),
        ],
        TrainingFeatureEncoder.for_domain(PolicyDomain.SUGGESTION_RANKING),
    )

    assert metrics.heuristic_accuracy >= 0.0
    assert metrics.sklearn_accuracy >= 0.0
    assert metrics.sample_count == 4
