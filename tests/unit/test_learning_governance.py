from pathlib import Path

import pytest
import torch

from mllminal.learning.contracts import PolicyAction, PolicyLifecycle, ReplaySample, TrainingRun
from mllminal.learning.evaluation import EvaluationCase
from mllminal.learning.governance import CandidateGovernanceService, PromotionApprovalError
from mllminal.learning.policy import ActionPolicy, save_checkpoint
from mllminal.learning.registry import PolicyRegistry
from mllminal.learning.replay import LearningRepository


def _policy(action: PolicyAction) -> ActionPolicy:
    policy = ActionPolicy(seed=42)
    with torch.no_grad():
        for parameter in policy.network.parameters():
            parameter.zero_()
        policy.network.layers[-1].bias[list(PolicyAction).index(action)] = 10.0
    return policy


def _case(action: PolicyAction, *, mask: tuple[bool, ...] | None = None) -> EvaluationCase:
    return EvaluationCase(
        sample=ReplaySample(
            experience_id="019b0000-0000-7000-8000-000000000001",
            features=(0.0,) * 15,
            action=action,
            reward=5.0,
        ),
        action_mask=mask or (True,) * 9,
    )


def _service(tmp_path: Path, action: PolicyAction = PolicyAction.ANSWER_DIRECTLY):
    repository = LearningRepository(tmp_path / "state.db")
    repository.initialize()
    registry = PolicyRegistry(repository, tmp_path / "checkpoints")
    source = tmp_path / "candidate.pt"
    digest = save_checkpoint(_policy(action), source, policy_version="policy_v1")
    candidate = registry.register_candidate(source, checkpoint_sha256=digest)
    run = TrainingRun()
    repository.save_training_run(run)
    return CandidateGovernanceService(repository, registry), repository, candidate, run


def test_passing_evaluation_persists_typed_report_and_completion_event(tmp_path: Path) -> None:
    service, repository, candidate, run = _service(tmp_path)

    result = service.evaluate(candidate.id, run.id, [_case(PolicyAction.ANSWER_DIRECTLY)])

    assert result.report.passed is True
    assert result.report.candidate_policy_id == candidate.id
    assert result.metrics.action_accuracy == 1.0
    assert repository.get_evaluation_report(result.report.id) == result.report
    assert (
        repository.get_policy_version(candidate.id).lifecycle
        is PolicyLifecycle.ELIGIBLE_FOR_PROMOTION
    )
    assert repository.list_events()[-1].event_type == "learning.evaluation.completed"


def test_insufficient_improvement_and_invalid_action_reject_candidates(tmp_path: Path) -> None:
    service, repository, candidate, run = _service(tmp_path, PolicyAction.STOP_SAFELY)
    service.evaluate(candidate.id, run.id, [_case(PolicyAction.STOP_SAFELY)])
    assert repository.get_policy_version(candidate.id).lifecycle is PolicyLifecycle.REJECTED

    unsafe, unsafe_repository, unsafe_candidate, unsafe_run = _service(
        tmp_path / "unsafe", PolicyAction.EXECUTE_APPROVED_TOOL
    )
    stop_only = tuple(action is PolicyAction.STOP_SAFELY for action in PolicyAction)
    unsafe.evaluate(
        unsafe_candidate.id, unsafe_run.id, [_case(PolicyAction.STOP_SAFELY, mask=stop_only)]
    )
    assert (
        unsafe_repository.get_policy_version(unsafe_candidate.id).lifecycle
        is PolicyLifecycle.REJECTED
    )


def test_explicit_idempotent_promotion_and_rollback_restore_previous_policy(tmp_path: Path) -> None:
    service, repository, candidate, run = _service(tmp_path)
    report = service.evaluate(candidate.id, run.id, [_case(PolicyAction.ANSWER_DIRECTLY)]).report

    with pytest.raises(PromotionApprovalError):
        service.promote(candidate.id, report.id, explicitly_approved=False, idempotency_key="p1")
    promoted = service.promote(
        candidate.id, report.id, explicitly_approved=True, idempotency_key="p1"
    )
    duplicate = service.promote(
        candidate.id, report.id, explicitly_approved=True, idempotency_key="p1"
    )
    assert repository.get_promoted_policy().id == candidate.id
    rollback = service.rollback(reason="operator", idempotency_key="r1")
    repeated = service.rollback(reason="operator", idempotency_key="r1")

    assert promoted.id == duplicate.id == candidate.id
    assert rollback.to_policy_version_id == repeated.to_policy_version_id
    assert repository.get_promoted_policy().name == "policy_v0"
    assert [event.event_type for event in repository.list_events()].count(
        "learning.policy.rolled_back"
    ) == 1


def test_digest_mismatch_and_incompatible_checkpoint_fall_back_safely(tmp_path: Path) -> None:
    service, _repository, candidate, _run = _service(tmp_path)
    checkpoint = tmp_path / "checkpoints" / f"{candidate.name}.pt"
    checkpoint.write_bytes(b"tampered")

    fallback = service.load_active_or_fallback(candidate)

    recommendation = fallback.recommend((0.0,) * 15, (True,) * 9)
    assert recommendation.action is PolicyAction.STOP_SAFELY
    assert recommendation.used_safe_fallback is True
