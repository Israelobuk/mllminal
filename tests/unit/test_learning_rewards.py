from importlib import import_module

import pytest

contracts = import_module("mllminal.learning.contracts")
rewards = import_module("mllminal.learning.rewards")


def _record(**overrides: object):
    values: dict[str, object] = {
        "task_id": "task-1",
        "decision_id": "decision-1",
        "idempotency_key": "event-1",
        "selected_action": contracts.PolicyAction.ANSWER_DIRECTLY,
        "outcome": contracts.ExperienceOutcome(terminal=True, task_completed=True),
        "reward": contracts.RewardBreakdown(verified_completion=5.0, total=5.0),
    }
    values.update(overrides)
    return contracts.ExperienceRecord(**values)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"outcome": {"terminal": False}}, "nonterminal"),
        ({"selected_action": None}, "missing_selected_action"),
        ({"reward": None}, "missing_reward"),
        ({"contains_sensitive_data": True}, "sensitive_data"),
        ({"contains_raw_data": True}, "raw_data"),
        ({"synthetic": True}, "synthetic_fixture"),
    ],
)
def test_eligibility_rejects_incomplete_or_unsafe_experiences(
    overrides: dict[str, object], reason: str
) -> None:
    record = _record(**overrides)

    assert reason in rewards.eligibility_exclusions(record)
    assert rewards.is_eligible_experience(record) is False


def test_eligibility_rejects_unverified_tool_actions_and_duplicate_events() -> None:
    unverified = _record(
        selected_action=contracts.PolicyAction.EXECUTE_APPROVED_TOOL,
        outcome=contracts.ExperienceOutcome(terminal=True, tool_succeeded=True),
    )
    duplicate = _record()

    assert "unverified_tool_action" in rewards.eligibility_exclusions(unverified)
    assert rewards.is_eligible_experience(duplicate, seen_idempotency_keys={"event-1"}) is False


def test_training_enabled_synthetic_terminal_fixture_is_eligible() -> None:
    record = _record(synthetic=True, training_enabled=True)

    assert rewards.is_eligible_experience(record) is True


def test_reward_calculation_exposes_every_weight_and_total() -> None:
    outcome = contracts.ExperienceOutcome(
        terminal=True,
        task_completed=True,
        verification_passed=True,
        tool_succeeded=True,
        user_accepted=True,
        efficient_execution=True,
        successful_recovery=True,
        correct_safe_stop=True,
        user_corrected=True,
        approval_rejected=True,
        tool_failed=True,
        verification_failed=True,
        invalid_policy_action=True,
        unauthorized_action=True,
        unnecessary_retry=True,
        repeated_loop=True,
        provider_failure=True,
        task_failed=True,
    )

    breakdown = rewards.calculate_reward(outcome)

    assert breakdown.model_dump() == {
        "schema_version": "v1",
        "verified_completion": 5.0,
        "verification_passed": 2.0,
        "tool_succeeded": 1.5,
        "user_accepted": 1.0,
        "efficient_execution": 0.5,
        "successful_recovery": 0.5,
        "correct_safe_stop": 0.5,
        "user_corrected": -2.0,
        "approval_rejected": -1.5,
        "tool_failed": -2.5,
        "verification_failed": -3.0,
        "invalid_policy_action": -4.0,
        "unauthorized_action": -5.0,
        "unnecessary_retry": -0.5,
        "repeated_loop": -1.0,
        "provider_failure": -1.5,
        "task_failure": -2.0,
        "total": -12.0,
    }


def test_reward_total_is_the_transparent_sum_of_components() -> None:
    breakdown = rewards.calculate_reward(
        contracts.ExperienceOutcome(
            terminal=True,
            verification_passed=True,
            user_corrected=True,
            correct_safe_stop=True,
        )
    )

    components = breakdown.model_dump(exclude={"schema_version", "total"}).values()
    assert breakdown.total == pytest.approx(sum(components)) == 0.5
