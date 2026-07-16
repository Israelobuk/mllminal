from pathlib import Path

import torch

from mllminal.learning.contracts import PolicyAction, ReplaySample
from mllminal.learning.policy import ActionPolicy
from mllminal.learning.training import TrainingConfig, train_policy


def _sample(action: PolicyAction, reward: float, value: float) -> ReplaySample:
    return ReplaySample(
        experience_id=f"019b0000-0000-7000-8000-{int(value):012d}",
        features=(value,) + (0.0,) * 14,
        action=action,
        reward=reward,
    )


def test_seeded_training_is_deterministic_and_learns_rewarded_action(tmp_path: Path) -> None:
    samples = [
        *[_sample(PolicyAction.ANSWER_DIRECTLY, 5.0, float(i)) for i in range(24)],
        *[_sample(PolicyAction.RETRY, -5.0, float(i + 24)) for i in range(8)],
    ]
    config = TrainingConfig(seed=42, epochs=20, batch_size=32)

    first = train_policy(samples, config=config, checkpoint_dir=tmp_path / "first")
    second = train_policy(samples, config=config, checkpoint_dir=tmp_path / "second")

    assert first.train_indices == second.train_indices
    assert first.holdout_indices == second.holdout_indices
    assert first.losses == second.losses
    assert first.losses[-1] < first.losses[0]
    assert first.checkpoint_path.exists()
    for left, right in zip(
        first.policy.network.parameters(), second.policy.network.parameters(), strict=True
    ):
        assert torch.equal(left, right)


def test_negative_samples_use_unlikelihood_not_failed_action_imitation(tmp_path: Path) -> None:
    samples = [_sample(PolicyAction.RETRY, -4.0, float(i)) for i in range(16)]
    before = ActionPolicy(seed=42).recommend((1.0,) + (0.0,) * 14, (True,) * 9).scores[7]
    trained = train_policy(
        samples,
        config=TrainingConfig(seed=42, epochs=20, batch_size=16),
        checkpoint_dir=tmp_path,
    )
    after = trained.policy.recommend(
        (1.0,) + (0.0,) * 14, (True,) * 9, confidence_threshold=0.0
    ).scores[7]
    assert after < before
