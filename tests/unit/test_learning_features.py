from importlib import import_module
from math import inf

import pytest

contracts = import_module("mllminal.learning.contracts")
features = import_module("mllminal.learning.features")


def _encoded(**overrides: object) -> tuple[float, ...]:
    values: dict[str, object] = {
        "task_state_index": 4,
        "provider": "ollama",
        "message_length": 251,
        "conversation_count": 10,
        "workspace_attached": True,
        "available_tool_count": 5,
        "pending_approval_count": 1,
        "prior_tool_succeeded": True,
        "prior_verification_succeeded": False,
        "retry_count": 1,
        "correction_count": 2,
        "task_age_seconds": 300,
        "provider_failure": True,
        "plan_ready": False,
        "verified_result": True,
    }
    values.update(overrides)
    return features.encode_features(**values)


def test_feature_encoder_has_fixed_deterministic_order_and_dimension() -> None:
    encoded = _encoded()

    assert encoded == (
        0.5,
        0.25,
        0.5,
        0.5,
        1.0,
        0.5,
        0.2,
        1.0,
        -1.0,
        1 / 3,
        2 / 3,
        0.5,
        1.0,
        0.0,
        1.0,
    )
    assert isinstance(encoded, tuple)
    assert len(encoded) == contracts.FEATURE_DIM == 15
    assert contracts.FEATURE_VERSION == "features_v1"
    assert encoded == _encoded()


def test_feature_encoder_buckets_and_clamps_counts() -> None:
    low = _encoded(
        task_state_index=-1,
        message_length=0,
        conversation_count=-5,
        available_tool_count=-2,
        pending_approval_count=-1,
        retry_count=-4,
        correction_count=-3,
        task_age_seconds=0,
    )
    high = _encoded(
        task_state_index=99,
        message_length=10_000,
        conversation_count=99,
        available_tool_count=99,
        pending_approval_count=99,
        retry_count=99,
        correction_count=99,
        task_age_seconds=99_999,
    )

    for index in (0, 2, 3, 5, 6, 9, 10, 11):
        assert low[index] == 0.0
        assert high[index] == 1.0


def test_feature_encoder_rejects_nonfinite_values_and_raw_payload_arguments() -> None:
    with pytest.raises(ValueError, match="finite"):
        _encoded(task_age_seconds=inf)
    with pytest.raises(TypeError):
        _encoded(message_content="secret")


@pytest.mark.parametrize(
    ("checkpoint", "expected"),
    [
        (
            "REQUEST_RECEIVED",
            {"ANSWER_DIRECTLY", "INSPECT_WORKSPACE", "ASK_USER", "STOP_SAFELY"},
        ),
        ("PLAN_READY", {"REQUEST_APPROVAL", "STOP_SAFELY"}),
        ("APPROVAL_GRANTED", {"STOP_SAFELY"}),
        ("TOOL_RESULT_AVAILABLE", {"STOP_SAFELY"}),
        ("RECOVERABLE_FAILURE", {"STOP_SAFELY"}),
    ],
)
def test_checkpoint_masks_allow_only_checkpoint_actions(
    checkpoint: str, expected: set[str]
) -> None:
    mask = features.build_action_mask(contracts.PolicyCheckpoint(checkpoint))

    allowed = {
        action.value
        for action, allowed in zip(contracts.PolicyAction, mask, strict=True)
        if allowed
    }
    assert allowed == expected


def test_sensitive_actions_require_attached_approved_runtime_evidence() -> None:
    read_mask = features.build_action_mask(
        contracts.PolicyCheckpoint.PLAN_READY,
        workspace_attached=True,
        read_file_proposal=True,
    )
    execute_mask = features.build_action_mask(
        contracts.PolicyCheckpoint.APPROVAL_GRANTED,
        proposal_approved=True,
    )
    verify_mask = features.build_action_mask(
        contracts.PolicyCheckpoint.TOOL_RESULT_AVAILABLE,
        tool_result_available=True,
    )
    retry_mask = features.build_action_mask(
        contracts.PolicyCheckpoint.RECOVERABLE_FAILURE,
        failure_reversible=True,
        failure_low_risk=True,
        retry_count=0,
    )

    assert read_mask[contracts.PolicyAction.READ_PROJECT_FILE] is True
    assert execute_mask[contracts.PolicyAction.EXECUTE_APPROVED_TOOL] is True
    assert verify_mask[contracts.PolicyAction.VERIFY_RESULT] is True
    assert retry_mask[contracts.PolicyAction.RETRY] is True
    assert (
        features.build_action_mask(
            contracts.PolicyCheckpoint.RECOVERABLE_FAILURE,
            failure_reversible=True,
            failure_low_risk=True,
            retry_count=1,
        )[contracts.PolicyAction.RETRY]
        is False
    )


def test_decision_falls_back_to_safe_stop_when_all_learned_actions_are_masked() -> None:
    scores = (100.0,) * 8 + (-100.0,)
    mask = (False,) * 8 + (True,)

    assert features.select_masked_action(scores, mask) is contracts.PolicyAction.STOP_SAFELY
