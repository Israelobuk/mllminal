from mllminal.learning.contracts import PolicyDomain, TrainingExperience
from mllminal.learning.offline_features import TrainingFeatureEncoder
from mllminal.learning.offline_training import OfflineTrainingConfig
from mllminal.learning.offline_worker import run_isolated_training


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


def test_training_runs_in_a_short_lived_isolated_worker() -> None:
    result = run_isolated_training(
        [
            _experience("one", 0.9, "present"),
            _experience("two", 0.8, "present"),
            _experience("three", 0.1, "defer"),
            _experience("four", 0.2, "defer"),
        ],
        TrainingFeatureEncoder.for_domain(PolicyDomain.SUGGESTION_RANKING),
        OfflineTrainingConfig(seed=11, epochs=2, hidden_size=8),
        timeout_seconds=30,
    )

    assert result.status == "COMPLETED"
    assert result.action_labels == ("defer", "present")
    assert result.worker_pid is not None
