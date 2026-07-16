from datetime import UTC
from importlib import import_module
from uuid import UUID

import pytest
from pydantic import ValidationError

contracts = import_module("mllminal.learning.contracts")


def test_policy_actions_are_fixed_and_versioned() -> None:
    actions = contracts.PolicyAction

    assert [action.value for action in actions] == [
        "ANSWER_DIRECTLY",
        "INSPECT_WORKSPACE",
        "READ_PROJECT_FILE",
        "ASK_USER",
        "REQUEST_APPROVAL",
        "EXECUTE_APPROVED_TOOL",
        "VERIFY_RESULT",
        "RETRY",
        "STOP_SAFELY",
    ]
    assert contracts.ACTION_SPACE_VERSION == "actions_v1"


def test_policy_decision_serializes_v1_uuid7_and_utc_timestamp() -> None:
    decision = contracts.PolicyDecision(
        task_id="task-1",
        selected_action=contracts.PolicyAction.ANSWER_DIRECTLY,
    )
    serialized = decision.model_dump(mode="json")

    assert serialized["schema_version"] == "v1"
    assert UUID(serialized["id"]).version == 7
    assert decision.created_at.tzinfo is UTC
    assert serialized["confidence"] == 0.65


def test_learning_contracts_are_frozen_and_forbid_extra_fields() -> None:
    decision = contracts.PolicyDecision(
        task_id="task-1",
        selected_action=contracts.PolicyAction.STOP_SAFELY,
    )

    with pytest.raises(ValidationError):
        contracts.PolicyDecision(
            task_id="task-1",
            selected_action=contracts.PolicyAction.STOP_SAFELY,
            surprise=True,
        )
    with pytest.raises(ValidationError):
        decision.confidence = 0.1


def test_policy_decision_rejects_arbitrary_action_strings() -> None:
    with pytest.raises(ValidationError):
        contracts.PolicyDecision(task_id="task-1", selected_action="DELETE_EVERYTHING")


def test_all_required_contracts_are_pydantic_models() -> None:
    required = (
        "PolicyState",
        "PolicyDecision",
        "RewardBreakdown",
        "ExperienceOutcome",
        "ExperienceRecord",
        "ReplaySample",
        "TrainingRun",
        "EvaluationReport",
        "PolicyVersion",
        "PromotionDecision",
        "RollbackRecord",
        "LearningStatus",
    )

    for name in required:
        model = getattr(contracts, name)
        assert model.model_fields["schema_version"].default == "v1"


def test_reward_breakdown_rejects_a_total_that_is_not_its_component_sum() -> None:
    with pytest.raises(ValidationError, match="sum"):
        contracts.RewardBreakdown(verified_completion=5.0, verification_passed=2.0, total=6.0)


def test_policy_state_requires_exact_feature_and_mask_dimensions() -> None:
    with pytest.raises(ValidationError):
        contracts.PolicyState(task_id="task-1", features=(0.0,) * 14, action_mask=(True,) * 9)
    with pytest.raises(ValidationError):
        contracts.PolicyState(task_id="task-1", features=(0.0,) * 15, action_mask=(True,) * 8)
