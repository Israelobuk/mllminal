"""Deterministic, source-grouped splits for offline policy evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from mllminal.learning.contracts import TrainingExperience


@dataclass(frozen=True)
class OfflineDataSplit:
    """Leakage-safe train, validation, and test partitions for one replay dataset."""

    train: tuple[TrainingExperience, ...]
    validation: tuple[TrainingExperience, ...]
    test: tuple[TrainingExperience, ...]
    seed: int
    strategy: str = "source-record-grouped-v1"


def split_training_experiences(
    experiences: list[TrainingExperience], *, seed: int = 42
) -> OfflineDataSplit:
    """Split eligible records by source identity, preventing episode leakage."""

    groups: dict[str, list[TrainingExperience]] = {}
    for experience in experiences:
        if not experience.eligible_for_training or not experience.privacy_approved:
            continue
        group_key = f"{experience.source_record_type}:{experience.source_record_id}"
        groups.setdefault(group_key, []).append(experience)
    if len(groups) < 3:
        raise ValueError(
            "at least three source groups are required for train/validation/test splitting"
        )

    ordered_groups = sorted(
        groups.items(),
        key=lambda item: sha256(f"{seed}:{item[0]}".encode()).hexdigest(),
    )
    held_out_count = max(1, len(ordered_groups) // 5)
    test_groups = ordered_groups[:held_out_count]
    validation_groups = ordered_groups[held_out_count : held_out_count * 2]
    train_groups = ordered_groups[held_out_count * 2 :]

    return OfflineDataSplit(
        train=_flatten_groups(train_groups),
        validation=_flatten_groups(validation_groups),
        test=_flatten_groups(test_groups),
        seed=seed,
    )


def _flatten_groups(
    groups: list[tuple[str, list[TrainingExperience]]],
) -> tuple[TrainingExperience, ...]:
    return tuple(
        experience
        for _, rows in groups
        for experience in sorted(rows, key=lambda row: row.experience_id)
    )
