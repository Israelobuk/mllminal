from pathlib import Path

import torch

from mllminal.learning.contracts import PolicyDomain, TrainingExperience
from mllminal.learning.offline_features import TrainingFeatureEncoder
from mllminal.learning.offline_training import (
    OfflineTrainingConfig,
    load_offline_candidate,
    save_offline_candidate,
    train_offline_candidate,
)


def _experience(source_id: str, occurrence_count: float, action: str) -> TrainingExperience:
    return TrainingExperience(
        policy_domain=PolicyDomain.SUGGESTION_RANKING,
        source_record_type="suggestion_feedback",
        source_record_id=source_id,
        context_features={"occurrence_count": occurrence_count},
        candidate_actions=("present", "defer"),
        selected_action=action,
        baseline_score=0.5,
        reward=1.0,
        reward_components={"accepted": 1.0},
        privacy_approved=True,
        eligible_for_training=True,
    )


def test_small_cpu_candidate_training_is_deterministic() -> None:
    experiences = [
        _experience("one", 0.9, "present"),
        _experience("two", 0.8, "present"),
        _experience("three", 0.1, "defer"),
        _experience("four", 0.2, "defer"),
    ]
    encoder = TrainingFeatureEncoder.for_domain(PolicyDomain.SUGGESTION_RANKING)
    config = OfflineTrainingConfig(seed=11, epochs=8, hidden_size=8)

    first = train_offline_candidate(experiences, encoder, config)
    second = train_offline_candidate(experiences, encoder, config)

    assert first.action_labels == ("defer", "present")
    assert first.model.cpu is True
    assert all(
        torch.equal(first.model.network.state_dict()[name], second.model.network.state_dict()[name])
        for name in first.model.network.state_dict()
    )


def test_offline_candidate_checkpoint_round_trips_with_digest(tmp_path: Path) -> None:
    experiences = [
        _experience("one", 0.9, "present"),
        _experience("two", 0.8, "present"),
        _experience("three", 0.1, "defer"),
        _experience("four", 0.2, "defer"),
    ]
    encoder = TrainingFeatureEncoder.for_domain(PolicyDomain.SUGGESTION_RANKING)
    trained = train_offline_candidate(
        experiences,
        encoder,
        OfflineTrainingConfig(seed=11, epochs=2, hidden_size=8),
    )

    checkpoint = tmp_path / "candidate.pt"
    digest = save_offline_candidate(trained.model, checkpoint)
    restored = load_offline_candidate(checkpoint)

    assert len(digest) == 64
    assert restored.action_labels == trained.action_labels
    assert restored.feature_schema_version == encoder.schema_version
    assert all(
        torch.equal(restored.network.state_dict()[name], trained.model.network.state_dict()[name])
        for name in trained.model.network.state_dict()
    )
