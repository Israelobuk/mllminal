from pathlib import Path

import pytest

from mllminal.learning.contracts import PolicyLifecycle
from mllminal.learning.evaluation import EvaluationMetrics
from mllminal.learning.policy import ActionPolicy, save_checkpoint
from mllminal.learning.registry import PolicyRegistry, PromotionGateError
from mllminal.learning.replay import LearningRepository


def _repository(path: Path) -> LearningRepository:
    repository = LearningRepository(path)
    repository.initialize()
    return repository


def _metrics(*, eligible: bool) -> EvaluationMetrics:
    return EvaluationMetrics(
        action_accuracy=1.0,
        reward_weighted_accuracy=1.0 if eligible else 0.0,
        average_predicted_reward=1.0,
        raw_invalid_action_rate=0.0,
        safe_fallback_rate=0.0,
        regression_pass_rate=1.0,
        baseline_reward_weighted_accuracy=0.5,
        promotion_eligible=eligible,
        rejection_reasons=() if eligible else ("insufficient_improvement",),
    )


def test_registry_loads_candidate_promotes_explicitly_and_rolls_back(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "state.db")
    registry = PolicyRegistry(repository, tmp_path / "checkpoints")
    checkpoint = tmp_path / "candidate.pt"
    digest = save_checkpoint(ActionPolicy(seed=42), checkpoint, policy_version="policy_v1")
    candidate = registry.register_candidate(checkpoint, checkpoint_sha256=digest)

    assert repository.get_promoted_policy().name == "policy_v0"
    assert registry.load(candidate).policy_version == "policy_v1"

    promoted = registry.promote(
        candidate.id,
        _metrics(eligible=True),
        explicitly_approved=True,
        idempotency_key="promote-1",
    )
    assert promoted.lifecycle is PolicyLifecycle.ACTIVE
    assert repository.get_promoted_policy().id == candidate.id

    record = registry.rollback(
        "policy_v0", reason="operator rollback", idempotency_key="rollback-1"
    )
    assert record.from_policy_version_id == candidate.id
    assert repository.get_promoted_policy().name == "policy_v0"
    assert checkpoint.exists()


def test_failed_candidate_is_rejected_and_cannot_promote(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "state.db")
    registry = PolicyRegistry(repository, tmp_path / "checkpoints")
    checkpoint = tmp_path / "candidate.pt"
    digest = save_checkpoint(ActionPolicy(seed=42), checkpoint, policy_version="policy_v1")
    candidate = registry.register_candidate(checkpoint, checkpoint_sha256=digest)

    with pytest.raises(PromotionGateError, match="not promotion eligible"):
        registry.promote(
            candidate.id,
            _metrics(eligible=False),
            explicitly_approved=True,
            idempotency_key="reject-1",
        )
    assert repository.get_policy_version(candidate.id).lifecycle is PolicyLifecycle.REJECTED


def test_promotion_requires_explicit_approval(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "state.db")
    registry = PolicyRegistry(repository, tmp_path / "checkpoints")
    checkpoint = tmp_path / "candidate.pt"
    digest = save_checkpoint(ActionPolicy(seed=42), checkpoint, policy_version="policy_v1")
    candidate = registry.register_candidate(checkpoint, checkpoint_sha256=digest)
    with pytest.raises(PromotionGateError, match="explicit approval"):
        registry.promote(
            candidate.id,
            _metrics(eligible=True),
            explicitly_approved=False,
            idempotency_key="no-approval",
        )
