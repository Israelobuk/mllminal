"""Deterministic and scikit-learn baseline evaluation for offline domains."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]

from mllminal.learning.contracts import TrainingExperience
from mllminal.learning.offline_features import TrainingFeatureEncoder


@dataclass(frozen=True)
class OfflineBaselineMetrics:
    sample_count: int
    heuristic_accuracy: float
    sklearn_accuracy: float


def evaluate_offline_baselines(
    experiences: list[TrainingExperience], encoder: TrainingFeatureEncoder
) -> OfflineBaselineMetrics:
    """Compare a frequency heuristic and lightweight local sklearn baseline."""

    samples = [
        experience
        for experience in experiences
        if experience.eligible_for_training
        and experience.privacy_approved
        and experience.selected_action is not None
    ]
    if len(samples) < 2:
        raise ValueError("at least two eligible experiences are required")
    labels = [experience.selected_action or "" for experience in samples]
    if len(set(labels)) < 2:
        raise ValueError("at least two actions are required for baseline evaluation")
    heuristic = Counter(labels).most_common(1)[0][0]
    heuristic_accuracy = sum(label == heuristic for label in labels) / len(labels)
    features = [encoder.encode(experience) for experience in samples]
    model = LogisticRegression(random_state=42, max_iter=100)
    model.fit(features, labels)
    sklearn_accuracy = float(model.score(features, labels))
    return OfflineBaselineMetrics(len(samples), heuristic_accuracy, sklearn_accuracy)
