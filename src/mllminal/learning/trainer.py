"""Deterministic CPU-only offline training for candidate action policies."""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass

import torch
from torch import Tensor
from torch.nn import functional as functional

from mllminal.learning.contracts import PolicyAction, ReplaySample
from mllminal.learning.policy import ActionPolicy


@dataclass(frozen=True)
class CandidateTrainingConfig:
    seed: int = 42
    epochs: int = 20
    learning_rate: float = 1e-3
    batch_size: int = 32
    train_fraction: float = 0.8
    maximum_reward_weight: float = 4.0


@dataclass(frozen=True)
class CandidateTrainingResult:
    policy: ActionPolicy
    losses: tuple[float, ...]
    train_indices: tuple[int, ...]
    validation_indices: tuple[int, ...]


def deterministic_split(
    size: int, *, seed: int, train_fraction: float
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Return a reproducible non-empty training split whenever samples exist."""
    if size < 1:
        raise ValueError("at least one replay sample is required")
    if not 0.0 < train_fraction <= 1.0:
        raise ValueError("train_fraction must be within (0, 1]")
    indices = list(range(size))
    random.Random(seed).shuffle(indices)
    training_size = max(1, int(size * train_fraction))
    if size > 1:
        training_size = min(training_size, size - 1)
    return tuple(indices[:training_size]), tuple(indices[training_size:])


def reward_weights(rewards: Tensor, *, maximum: float = 4.0) -> Tensor:
    """Bound rewards to safe, non-negative sample weights."""
    if maximum <= 0:
        raise ValueError("maximum reward weight must be positive")
    return rewards.clamp(min=0.0, max=maximum)


def reward_weighted_cross_entropy(
    logits: Tensor, actions: Tensor, rewards: Tensor, *, maximum_weight: float = 4.0
) -> Tensor:
    """Offline imitation loss weighted only by bounded positive verified rewards."""
    per_sample = functional.cross_entropy(logits, actions, reduction="none")
    weights = reward_weights(rewards, maximum=maximum_weight)
    normalizer = weights.sum()
    if float(normalizer.item()) == 0.0:
        return (per_sample * weights).mean()
    return (per_sample * weights).sum() / normalizer


def train_candidate(
    samples: list[ReplaySample],
    config: CandidateTrainingConfig,
    *,
    initial_policy: ActionPolicy | None = None,
) -> CandidateTrainingResult:
    """Train one CPU candidate using no online environment interaction."""
    if not samples:
        raise ValueError("at least one replay sample is required")

    random.seed(config.seed)
    torch.manual_seed(config.seed)
    torch.use_deterministic_algorithms(True)
    policy = ActionPolicy(seed=config.seed)
    if initial_policy is not None:
        policy.network.load_state_dict(copy.deepcopy(initial_policy.network.state_dict()))
    policy.network.cpu()
    policy.network.train()

    train_indices, validation_indices = deterministic_split(
        len(samples), seed=config.seed, train_fraction=config.train_fraction
    )
    features = torch.tensor([sample.features for sample in samples], dtype=torch.float32)
    actions = torch.tensor(
        [list(PolicyAction).index(sample.action) for sample in samples], dtype=torch.long
    )
    rewards = torch.tensor([sample.reward for sample in samples], dtype=torch.float32)
    optimizer = torch.optim.Adam(policy.network.parameters(), lr=config.learning_rate)
    generator = torch.Generator(device="cpu").manual_seed(config.seed)
    losses: list[float] = []

    for _ in range(config.epochs):
        order = torch.randperm(len(train_indices), generator=generator).tolist()
        for offset in range(0, len(order), config.batch_size):
            batch_indices = [
                train_indices[item] for item in order[offset : offset + config.batch_size]
            ]
            index = torch.tensor(batch_indices, dtype=torch.long)
            optimizer.zero_grad()
            loss = reward_weighted_cross_entropy(
                policy.network(features[index]),
                actions[index],
                rewards[index],
                maximum_weight=config.maximum_reward_weight,
            )
            torch.autograd.backward(loss)
            optimizer.step()
            losses.append(float(loss.detach().item()))

    policy.network.eval()
    return CandidateTrainingResult(
        policy=policy,
        losses=tuple(losses),
        train_indices=train_indices,
        validation_indices=validation_indices,
    )
