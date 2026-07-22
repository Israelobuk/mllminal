"""Small deterministic CPU models for advisory policy candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

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
