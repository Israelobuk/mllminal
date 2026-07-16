"""Eligibility checks and transparent reward calculation."""

from collections.abc import Set

from mllminal.learning.contracts import (
    ExperienceOutcome,
    ExperienceRecord,
    PolicyAction,
    RewardBreakdown,
)

_TOOL_RELATED_ACTIONS = {
    PolicyAction.EXECUTE_APPROVED_TOOL,
    PolicyAction.VERIFY_RESULT,
    PolicyAction.RETRY,
}


def eligibility_exclusions(
    experience: ExperienceRecord,
    *,
    seen_idempotency_keys: Set[str] = frozenset(),
) -> tuple[str, ...]:
    """Return deterministic reasons an experience cannot enter offline training."""

    reasons: list[str] = []
    if not experience.outcome.terminal:
        reasons.append("nonterminal")
    if experience.selected_action is None:
        reasons.append("missing_selected_action")
    if experience.reward is None:
        reasons.append("missing_reward")
    if (
        experience.selected_action in _TOOL_RELATED_ACTIONS
        and not experience.outcome.verification_passed
    ):
        reasons.append("unverified_tool_action")
    if experience.contains_sensitive_data:
        reasons.append("sensitive_data")
    if experience.contains_raw_data:
        reasons.append("raw_data")
    if experience.idempotency_key in seen_idempotency_keys:
        reasons.append("duplicate_idempotent_event")
    if experience.synthetic and not experience.training_enabled:
        reasons.append("synthetic_fixture")
    return tuple(reasons)


def is_eligible_experience(
    experience: ExperienceRecord,
    *,
    seen_idempotency_keys: Set[str] = frozenset(),
) -> bool:
    return not eligibility_exclusions(experience, seen_idempotency_keys=seen_idempotency_keys)


def calculate_reward(outcome: ExperienceOutcome) -> RewardBreakdown:
    """Apply fixed weights and retain every component for auditability."""

    components = {
        "verified_completion": 5.0 if outcome.task_completed else 0.0,
        "verification_passed": 2.0 if outcome.verification_passed else 0.0,
        "tool_succeeded": 1.5 if outcome.tool_succeeded else 0.0,
        "user_accepted": 1.0 if outcome.user_accepted else 0.0,
        "efficient_execution": 0.5 if outcome.efficient_execution else 0.0,
        "successful_recovery": 0.5 if outcome.successful_recovery else 0.0,
        "correct_safe_stop": 0.5 if outcome.correct_safe_stop else 0.0,
        "user_corrected": -2.0 if outcome.user_corrected else 0.0,
        "approval_rejected": -1.5 if outcome.approval_rejected else 0.0,
        "tool_failed": -2.5 if outcome.tool_failed else 0.0,
        "verification_failed": -3.0 if outcome.verification_failed else 0.0,
        "invalid_policy_action": -4.0 if outcome.invalid_policy_action else 0.0,
        "unauthorized_action": -5.0 if outcome.unauthorized_action else 0.0,
        "unnecessary_retry": -0.5 if outcome.unnecessary_retry else 0.0,
        "repeated_loop": -1.0 if outcome.repeated_loop else 0.0,
        "provider_failure": -1.5 if outcome.provider_failure else 0.0,
        "task_failure": -2.0 if outcome.task_failed else 0.0,
    }
    return RewardBreakdown.model_validate({**components, "total": sum(components.values())})
