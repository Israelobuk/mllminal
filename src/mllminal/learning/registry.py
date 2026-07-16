"""Checkpoint registry with explicit promotion and durable rollback."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from mllminal.learning.contracts import PolicyVersion, RollbackRecord
from mllminal.learning.evaluation import EvaluationMetrics
from mllminal.learning.policy import LoadedPolicy, load_checkpoint
from mllminal.learning.replay import LearningRepository


class PromotionGateError(ValueError):
    """Raised when deterministic promotion requirements are not satisfied."""


class PolicyRegistry:
    def __init__(self, repository: LearningRepository, checkpoint_root: Path) -> None:
        self.repository = repository
        self.checkpoint_root = checkpoint_root
        self.checkpoint_root.mkdir(parents=True, exist_ok=True)

    def register_candidate(self, checkpoint: Path, *, checkpoint_sha256: str) -> PolicyVersion:
        actual_digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
        if actual_digest != checkpoint_sha256:
            raise ValueError("checkpoint digest mismatch")
        policy = self.repository.create_policy_version(checkpoint_sha256=actual_digest)
        target = self._checkpoint_path(policy)
        shutil.copyfile(checkpoint, target)
        loaded = load_checkpoint(target)
        if loaded.policy_version != policy.name:
            target.unlink(missing_ok=True)
            self.repository.reject_policy(policy.id, reason="checkpoint policy version mismatch")
            raise ValueError("checkpoint policy version mismatch")
        return policy

    def load(self, policy: PolicyVersion) -> LoadedPolicy:
        if policy.version == 0 or policy.checkpoint_sha256 is None:
            raise ValueError("policy_v0 is a deterministic fallback without a checkpoint")
        path = self._checkpoint_path(policy)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != policy.checkpoint_sha256:
            raise ValueError("checkpoint digest mismatch")
        return load_checkpoint(path)

    def promote(
        self,
        policy_version_id: str,
        metrics: EvaluationMetrics,
        *,
        explicitly_approved: bool,
        idempotency_key: str,
    ) -> PolicyVersion:
        if not metrics.promotion_eligible:
            self.repository.reject_policy(
                policy_version_id, reason=",".join(metrics.rejection_reasons)
            )
            raise PromotionGateError("candidate is not promotion eligible")
        if not explicitly_approved:
            raise PromotionGateError("explicit approval is required")
        policy, _ = self.repository.promote_policy(
            policy_version_id,
            reason="explicitly approved after passing evaluation gates",
            idempotency_key=idempotency_key,
        )
        return policy

    def rollback(self, target_name: str, *, reason: str, idempotency_key: str) -> RollbackRecord:
        matches = [
            policy
            for policy in self.repository.list_policy_versions()
            if policy.name == target_name
        ]
        if len(matches) != 1:
            raise KeyError(target_name)
        record, _ = self.repository.rollback_policy(
            matches[0].id, reason=reason, idempotency_key=idempotency_key
        )
        return record

    def _checkpoint_path(self, policy: PolicyVersion) -> Path:
        if not policy.name:
            raise ValueError("policy version is missing a name")
        return self.checkpoint_root / f"{policy.name}.pt"
