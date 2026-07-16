"""Seeded offline policy training over privacy-preserving replay samples."""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

import torch
from torch import Tensor
from torch.nn import functional as functional

from mllminal.learning.contracts import PolicyAction, ReplaySample
from mllminal.learning.policy import ActionPolicy, save_checkpoint


@dataclass(frozen=True)
class TrainingConfig:
    seed: int = 42
    epochs: int = 20
    learning_rate: float = 1e-3
    batch_size: int = 32
    train_fraction: float = 0.8


@dataclass(frozen=True)
class TrainingResult:
    policy: ActionPolicy
    losses: tuple[float, ...]
    train_indices: tuple[int, ...]
    holdout_indices: tuple[int, ...]
    checkpoint_path: Path
    checkpoint_sha256: str


def _split_indices(size: int, *, seed: int, train_fraction: float) -> tuple[list[int], list[int]]:
    indices = list(range(size))
    random.Random(seed).shuffle(indices)
    if size <= 1:
        return indices, []
    split = min(size - 1, max(1, int(size * train_fraction)))
    return indices[:split], indices[split:]


def _batch_loss(logits: Tensor, actions: Tensor, rewards: Tensor) -> Tensor:
    positive = rewards >= 0
    losses = torch.empty_like(rewards)
    if bool(positive.any()):
        cross_entropy = functional.cross_entropy(
            logits[positive], actions[positive], reduction="none"
        )
        losses[positive] = cross_entropy * rewards[positive].clamp_min(0.25)
    negative = ~positive
    if bool(negative.any()):
        probabilities = torch.softmax(logits[negative], dim=1)
        failed_probability = probabilities.gather(1, actions[negative].unsqueeze(1)).squeeze(1)
        unlikelihood = -torch.log((1.0 - failed_probability).clamp_min(1e-6))
        losses[negative] = unlikelihood * rewards[negative].abs().clamp_min(0.25)
    return losses.mean()


def train_policy(
    samples: list[ReplaySample],
    *,
    config: TrainingConfig | None = None,
    checkpoint_dir: Path,
    policy_version: str = "policy_v1",
) -> TrainingResult:
    if not samples:
        raise ValueError("at least one replay sample is required")
    config = config or TrainingConfig()
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(config.seed)
    random.seed(config.seed)
    policy = ActionPolicy(seed=config.seed)
    policy.network.train()
    optimizer = torch.optim.Adam(policy.network.parameters(), lr=config.learning_rate)
    train_indices, holdout_indices = _split_indices(
        len(samples), seed=config.seed, train_fraction=config.train_fraction
    )
    generator = torch.Generator(device="cpu").manual_seed(config.seed)
    losses: list[float] = []
    actions = list(PolicyAction)

    for _ in range(config.epochs):
        order = torch.randperm(len(train_indices), generator=generator).tolist()
        epoch_loss = 0.0
        examples = 0
        for start in range(0, len(order), config.batch_size):
            batch_indices = [
                train_indices[order[index]]
                for index in range(start, min(start + config.batch_size, len(order)))
            ]
            features = torch.tensor(
                [samples[index].features for index in batch_indices], dtype=torch.float32
            )
            targets = torch.tensor(
                [actions.index(samples[index].action) for index in batch_indices]
            )
            rewards = torch.tensor(
                [samples[index].reward for index in batch_indices], dtype=torch.float32
            )
            optimizer.zero_grad(set_to_none=True)
            loss = _batch_loss(policy.network(features), targets, rewards)
            loss.backward()  # type: ignore[no-untyped-call]
            optimizer.step()
            batch_size = len(batch_indices)
            epoch_loss += float(loss.detach().item()) * batch_size
            examples += batch_size
        losses.append(epoch_loss / examples)

    policy.network.eval()
    checkpoint_path = checkpoint_dir / f"{policy_version}.pt"
    digest = save_checkpoint(policy, checkpoint_path, policy_version=policy_version)
    return TrainingResult(
        policy=policy,
        losses=tuple(losses),
        train_indices=tuple(train_indices),
        holdout_indices=tuple(holdout_indices),
        checkpoint_path=checkpoint_path,
        checkpoint_sha256=digest,
    )
