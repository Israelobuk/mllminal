"""Durable candidate-policy training lifecycle orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mllminal.learning.contracts import PolicyVersion, RunStatus, TrainingRun, utc_now
from mllminal.learning.policy import (
    ActionPolicy,
    PolicyCheckpointError,
    load_checkpoint,
    save_checkpoint,
)
from mllminal.learning.replay import LearningRepository
from mllminal.learning.trainer import CandidateTrainingConfig, train_candidate


class MinimumExperienceError(ValueError):
    """Raised after a durable failed run when replay is below the configured threshold."""


@dataclass(frozen=True)
class CandidateTrainingServiceResult:
    training_run: TrainingRun
    candidate: PolicyVersion
    checkpoint: Path
    replay_entry_ids: tuple[int, ...]


class CandidateTrainingService:
    """Create candidates from frozen durable replay without ever promoting them."""

    def __init__(
        self,
        repository: LearningRepository,
        data_directory: Path,
        *,
        config: CandidateTrainingConfig | None = None,
    ) -> None:
        self.repository = repository
        self.data_directory = data_directory
        self.config = config or CandidateTrainingConfig(seed=repository.get_settings().seed)

    def train(self) -> CandidateTrainingServiceResult:
        settings = self.repository.get_settings()
        samples = self.repository.sample_replay(
            self.repository.count_replay_entries(), seed=self.config.seed, reward_balanced=False
        )
        replay_entry_ids = tuple(sample.replay_entry_id for sample in samples)
        run = TrainingRun(
            status=RunStatus.RUNNING,
            seed=self.config.seed,
            eligible_experience_count=settings.eligible_experience_count,
            replay_entry_ids=replay_entry_ids,
            lifecycle_stage="COLLECTING",
            started_at=utc_now(),
        )
        self.repository.save_training_run(run)
        self.repository.append_event(
            "learning.training.started", {"training_run_id": run.id, "eligible_count": len(samples)}
        )
        if len(samples) < settings.minimum_experience_count:
            failed = run.model_copy(
                update={
                    "status": RunStatus.FAILED,
                    "failure_reason": "minimum_experience_not_met",
                    "completed_at": utc_now(),
                }
            )
            self.repository.update_training_run(failed)
            self.repository.append_event(
                "learning.training.failed",
                {"training_run_id": run.id, "reason": "minimum_experience_not_met"},
            )
            raise MinimumExperienceError("minimum eligible experience threshold is not met")

        try:
            candidate = self.repository.create_policy_version(
                checkpoint_sha256=None, training_run_id=run.id
            )
            trained = train_candidate(
                samples,
                self.config,
                initial_policy=self._promoted_policy(),
            )
            checkpoint = self.data_directory / "checkpoints" / f"{candidate.name}.pt"
            digest = save_checkpoint(
                trained.policy,
                checkpoint,
                policy_version=candidate.name or "candidate",
            )
            candidate = self.repository.update_policy_checkpoint(candidate.id, digest)
            completed = run.model_copy(
                update={
                    "status": RunStatus.COMPLETED,
                    "lifecycle_stage": "EVALUATING",
                    "completed_at": utc_now(),
                }
            )
            self.repository.update_training_run(completed)
            self.repository.append_event(
                "learning.training.completed",
                {"training_run_id": run.id, "candidate_policy_id": candidate.id},
            )
            return CandidateTrainingServiceResult(
                training_run=completed,
                candidate=candidate,
                checkpoint=checkpoint,
                replay_entry_ids=replay_entry_ids,
            )
        except Exception:
            failed = run.model_copy(
                update={
                    "status": RunStatus.FAILED,
                    "lifecycle_stage": "TRAINING",
                    "failure_reason": "training_failed",
                    "completed_at": utc_now(),
                }
            )
            self.repository.update_training_run(failed)
            self.repository.append_event(
                "learning.training.failed", {"training_run_id": run.id, "reason": "training_failed"}
            )
            raise

    def _promoted_policy(self) -> ActionPolicy | None:
        promoted = self.repository.get_promoted_policy()
        if promoted.checkpoint_sha256 is None or not promoted.name:
            return None
        checkpoint = self.data_directory / "checkpoints" / f"{promoted.name}.pt"
        try:
            return load_checkpoint(checkpoint).policy
        except PolicyCheckpointError:
            return None
