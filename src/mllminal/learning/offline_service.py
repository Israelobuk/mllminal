"""Durable orchestration for offline policy replay data."""

from __future__ import annotations

from pathlib import Path

from mllminal.learning.contracts import PolicyDomain, ReplaySnapshot
from mllminal.learning.offline import materialize_replay_snapshot
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
