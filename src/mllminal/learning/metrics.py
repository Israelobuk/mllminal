"""Deterministic monitoring summaries for persisted adaptive outcomes."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import Field

from mllminal.contracts import Contract
from mllminal.learning.adaptive_contracts import AdaptiveExecutionDecision
from mllminal.learning.contracts import PolicyDomain


class AdaptiveOutcomeMetrics(Contract):
    policy_domain: PolicyDomain = PolicyDomain.BACKEND_RANKING
    decision_count: int = Field(ge=0)
    outcome_count: int = Field(ge=0)
    execution_success_count: int = Field(ge=0)
    verification_pass_count: int = Field(ge=0)
    active_advisory_decision_count: int = Field(ge=0)
    active_advisory_influence_count: int = Field(ge=0)
    shadow_evaluation_count: int = Field(ge=0)
    shadow_rank_change_count: int = Field(ge=0)
    outcome_coverage: float = Field(ge=0.0, le=1.0)
    execution_success_rate: float = Field(ge=0.0, le=1.0)
    verification_pass_rate: float = Field(ge=0.0, le=1.0)
    active_advisory_influence_rate: float = Field(ge=0.0, le=1.0)
    shadow_rank_change_rate: float = Field(ge=0.0, le=1.0)


def summarize_backend_outcomes(
    decisions: Iterable[AdaptiveExecutionDecision],
) -> AdaptiveOutcomeMetrics:
    items = list(decisions)
    decision_count = len(items)
    outcomes = [item for item in items if item.execution_outcome is not None]
    outcome_count = len(outcomes)
    execution_success_count = sum(item.execution_outcome == "succeeded" for item in outcomes)
    verification_pass_count = sum(item.verification_outcome == "passed" for item in outcomes)
    active_advisory_decision_count = sum(bool(item.advisory_scores) for item in items)
    active_advisory_influence_count = sum(item.advisory_changed_selection for item in items)
    shadow_evaluation_count = sum(
        bool(item.shadow_policy.get("shadow")) or bool(item.shadow_advisory_scores)
        for item in items
    )
    shadow_rank_change_count = sum(item.shadow_rank_changed for item in items)

    def rate(numerator: int, denominator: int) -> float:
        return numerator / denominator if denominator else 0.0

    return AdaptiveOutcomeMetrics(
        decision_count=decision_count,
        outcome_count=outcome_count,
        execution_success_count=execution_success_count,
        verification_pass_count=verification_pass_count,
        active_advisory_decision_count=active_advisory_decision_count,
        active_advisory_influence_count=active_advisory_influence_count,
        shadow_evaluation_count=shadow_evaluation_count,
        shadow_rank_change_count=shadow_rank_change_count,
        outcome_coverage=rate(outcome_count, decision_count),
        execution_success_rate=rate(execution_success_count, outcome_count),
        verification_pass_rate=rate(verification_pass_count, outcome_count),
        active_advisory_influence_rate=rate(
            active_advisory_influence_count, active_advisory_decision_count
        ),
        shadow_rank_change_rate=rate(shadow_rank_change_count, shadow_evaluation_count),
    )


__all__ = ["AdaptiveOutcomeMetrics", "summarize_backend_outcomes"]
