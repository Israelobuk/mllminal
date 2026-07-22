"""Durable orchestration for offline policy replay data and advisory candidates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from mllminal.learning.contracts import (
    PolicyDomain,
    PolicyLifecycle,
    PolicyVersion,
    ReplaySnapshot,
    RunStatus,
    TrainingRun,
    utc_now,
)
from mllminal.learning.offline import materialize_replay_snapshot
from mllminal.learning.offline_features import TrainingFeatureEncoder
from mllminal.learning.offline_training import OfflineTrainingConfig
from mllminal.learning.offline_worker import TrainingWorkerResult, run_isolated_training
from mllminal.learning.replay import LearningRepository


class OfflinePolicyDataService:
    """Build immutable domain snapshots from already-minimized durable experiences."""

    def __init__(self, repository: LearningRepository, root: Path) -> None:
        self.repository = repository
        self.root = root

    def snapshot(self, policy_domain: PolicyDomain, *, seed: int) -> ReplaySnapshot:
        """Materialize and durably register one immutable local Parquet snapshot."""

        snapshot = materialize_replay_snapshot(
            self.repository.list_training_experiences(policy_domain),
            policy_domain=policy_domain,
            seed=seed,
            root=self.root / "snapshots",
        )
        return self.repository.save_replay_snapshot(snapshot)


@dataclass(frozen=True)
class OfflineTrainingJobResult:
    snapshot: ReplaySnapshot
    training_run: TrainingRun
    candidate: PolicyVersion
    worker: TrainingWorkerResult


class OfflinePolicyTrainingService:
    """Persist a CPU-trained advisory candidate without promoting it."""

    def __init__(self, repository: LearningRepository, root: Path) -> None:
        self.repository = repository
        self.root = root
        self.data = OfflinePolicyDataService(repository, root)

    def train(
        self,
        policy_domain: PolicyDomain,
        config: OfflineTrainingConfig,
        *,
        timeout_seconds: float,
    ) -> OfflineTrainingJobResult:
        """Create a snapshot, run isolated CPU training, and durably record its candidate."""

        experiences = self.repository.list_training_experiences(policy_domain)
        snapshot = self.data.snapshot(policy_domain, seed=config.seed)
        run = TrainingRun(
            status=RunStatus.RUNNING,
            seed=config.seed,
            eligible_experience_count=snapshot.experience_count,
            lifecycle_stage="TRAINING",
            started_at=utc_now(),
        )
        self.repository.save_training_run(run)
        self.repository.append_event(
            "learning.offline_training.started",
            {"training_run_id": run.id, "snapshot_id": snapshot.snapshot_id},
        )
        candidate = self.repository.create_policy_version(
            checkpoint_sha256=None,
            training_run_id=run.id,
            policy_domain=policy_domain,
            replay_snapshot_id=snapshot.snapshot_id,
            feature_schema_version=snapshot.feature_schema_version,
            training_config=asdict(config),
            training_seed=config.seed,
            parent_policy_id=self.repository.get_promoted_policy().id,
            lifecycle=PolicyLifecycle.TRAINING,
        )
        checkpoint = self.root / "checkpoints" / f"{candidate.name}.pt"
        worker = run_isolated_training(
            experiences,
            TrainingFeatureEncoder.for_domain(policy_domain),
            config,
            timeout_seconds=timeout_seconds,
            checkpoint_path=checkpoint,
        )
        if worker.status != "COMPLETED" or worker.checkpoint_sha256 is None:
            failed = run.model_copy(
                update={
                    "status": RunStatus.FAILED,
                    "failure_reason": worker.failure_reason or "offline_training_failed",
                    "completed_at": utc_now(),
                }
            )
            self.repository.update_training_run(failed)
            candidate = self.repository.update_offline_candidate(
                candidate.id,
                lifecycle=PolicyLifecycle.FAILED,
            )
            self.repository.append_event(
                "learning.offline_training.failed",
                {"training_run_id": run.id, "candidate_policy_id": candidate.id},
            )
            return OfflineTrainingJobResult(snapshot, failed, candidate, worker)

        candidate = self.repository.update_policy_checkpoint(candidate.id, worker.checkpoint_sha256)
        candidate = self.repository.update_offline_candidate(
            candidate.id,
            lifecycle=PolicyLifecycle.TRAINED,
        )
        completed = run.model_copy(
            update={
                "status": RunStatus.COMPLETED,
                "lifecycle_stage": "EVALUATING",
                "completed_at": utc_now(),
            }
        )
        self.repository.update_training_run(completed)
        self.repository.append_event(
            "learning.offline_training.completed",
            {"training_run_id": run.id, "candidate_policy_id": candidate.id},
        )
        return OfflineTrainingJobResult(snapshot, completed, candidate, worker)
