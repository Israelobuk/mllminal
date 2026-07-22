from mllminal.learning.contracts import PolicyDomain, TrainingExperience
from mllminal.learning.offline_evaluation import evaluate_offline_candidate
from mllminal.learning.offline_features import TrainingFeatureEncoder
from mllminal.learning.offline_splits import split_training_experiences
from mllminal.learning.offline_training import OfflineTrainingConfig, train_offline_candidate


def _experience(source_id: str, value: float, action: str) -> TrainingExperience:
    return TrainingExperience(
        policy_domain=PolicyDomain.SUGGESTION_RANKING,
        source_record_type="workflow_episode",
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


def test_candidate_metrics_score_only_the_held_out_partition() -> None:
    experiences = [
        _experience(f"episode-{index}", index / 12, "present" if index % 2 else "defer")
        for index in range(1, 13)
    ]
    encoder = TrainingFeatureEncoder.for_domain(PolicyDomain.SUGGESTION_RANKING)
    split = split_training_experiences(experiences, seed=7)
    trained = train_offline_candidate(
        list(split.train),
        encoder,
        OfflineTrainingConfig(seed=7, epochs=2, hidden_size=8),
    )

    metrics = evaluate_offline_candidate(trained.model, split, encoder)

    assert metrics.sample_count == len(split.test)
    assert metrics.evaluated_source_ids
    assert set(metrics.evaluated_source_ids).isdisjoint(metrics.training_source_ids)
    assert 0.0 <= metrics.accuracy <= 1.0
