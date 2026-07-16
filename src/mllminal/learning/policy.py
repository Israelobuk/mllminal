"""Deterministic, safety-masked PyTorch action policy."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
from torch import Tensor, nn

from mllminal.learning.contracts import (
    ACTION_DIM,
    ACTION_SPACE_VERSION,
    DEFAULT_CONFIDENCE,
    FEATURE_DIM,
    FEATURE_VERSION,
    PolicyAction,
)


class PolicyCheckpointError(ValueError):
    """Raised when a checkpoint cannot be used safely."""


class PolicyNetwork(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(FEATURE_DIM, 64),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(32, ACTION_DIM),
        )

    def forward(self, features: Tensor) -> Tensor:
        return self.layers(features)  # type: ignore[no-any-return]


@dataclass(frozen=True)
class PolicyInference:
    action: PolicyAction
    confidence: float
    scores: tuple[float, ...]
    used_safe_fallback: bool = False
    fallback_reason: str | None = None


class ActionPolicy:
    """Small CPU-only policy with deterministic inference and safety masks."""

    def __init__(self, *, seed: int = 42, network: PolicyNetwork | None = None) -> None:
        torch.manual_seed(seed)
        self.network = network or PolicyNetwork()
        self.network.cpu()
        self.network.eval()

    def recommend(
        self,
        features: tuple[float, ...],
        action_mask: tuple[bool, ...],
        *,
        confidence_threshold: float = DEFAULT_CONFIDENCE,
        fallback_action: PolicyAction = PolicyAction.STOP_SAFELY,
    ) -> PolicyInference:
        if len(features) != FEATURE_DIM:
            raise ValueError(f"features must contain {FEATURE_DIM} values")
        if len(action_mask) != ACTION_DIM:
            raise ValueError(f"action mask must contain {ACTION_DIM} values")
        if not any(action_mask):
            return PolicyInference(
                action=PolicyAction.STOP_SAFELY,
                confidence=1.0,
                scores=(0.0,) * ACTION_DIM,
                used_safe_fallback=True,
                fallback_reason="all_actions_masked",
            )

        with torch.inference_mode():
            logits = self.network(torch.tensor([features], dtype=torch.float32))[0]
            mask = torch.tensor(action_mask, dtype=torch.bool)
            masked_logits = logits.masked_fill(~mask, float("-inf"))
            probabilities = torch.softmax(masked_logits, dim=0)
            confidence_tensor, action_index_tensor = torch.max(probabilities, dim=0)
        confidence = float(confidence_tensor.item())
        scores = tuple(float(value) for value in probabilities.tolist())
        if confidence < confidence_threshold:
            safe_fallback = fallback_action
            if not action_mask[list(PolicyAction).index(safe_fallback)]:
                safe_fallback = PolicyAction.STOP_SAFELY
            return PolicyInference(
                action=safe_fallback,
                confidence=confidence,
                scores=scores,
                used_safe_fallback=True,
                fallback_reason="insufficient_confidence",
            )
        return PolicyInference(
            action=list(PolicyAction)[int(action_index_tensor.item())],
            confidence=confidence,
            scores=scores,
        )


@dataclass(frozen=True)
class LoadedPolicy:
    policy: ActionPolicy
    policy_version: str


def save_checkpoint(policy: ActionPolicy, path: Path, *, policy_version: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "feature_version": FEATURE_VERSION,
        "action_space_version": ACTION_SPACE_VERSION,
        "feature_dim": FEATURE_DIM,
        "action_dim": ACTION_DIM,
        "policy_version": policy_version,
        "state_dict": policy.network.state_dict(),
    }
    torch.save(payload, path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_checkpoint(path: Path) -> LoadedPolicy:
    try:
        payload = torch.load(path, map_location="cpu", weights_only=True)
    except (OSError, RuntimeError, ValueError) as error:
        raise PolicyCheckpointError("checkpoint could not be loaded") from error
    if not isinstance(payload, dict):
        raise PolicyCheckpointError("checkpoint payload must be a mapping")
    if payload.get("feature_version") != FEATURE_VERSION:
        raise PolicyCheckpointError("incompatible feature version")
    if payload.get("action_space_version") != ACTION_SPACE_VERSION:
        raise PolicyCheckpointError("incompatible action-space version")
    if payload.get("feature_dim") != FEATURE_DIM or payload.get("action_dim") != ACTION_DIM:
        raise PolicyCheckpointError("incompatible policy dimensions")
    policy_version = payload.get("policy_version")
    state_dict = payload.get("state_dict")
    if not isinstance(policy_version, str) or not isinstance(state_dict, dict):
        raise PolicyCheckpointError("checkpoint metadata is malformed")
    network = PolicyNetwork()
    try:
        network.load_state_dict(state_dict, strict=True)
    except (RuntimeError, TypeError) as error:
        raise PolicyCheckpointError("checkpoint weights are incompatible") from error
    return LoadedPolicy(policy=ActionPolicy(network=network), policy_version=policy_version)
