from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import torch

from mllminal.learning.contracts import (
    ExperienceOutcome,
    ExperienceRecord,
    PolicyAction,
    PolicyDecision,
    RewardBreakdown,
    RunStatus,
)
from mllminal.learning.replay import LearningRepository
from mllminal.learning.service import CandidateTrainingService, MinimumExperienceError
from mllminal.learning.trainer import CandidateTrainingConfig, deterministic_split, reward_weights


def _repository(path: Path, *, minimum: int = 2) -> LearningRepository:
    repository = LearningRepository(path)
    repository.initialize()
    repository.update_settings(minimum_experience_count=minimum, seed=19)
    return repository


def _add_samples(repository: LearningRepository, count: int = 4) -> None:
    for sequence in range(1, count + 1):
        action = list(PolicyAction)[sequence % len(PolicyAction)]
        reward = float(sequence - 2)
        component = "verification_passed" if reward >= 0 else "task_failure"
        decision = PolicyDecision(task_id=f"task-{sequence}", selected_action=action)
        repository.save_decision(decision, decision_sequence=sequence)
        experience = ExperienceRecord(
            task_id=decision.task_id,
            decision_id=decision.id,
            idempotency_key=f"terminal-{sequence}",
            selected_action=action,
            outcome=ExperienceOutcome(terminal=True, task_failed=reward < 0),
            reward=RewardBreakdown.model_validate({component: reward, "total": reward}),
            status="ELIGIBLE",
        )
        repository.save_experience(experience, decision_sequence=sequence)
        repository.add_replay_entry(
            experience.id,
            features=(float(sequence),) + (0.0,) * 14,
            action=action,
            reward=reward,
        )


def _service(repository: LearningRepository, root: Path) -> CandidateTrainingService:
    return CandidateTrainingService(
        repository,
        root / "learning-data",
        config=CandidateTrainingConfig(seed=19, epochs=2, batch_size=2),
    )


def test_minimum_experience_rejection_is_persisted(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "state.db", minimum=3)
    _add_samples(repository, 2)

    with pytest.raises(MinimumExperienceError):
        _service(repository, tmp_path).train()

    run = repository.list_training_runs()[0]
    assert run.status is RunStatus.FAILED
    assert run.failure_reason == "minimum_experience_not_met"
    assert [event.event_type for event in repository.list_events()][
        -1
    ] == "learning.training.failed"


def test_split_and_reward_weights_are_deterministic_and_bounded() -> None:
    assert deterministic_split(5, seed=7, train_fraction=0.6) == deterministic_split(
        5, seed=7, train_fraction=0.6
    )
    weights = reward_weights(torch.tensor([-10.0, 0.0, 0.5, 99.0]))
    assert torch.all(weights >= 0)
    assert torch.all(weights <= 4)
    assert weights.tolist() == [0.0, 0.0, 0.5, 4.0]


def test_training_persists_snapshot_candidate_checkpoint_and_events(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "state.db")
    _add_samples(repository)

    result = _service(repository, tmp_path).train()
    run = repository.get_training_run(result.training_run.id)
    candidate = repository.get_policy_version(result.candidate.id)

    assert run.status is RunStatus.COMPLETED
    assert run.replay_entry_ids == result.replay_entry_ids
    assert len(run.replay_entry_ids) == 4
    assert result.checkpoint.exists()
    assert hashlib.sha256(result.checkpoint.read_bytes()).hexdigest() == candidate.checkpoint_sha256
    assert candidate.training_run_id == run.id
    assert candidate.lifecycle.value == "CANDIDATE"
    assert repository.get_promoted_policy().version == 0
    event_types = [event.event_type for event in repository.list_events()]
    assert event_types.index("learning.training.started") < event_types.index(
        "learning.training.completed"
    )


def test_same_seed_creates_identical_candidate_weights_and_different_versions(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path / "state.db")
    _add_samples(repository)
    service = _service(repository, tmp_path)

    first = service.train()
    second = service.train()
    first_payload = torch.load(first.checkpoint, map_location="cpu", weights_only=True)
    second_payload = torch.load(second.checkpoint, map_location="cpu", weights_only=True)

    assert first.candidate.version == 1
    assert second.candidate.version == 2
    assert first.training_run.replay_entry_ids == second.training_run.replay_entry_ids
    assert all(
        torch.equal(first_payload["state_dict"][key], second_payload["state_dict"][key])
        for key in first_payload["state_dict"]
    )
    assert all(
        parameter.device.type == "cpu" for parameter in result_policy(first).network.parameters()
    )


def result_policy(result: object):
    from mllminal.learning.policy import load_checkpoint

    return load_checkpoint(result.checkpoint).policy


def test_failed_training_is_persisted_without_promotion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _repository(tmp_path / "state.db")
    _add_samples(repository)
    service = _service(repository, tmp_path)

    def fail(*args: object, **kwargs: object) -> object:
        raise RuntimeError("forced training failure")

    monkeypatch.setattr("mllminal.learning.service.train_candidate", fail)
    with pytest.raises(RuntimeError, match="forced training failure"):
        service.train()

    run = repository.list_training_runs()[0]
    assert run.status is RunStatus.FAILED
    assert run.failure_reason == "training_failed"
    assert repository.get_promoted_policy().version == 0
