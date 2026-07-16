"""Privacy-preserving policy features and safety-aware action masks."""

from collections.abc import Sequence
from math import isfinite

from mllminal.learning.contracts import FEATURE_DIM, PolicyAction, PolicyCheckpoint

_PROVIDER_CODES = {"none": 0.0, "ollama": 0.25, "openai": 0.5, "anthropic": 0.75}


class ActionMask(tuple[bool, ...]):
    """Immutable mask addressable by stable action or numeric position."""

    def __getitem__(self, index: int | slice | PolicyAction) -> bool | tuple[bool, ...]:  # type: ignore[override]
        if isinstance(index, PolicyAction):
            index = tuple(PolicyAction).index(index)
        return super().__getitem__(index)


def _clamp_ratio(value: float, maximum: float) -> float:
    return min(max(value, 0.0), maximum) / maximum


def _message_length_bucket(length: int) -> float:
    if length <= 0:
        return 0.0
    if length <= 250:
        return 0.25
    if length <= 1_000:
        return 0.5
    if length <= 4_000:
        return 0.75
    return 1.0


def _task_age_bucket(seconds: float) -> float:
    if seconds < 60:
        return 0.0
    if seconds < 300:
        return 0.25
    if seconds < 1_800:
        return 0.5
    if seconds < 7_200:
        return 0.75
    return 1.0


def _outcome_code(value: bool | None) -> float:
    if value is None:
        return 0.0
    return 1.0 if value else -1.0


def encode_features(
    *,
    task_state_index: int,
    provider: str,
    message_length: int,
    conversation_count: int,
    workspace_attached: bool,
    available_tool_count: int,
    pending_approval_count: int,
    prior_tool_succeeded: bool | None,
    prior_verification_succeeded: bool | None,
    retry_count: int,
    correction_count: int,
    task_age_seconds: float,
    provider_failure: bool,
    plan_ready: bool,
    verified_result: bool,
) -> tuple[float, ...]:
    """Encode only bounded metadata; raw payloads are intentionally not accepted."""

    if not isfinite(task_age_seconds):
        raise ValueError("feature values must be finite")
    encoded = (
        _clamp_ratio(task_state_index, 8),
        _PROVIDER_CODES.get(provider.lower(), 1.0),
        _message_length_bucket(message_length),
        _clamp_ratio(conversation_count, 20),
        float(workspace_attached),
        _clamp_ratio(available_tool_count, 10),
        _clamp_ratio(pending_approval_count, 5),
        _outcome_code(prior_tool_succeeded),
        _outcome_code(prior_verification_succeeded),
        _clamp_ratio(retry_count, 3),
        _clamp_ratio(correction_count, 3),
        _task_age_bucket(max(task_age_seconds, 0.0)),
        float(provider_failure),
        float(plan_ready),
        float(verified_result),
    )
    if len(encoded) != FEATURE_DIM or not all(isfinite(value) for value in encoded):
        raise ValueError("feature vector must contain 15 finite values")
    return encoded


def build_action_mask(
    checkpoint: PolicyCheckpoint,
    *,
    workspace_attached: bool = False,
    read_file_proposal: bool = False,
    proposal_approved: bool = False,
    tool_result_available: bool = False,
    failure_reversible: bool = False,
    failure_low_risk: bool = False,
    retry_count: int = 0,
) -> ActionMask:
    """Return an immutable mask whose privileged actions require runtime evidence."""

    allowed: set[PolicyAction] = {PolicyAction.STOP_SAFELY}
    if checkpoint is PolicyCheckpoint.REQUEST_RECEIVED:
        allowed.update(
            {PolicyAction.ANSWER_DIRECTLY, PolicyAction.INSPECT_WORKSPACE, PolicyAction.ASK_USER}
        )
    elif checkpoint is PolicyCheckpoint.PLAN_READY:
        allowed.add(PolicyAction.REQUEST_APPROVAL)
        if workspace_attached and read_file_proposal:
            allowed.add(PolicyAction.READ_PROJECT_FILE)
    elif checkpoint is PolicyCheckpoint.APPROVAL_GRANTED and proposal_approved:
        allowed.add(PolicyAction.EXECUTE_APPROVED_TOOL)
    elif checkpoint is PolicyCheckpoint.TOOL_RESULT_AVAILABLE and tool_result_available:
        allowed.add(PolicyAction.VERIFY_RESULT)
    elif (
        checkpoint is PolicyCheckpoint.RECOVERABLE_FAILURE
        and failure_reversible
        and failure_low_risk
        and retry_count < 1
    ):
        allowed.add(PolicyAction.RETRY)
    return ActionMask(action in allowed for action in PolicyAction)


def select_masked_action(scores: Sequence[float], action_mask: Sequence[bool]) -> PolicyAction:
    """Select the highest-scoring allowed learned action or stop safely."""

    actions = tuple(PolicyAction)
    if len(scores) != len(actions) or len(action_mask) != len(actions):
        raise ValueError("scores and action mask must match the action space")
    allowed_learned = [index for index in range(len(actions) - 1) if action_mask[index]]
    if not allowed_learned:
        return PolicyAction.STOP_SAFELY
    return actions[max(allowed_learned, key=lambda index: scores[index])]
