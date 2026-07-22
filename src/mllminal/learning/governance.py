"""Candidate evaluation, explicit promotion, and safe rollback governance."""

from __future__ import annotations

from dataclasses import dataclass

from mllminal.learning.contracts import (
    EvaluationReport,
    PolicyLifecycle,
    PolicyVersion,
    RollbackRecord,
)
from mllminal.learning.evaluation import EvaluationCase, EvaluationMetrics, evaluate_policy
from mllminal.learning.policy import ActionPolicy, PolicyCheckpointError
from mllminal.learning.registry import PolicyRegistry, PromotionGateError
from mllminal.learning.replay import LearningRepository


class PromotionApprovalError(PromotionGateError):
    """Raised when a candidate lacks an explicit approved passing evaluation."""


@dataclass(frozen=True)
class GovernedEvaluation:
    report: EvaluationReport
    metrics: EvaluationMetrics


class CandidateGovernanceService:
    """Keeps candidate evaluation and activation separate from runtime decisions."""

    def __init__(self, repository: LearningRepository, registry: PolicyRegistry) -> None:
        self.repository = repository
        self.registry = registry

    def evaluate(
        self, candidate_policy_id: str, training_run_id: str, cases: list[EvaluationCase]
    ) -> GovernedEvaluation:
        candidate = self.repository.get_policy_version(candidate_policy_id)
        candidate_policy = self.load_active_or_fallback(candidate)
        baseline = self.load_active_or_fallback(self.repository.get_promoted_policy())
        baseline_metrics = evaluate_policy(baseline, cases, baseline_reward_weighted_accuracy=0.0)
        metrics = evaluate_policy(
            candidate_policy,
            cases,
            baseline_reward_weighted_accuracy=baseline_metrics.reward_weighted_accuracy,
        )
        report = EvaluationReport(
            training_run_id=training_run_id,
            candidate_policy_id=candidate_policy_id,
            sample_count=len(cases),
            mean_reward=metrics.average_predicted_reward,
            safe_action_rate=metrics.safe_fallback_rate,
            passed=metrics.promotion_eligible,
            action_accuracy=metrics.action_accuracy,
            reward_weighted_accuracy=metrics.reward_weighted_accuracy,
            average_predicted_reward=metrics.average_predicted_reward,
            invalid_action_rate=metrics.raw_invalid_action_rate,
            safe_fallback_rate=metrics.safe_fallback_rate,
            regression_pass_rate=metrics.regression_pass_rate,
            baseline_reward_weighted_accuracy=metrics.baseline_reward_weighted_accuracy,
            rejection_reasons=metrics.rejection_reasons,
        )
        self.repository.save_evaluation_report(report)
        self.repository.update_offline_candidate(
            candidate_policy_id,
            lifecycle=(
                PolicyLifecycle.ELIGIBLE_FOR_PROMOTION
                if report.passed
                else PolicyLifecycle.EVALUATED
            ),
            evaluation_metrics={
                "action_accuracy": report.action_accuracy,
                "reward_weighted_accuracy": report.reward_weighted_accuracy,
                "average_predicted_reward": report.average_predicted_reward,
            },
            baseline_metrics={
                "reward_weighted_accuracy": report.baseline_reward_weighted_accuracy,
            },
            safety_checks={
                "no_invalid_actions": report.invalid_action_rate == 0.0,
                "no_safety_regression": report.regression_pass_rate == 1.0,
            },
        )
        if not report.passed:
            self.repository.reject_policy(
                candidate_policy_id, reason=",".join(metrics.rejection_reasons)
            )
        self.repository.append_event(
            "learning.evaluation.completed",
            {"evaluation_report_id": report.id, "candidate_policy_id": candidate_policy_id},
        )
        return GovernedEvaluation(report=report, metrics=metrics)

    def promote(
        self,
        candidate_policy_id: str,
        evaluation_report_id: str,
        *,
        explicitly_approved: bool,
        idempotency_key: str,
    ) -> PolicyVersion:
        if not explicitly_approved:
            raise PromotionApprovalError("explicit approval is required")
        report = self.repository.get_evaluation_report(evaluation_report_id)
        if report.candidate_policy_id != candidate_policy_id or not report.passed:
            raise PromotionApprovalError("candidate does not have a passing evaluation")
        candidate = self.repository.get_policy_version(candidate_policy_id)
        try:
            self.registry.load(candidate)
        except (PolicyCheckpointError, ValueError) as error:
            self.repository.reject_policy(
                candidate_policy_id, reason="checkpoint_validation_failed"
            )
            raise PromotionApprovalError("candidate checkpoint cannot be activated") from error
        metrics = EvaluationMetrics(
            action_accuracy=report.action_accuracy,
            reward_weighted_accuracy=report.reward_weighted_accuracy,
            average_predicted_reward=report.average_predicted_reward,
            raw_invalid_action_rate=report.invalid_action_rate,
            safe_fallback_rate=report.safe_fallback_rate,
            regression_pass_rate=report.regression_pass_rate,
            baseline_reward_weighted_accuracy=report.baseline_reward_weighted_accuracy,
            promotion_eligible=report.passed,
            rejection_reasons=report.rejection_reasons,
        )
        return self.registry.promote(
            candidate_policy_id,
            metrics,
            explicitly_approved=True,
            idempotency_key=idempotency_key,
        )

    def rollback(self, *, reason: str, idempotency_key: str) -> RollbackRecord:
        existing = self.repository.find_rollback_by_key(idempotency_key)
        if existing is not None:
            return existing
        active = self.repository.get_promoted_policy()
        candidates = [
            policy
            for policy in self.repository.list_policy_versions()
            if policy.id != active.id and policy.lifecycle is PolicyLifecycle.RETIRED
        ]
        if not candidates:
            raise KeyError("rollback target")
        target = max(candidates, key=lambda policy: policy.version)
        return self.registry.rollback(
            target.name or "", reason=reason, idempotency_key=idempotency_key
        )

    def load_active_or_fallback(self, policy: PolicyVersion) -> ActionPolicy:
        if policy.version == 0:
            return ActionPolicy(seed=self.repository.get_settings().seed)
        try:
            return self.registry.load(policy).policy
        except (PolicyCheckpointError, ValueError):
            return ActionPolicy(seed=self.repository.get_settings().seed)
