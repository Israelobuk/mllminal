"""Advisory runtime bridge for domain-scoped suggestion policies."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mllminal.learning.active_policy_registry import ActivePolicyRegistry
from mllminal.learning.contracts import PolicyDomain
from mllminal.learning.offline_features import TrainingFeatureEncoder
from mllminal.learning.replay import LearningRepository
from mllminal.learning.runtime_adapter import ActivePolicyRuntimeAdapter
from mllminal.mining.contracts import WorkflowCandidate


@dataclass(frozen=True)
class SuggestionAdvisoryResult:
    score: float
    provenance: dict[str, Any]


class SuggestionPolicyRuntime:
    """Run a bounded SUGGESTION_RANKING policy as score-only advice."""

    advisory_weight = 0.2

    def __init__(self, repository: LearningRepository, checkpoint_root: Path) -> None:
        encoder = TrainingFeatureEncoder.for_domain(PolicyDomain.SUGGESTION_RANKING)
        self.adapter = ActivePolicyRuntimeAdapter(
            ActivePolicyRegistry(repository, checkpoint_root),
            checkpoint_root,
            policy_domain=PolicyDomain.SUGGESTION_RANKING,
            expected_feature_schema_version=encoder.schema_version,
            expected_input_dimension=encoder.dimension,
        )

    def evaluate(
        self,
        candidate: WorkflowCandidate,
        *,
        verification_available: bool,
        rejection_count: int,
    ) -> SuggestionAdvisoryResult:
        features = TrainingFeatureEncoder.for_domain(
            PolicyDomain.SUGGESTION_RANKING
        ).encode_mapping(
            {
                "occurrence_count": min(candidate.occurrences / 10.0, 1.0),
                "recurrence": min(candidate.occurrences / 10.0, 1.0),
                "correction_rate": 0.0,
                "rejection_rate": min(rejection_count / 5.0, 1.0),
                "snooze_rate": 0.0,
                "estimated_time_saved": 0.0,
                "fragility": 0.0,
                "interruption_cost": 0.0,
                "prior_acceptance_rate": 0.0,
                "application_state_stability": 0.0,
                "workflow_complexity": 0.0,
                "approval_burden": 0.0,
                "verification_availability": float(verification_available),
                "recent_emergency_stop": 0.0,
                "active_workflow_state": 0.0,
            }
        )
        loaded = self.adapter.load()
        rows = self.adapter.infer([features])
        labels = dict(zip(loaded.model.action_labels, rows[0], strict=True))
        score = labels.get("present", max(labels.values()))
        status = self.adapter.status().as_dict()
        status["used_in_ranking"] = True
        return SuggestionAdvisoryResult(score=score, provenance=status)


__all__ = ["SuggestionAdvisoryResult", "SuggestionPolicyRuntime"]
