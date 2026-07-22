"""Versioned, allowlisted feature encoders for offline advisory policies."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from mllminal.learning.contracts import PolicyDomain, TrainingExperience

FEATURE_SCHEMA_VERSION = "training_features_v1"

_SUGGESTION_FEATURES = (
    "occurrence_count",
    "recurrence",
    "correction_rate",
    "rejection_rate",
    "snooze_rate",
    "estimated_time_saved",
    "fragility",
    "interruption_cost",
    "prior_acceptance_rate",
    "application_state_stability",
    "workflow_complexity",
    "approval_burden",
    "verification_availability",
    "recent_emergency_stop",
    "active_workflow_state",
)

_EXECUTION_FEATURES = (
    "application_profile_reliability",
    "backend_success_rate",
    "backend_failure_recency",
    "target_stability",
    "verification_availability",
    "consequence_class",
    "provider_availability",
    "fragility",
    "approval_burden",
    "recent_emergency_stop",
    "active_workflow_state",
    "workflow_complexity",
    "correction_rate",
    "rollback_rate",
    "interruption_cost",
)

_FEATURES_BY_DOMAIN = {
    PolicyDomain.BACKEND_RANKING: _EXECUTION_FEATURES,
    PolicyDomain.SUGGESTION_RANKING: _SUGGESTION_FEATURES,
    PolicyDomain.SUGGESTION_TIMING: _SUGGESTION_FEATURES,
    PolicyDomain.CLARIFICATION_POLICY: _SUGGESTION_FEATURES,
    PolicyDomain.VERIFICATION_RANKING: _EXECUTION_FEATURES,
    PolicyDomain.REPAIR_RANKING: _EXECUTION_FEATURES,
    PolicyDomain.ADAPTATION_RANKING: _SUGGESTION_FEATURES,
}


@dataclass(frozen=True)
class TrainingFeatureEncoder:
    policy_domain: PolicyDomain
    feature_names: tuple[str, ...]
    schema_version: str = FEATURE_SCHEMA_VERSION

    @classmethod
    def for_domain(cls, policy_domain: PolicyDomain) -> TrainingFeatureEncoder:
        return cls(policy_domain, _FEATURES_BY_DOMAIN[policy_domain])

    @property
    def dimension(self) -> int:
        return len(self.feature_names)

    def encode(self, experience: TrainingExperience) -> tuple[float, ...]:
        if experience.policy_domain is not self.policy_domain:
            raise ValueError("experience policy domain does not match feature encoder")
        unknown = set(experience.context_features) - set(self.feature_names)
        if unknown:
            raise ValueError(f"feature names are not allowed: {sorted(unknown)}")
        values = tuple(
            self._normalize(experience.context_features.get(name, 0.0))
            for name in self.feature_names
        )
        return values

    @staticmethod
    def _normalize(value: float) -> float:
        if not isfinite(value):
            raise ValueError("feature values must be finite")
        return min(max(value, 0.0), 1.0)
