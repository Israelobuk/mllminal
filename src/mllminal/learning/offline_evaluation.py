"""Held-out deterministic and scikit-learn baseline evaluation for offline domains."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]

from mllminal.learning.contracts import TrainingExperience
from mllminal.learning.offline_features import TrainingFeatureEncoder
from mllminal.learning.offline_splits import split_training_experiences


@dataclass(frozen=True)
class OfflineBaselineMetrics:
    sample_count: int
    train_sample_count: int
    validation_sample_count: int
    test_sample_count: int
    heuristic_accuracy: float
    sklearn_accuracy: float
    training_source_ids: tuple[str, ...]
    evaluated_source_ids: tuple[str, ...]
    split_strategy: str


def evaluate_offline_baselines(
    experiences: list[TrainingExperience],
    encoder: TrainingFeatureEncoder,
    *,
    seed: int = 42,
) -> OfflineBaselineMetrics:
    """Compare local baselines on a deterministic source-grouped test partition."""

    samples = [
        experience
        for experience in experiences
        if experience.eligible_for_training
        and experience.privacy_approved
        and experience.selected_action is not None
    ]
    if len(samples) < 3:
        raise ValueError("at least three eligible experiences are required")
    split = split_training_experiences(samples, seed=seed)
    training_labels = [experience.selected_action or "" for experience in split.train]
    if len(set(training_labels)) < 2:
        raise ValueError("at least two training actions are required for baseline evaluation")

    heuristic = Counter(training_labels).most_common(1)[0][0]
    test_labels = [experience.selected_action or "" for experience in split.test]
    heuristic_accuracy = sum(label == heuristic for label in test_labels) / len(test_labels)
    model = LogisticRegression(random_state=seed, max_iter=100)
    model.fit([encoder.encode(experience) for experience in split.train], training_labels)
    sklearn_accuracy = float(
        model.score(
            [encoder.encode(experience) for experience in split.test],
            test_labels,
        )
    )
    return OfflineBaselineMetrics(
        sample_count=len(samples),
        train_sample_count=len(split.train),
        validation_sample_count=len(split.validation),
        test_sample_count=len(split.test),
        heuristic_accuracy=heuristic_accuracy,
        sklearn_accuracy=sklearn_accuracy,
        training_source_ids=_source_ids(split.train),
        evaluated_source_ids=_source_ids(split.test),
        split_strategy=split.strategy,
    )


def _source_ids(experiences: tuple[TrainingExperience, ...]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                f"{experience.source_record_type}:{experience.source_record_id}"
                for experience in experiences
            }
        )
    )
