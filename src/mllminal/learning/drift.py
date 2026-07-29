"""Read-only behavioral drift and retraining-readiness reporting."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from pydantic import Field

from mllminal.contracts import Contract, utc_now
from mllminal.learning.adaptive_contracts import AdaptiveExecutionDecision
from mllminal.learning.contracts import PolicyDomain
from mllminal.learning.metrics import summarize_backend_outcomes


class PolicyDriftReport(Contract):
    policy_domain: PolicyDomain = PolicyDomain.BACKEND_RANKING
    observation_count: int = Field(ge=0)
    outcome_count: int = Field(ge=0)
    failure_rate: float = Field(ge=0.0, le=1.0)
    shadow_evaluation_count: int = Field(ge=0)
    shadow_rank_change_rate: float = Field(ge=0.0, le=1.0)
    minimum_observations: int = Field(ge=1)
    drift_detected: bool = False
    retraining_recommended: bool = False
    reasons: tuple[str, ...] = ()
    automatic_retraining_enabled: bool = False
    automatic_promotion_enabled: bool = False
    generated_at: datetime = Field(default_factory=utc_now)


class BehavioralDriftDetector:
    """Detect sustained behavioral drift without mutating training or policy state."""

    def __init__(
        self,
        *,
        minimum_observations: int = 10,
        failure_rate_threshold: float = 0.35,
        shadow_rank_change_threshold: float = 0.50,
    ) -> None:
        if minimum_observations < 1:
            raise ValueError("minimum_observations must be positive")
        if not 0.0 <= failure_rate_threshold <= 1.0:
            raise ValueError("failure_rate_threshold must be between 0 and 1")
        if not 0.0 <= shadow_rank_change_threshold <= 1.0:
            raise ValueError("shadow_rank_change_threshold must be between 0 and 1")
        self.minimum_observations = minimum_observations
        self.failure_rate_threshold = failure_rate_threshold
        self.shadow_rank_change_threshold = shadow_rank_change_threshold

    def assess(self, decisions: Iterable[AdaptiveExecutionDecision]) -> PolicyDriftReport:
        items = list(decisions)
        metrics = summarize_backend_outcomes(items)
        reasons: list[str] = []
        if metrics.outcome_count >= self.minimum_observations:
            failure_rate = 1.0 - metrics.execution_success_rate
            if failure_rate >= self.failure_rate_threshold:
                reasons.append("failure_rate")
        else:
            failure_rate = 0.0
        if (
            metrics.shadow_evaluation_count >= self.minimum_observations
            and metrics.shadow_rank_change_rate >= self.shadow_rank_change_threshold
        ):
            reasons.append("shadow_rank_change_rate")
        drift_detected = bool(reasons)
        return PolicyDriftReport(
            observation_count=metrics.decision_count,
            outcome_count=metrics.outcome_count,
            failure_rate=failure_rate,
            shadow_evaluation_count=metrics.shadow_evaluation_count,
            shadow_rank_change_rate=metrics.shadow_rank_change_rate,
            minimum_observations=self.minimum_observations,
            drift_detected=drift_detected,
            retraining_recommended=drift_detected,
            reasons=tuple(reasons),
        )


__all__ = ["BehavioralDriftDetector", "PolicyDriftReport"]
