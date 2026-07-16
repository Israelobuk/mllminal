from pathlib import Path

import pytest
import torch

from mllminal.learning.contracts import PolicyAction
from mllminal.learning.policy import (
    ActionPolicy,
    PolicyCheckpointError,
    PolicyInference,
    load_checkpoint,
    save_checkpoint,
)


def test_policy_shape_and_deterministic_inference() -> None:
    policy = ActionPolicy(seed=42)
    assert policy.network(torch.zeros(2, 15)).shape == (2, 9)

    mask = tuple(action is PolicyAction.ANSWER_DIRECTLY for action in PolicyAction)
    first = policy.recommend((0.0,) * 15, mask)
    second = policy.recommend((0.0,) * 15, mask)

    assert first == second
    assert first.action is PolicyAction.ANSWER_DIRECTLY
    assert first.confidence == 1.0
    assert not first.used_safe_fallback


def test_all_masked_stops_safely() -> None:
    result = ActionPolicy(seed=42).recommend((0.0,) * 15, (False,) * 9)
    assert result == PolicyInference(
        action=PolicyAction.STOP_SAFELY,
        confidence=1.0,
        scores=(0.0,) * 9,
        used_safe_fallback=True,
        fallback_reason="all_actions_masked",
    )


def test_low_confidence_uses_deterministic_fallback() -> None:
    policy = ActionPolicy(seed=42)
    result = policy.recommend(
        (0.0,) * 15,
        (True,) * 9,
        confidence_threshold=1.0,
        fallback_action=PolicyAction.ASK_USER,
    )
    assert result.action is PolicyAction.ASK_USER
    assert result.used_safe_fallback
    assert result.fallback_reason == "insufficient_confidence"


def test_checkpoint_round_trip_and_version_validation(tmp_path: Path) -> None:
    path = tmp_path / "policy.pt"
    original = ActionPolicy(seed=7)
    digest = save_checkpoint(original, path, policy_version="policy_v1")
    loaded = load_checkpoint(path)

    assert len(digest) == 64
    assert loaded.policy_version == "policy_v1"
    assert loaded.policy.recommend((1.0,) * 15, (True,) * 9) == original.recommend(
        (1.0,) * 15, (True,) * 9
    )

    payload = torch.load(path, weights_only=True)
    payload["feature_version"] = "features_v2"
    torch.save(payload, path)
    with pytest.raises(PolicyCheckpointError, match="feature version"):
        load_checkpoint(path)
