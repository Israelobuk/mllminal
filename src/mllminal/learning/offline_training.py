"""Small deterministic CPU models for advisory policy candidates."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import torch
from torch import Tensor, nn
from torch.nn import functional as functional

from mllminal.learning.contracts import TrainingExperience
from mllminal.learning.offline_features import TrainingFeatureEncoder


@dataclass(frozen=True)
class OfflineTrainingConfig:
    seed: int = 42
    epochs: int = 20
    hidden_size: int = 16
    learning_rate: float = 1e-2
    cpu_threads: int = 1


class OfflinePolicyNetwork(nn.Module):
    def __init__(self, input_dimension: int, output_dimension: int, hidden_size: int) -> None:
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(input_dimension, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, output_dimension),
            nn.Sigmoid(),
        )

    def forward(self, features: Tensor) -> Tensor:
        return cast(Tensor, self.layers(features))


@dataclass(frozen=True)
class OfflineCandidateModel:
    network: OfflinePolicyNetwork
    action_labels: tuple[str, ...]
    feature_schema_version: str
    cpu: bool = True


@dataclass(frozen=True)
class OfflineTrainingResult:
    model: OfflineCandidateModel
    action_labels: tuple[str, ...]
    losses: tuple[float, ...]


def train_offline_candidate(
    experiences: list[TrainingExperience],
    encoder: TrainingFeatureEncoder,
    config: OfflineTrainingConfig,
) -> OfflineTrainingResult:
    """Train a bounded, CPU-only candidate without online device interaction."""

    samples = [
        experience
        for experience in experiences
        if experience.eligible_for_training
        and experience.privacy_approved
        and experience.selected_action is not None
    ]
    if len(samples) < 2:
        raise ValueError("at least two eligible experiences are required")
    actions = tuple(
        sorted({experience.selected_action for experience in samples if experience.selected_action})
    )
    if len(actions) < 2:
        raise ValueError("at least two candidate actions are required")

    torch.set_num_threads(config.cpu_threads)
    torch.manual_seed(config.seed)
    torch.use_deterministic_algorithms(True)
    network = OfflinePolicyNetwork(encoder.dimension, len(actions), config.hidden_size).cpu()
    features = torch.tensor([encoder.encode(sample) for sample in samples], dtype=torch.float32)
    labels = torch.tensor([actions.index(sample.selected_action or "") for sample in samples])
    targets = functional.one_hot(labels, num_classes=len(actions)).to(dtype=torch.float32)
    weights = torch.tensor(
        [max(sample.reward or 0.0, 0.0) for sample in samples], dtype=torch.float32
    )
    optimizer = torch.optim.Adam(network.parameters(), lr=config.learning_rate)
    losses: list[float] = []

    network.train()
    for _ in range(config.epochs):
        optimizer.zero_grad()
        per_row = functional.binary_cross_entropy(
            network(features), targets, reduction="none"
        ).mean(dim=1)
        normalizer = weights.sum().clamp_min(1.0)
        loss = (per_row * weights).sum() / normalizer
        loss.backward()  # type: ignore[no-untyped-call]
        optimizer.step()
        losses.append(float(loss.detach().item()))
    network.eval()
    model = OfflineCandidateModel(network, actions, encoder.schema_version)
    return OfflineTrainingResult(model=model, action_labels=actions, losses=tuple(losses))


class OfflineCandidateCheckpointError(ValueError):
    """Raised when a local offline candidate artifact is invalid or incompatible."""


def save_offline_candidate(model: OfflineCandidateModel, path: Path) -> str:
    """Save one CPU candidate with schema metadata and return its SHA-256 digest."""

    input_layer = model.network.layers[0]
    hidden_layer = model.network.layers[2]
    if not isinstance(input_layer, nn.Linear) or not isinstance(hidden_layer, nn.Linear):
        raise OfflineCandidateCheckpointError("candidate network architecture is unsupported")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "artifact_type": "offline_policy_network_v1",
        "feature_schema_version": model.feature_schema_version,
        "action_labels": model.action_labels,
        "input_dimension": input_layer.in_features,
        "hidden_size": input_layer.out_features,
        "output_dimension": hidden_layer.out_features,
        "state_dict": model.network.state_dict(),
    }
    torch.save(payload, path)
    return sha256(path.read_bytes()).hexdigest()


def load_offline_candidate(path: Path) -> OfflineCandidateModel:
    """Load a local CPU candidate only when its metadata and weights are compatible."""

    try:
        payload = torch.load(path, map_location="cpu", weights_only=True)
    except (OSError, RuntimeError, ValueError) as error:
        raise OfflineCandidateCheckpointError("candidate artifact could not be loaded") from error
    if not isinstance(payload, dict) or payload.get("artifact_type") != "offline_policy_network_v1":
        raise OfflineCandidateCheckpointError("candidate artifact metadata is invalid")
    action_labels = payload.get("action_labels")
    input_dimension = payload.get("input_dimension")
    hidden_size = payload.get("hidden_size")
    output_dimension = payload.get("output_dimension")
    feature_schema_version = payload.get("feature_schema_version")
    state_dict = payload.get("state_dict")
    if (
        not isinstance(action_labels, tuple)
        or not all(isinstance(label, str) for label in action_labels)
        or not isinstance(input_dimension, int)
        or not isinstance(hidden_size, int)
        or not isinstance(output_dimension, int)
        or not isinstance(feature_schema_version, str)
        or not isinstance(state_dict, dict)
        or output_dimension != len(action_labels)
    ):
        raise OfflineCandidateCheckpointError("candidate artifact fields are invalid")
    network = OfflinePolicyNetwork(input_dimension, output_dimension, hidden_size).cpu()
    try:
        network.load_state_dict(state_dict, strict=True)
    except (RuntimeError, TypeError) as error:
        raise OfflineCandidateCheckpointError(
            "candidate artifact weights are incompatible"
        ) from error
    network.eval()
    return OfflineCandidateModel(
        network=network,
        action_labels=action_labels,
        feature_schema_version=feature_schema_version,
    )
