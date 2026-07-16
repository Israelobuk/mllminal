import torch

from mllminal.learning.contracts import PolicyAction, ReplaySample
from mllminal.learning.evaluation import EvaluationCase, evaluate_policy
from mllminal.learning.policy import ActionPolicy


def _biased_policy(action: PolicyAction) -> ActionPolicy:
    policy = ActionPolicy(seed=42)
    with torch.no_grad():
        for parameter in policy.network.parameters():
            parameter.zero_()
        policy.network.layers[-1].bias[list(PolicyAction).index(action)] = 10.0
    return policy


def _case(action: PolicyAction, reward: float, mask: tuple[bool, ...]) -> EvaluationCase:
    return EvaluationCase(
        sample=ReplaySample(
            experience_id="019b0000-0000-7000-8000-000000000001",
            features=(0.0,) * 15,
            action=action,
            reward=reward,
        ),
        action_mask=mask,
    )


def test_evaluation_reports_required_metrics_and_promotion_gate() -> None:
    answer_mask = tuple(action is PolicyAction.ANSWER_DIRECTLY for action in PolicyAction)
    cases = [_case(PolicyAction.ANSWER_DIRECTLY, 5.0, answer_mask) for _ in range(4)]

    metrics = evaluate_policy(
        _biased_policy(PolicyAction.ANSWER_DIRECTLY),
        cases,
        baseline_reward_weighted_accuracy=0.5,
    )

    assert metrics.action_accuracy == 1.0
    assert metrics.reward_weighted_accuracy == 1.0
    assert metrics.average_predicted_reward > 4.9
    assert metrics.raw_invalid_action_rate == 0.0
    assert metrics.safe_fallback_rate == 0.0
    assert metrics.regression_pass_rate == 1.0
    assert metrics.promotion_eligible


def test_raw_invalid_action_is_measured_before_safe_masking() -> None:
    stop_only = tuple(action is PolicyAction.STOP_SAFELY for action in PolicyAction)
    metrics = evaluate_policy(
        _biased_policy(PolicyAction.EXECUTE_APPROVED_TOOL),
        [_case(PolicyAction.STOP_SAFELY, -1.0, stop_only)],
        baseline_reward_weighted_accuracy=0.0,
    )

    assert metrics.raw_invalid_action_rate == 1.0
    assert metrics.safe_fallback_rate == 1.0
    assert metrics.regression_pass_rate == 1.0
    assert not metrics.promotion_eligible
    assert "invalid_action_rate" in metrics.rejection_reasons


def test_improvement_must_be_at_least_two_points() -> None:
    answer_mask = (True,) * 9
    cases = [
        _case(PolicyAction.ANSWER_DIRECTLY, 1.0, answer_mask),
        _case(PolicyAction.ASK_USER, 1.0, answer_mask),
    ]
    metrics = evaluate_policy(
        _biased_policy(PolicyAction.ANSWER_DIRECTLY),
        cases,
        baseline_reward_weighted_accuracy=0.49,
    )
    assert metrics.reward_weighted_accuracy == 0.5
    assert not metrics.promotion_eligible
    assert "insufficient_improvement" in metrics.rejection_reasons
