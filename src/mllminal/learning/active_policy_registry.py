"""Explicit, domain-scoped bindings for advisory policy artifacts."""

from __future__ import annotations

import hashlib
from pathlib import Path

from mllminal.learning.contracts import (
    ACTION_SPACE_VERSION,
    ActivePolicyBinding,
    ActivePolicyStatus,
    FallbackPolicy,
    PolicyDomain,
    PolicyVersion,
)
from mllminal.learning.replay import LearningRepository


class ActivePolicyValidationError(ValueError):
    """Raised when a candidate cannot be bound safely to a runtime domain."""


LIVE_ADVISORY_POLICY_DOMAINS: frozenset[PolicyDomain] = frozenset(
    {
        PolicyDomain.BACKEND_RANKING,
        PolicyDomain.SUGGESTION_RANKING,
        PolicyDomain.VERIFICATION_RANKING,
    }
)


class ActivePolicyRegistry:
    """Manage explicit active/shadow bindings without changing candidate lifecycle."""

    def __init__(
        self,
        repository: LearningRepository,
        artifact_root: Path,
        *,
        runtime_version: str = "runtime_v1",
    ) -> None:
        self.repository = repository
        self.artifact_root = artifact_root.resolve()
        self.runtime_version = runtime_version
        self.artifact_root.mkdir(parents=True, exist_ok=True)

    def activate(
        self,
        candidate_id: str,
        *,
        activated_by: str,
        idempotency_key: str,
        mode: ActivePolicyStatus = ActivePolicyStatus.ACTIVE,
        artifact_path: str | None = None,
        feature_schema_version: str | None = None,
        action_schema_version: str | None = None,
        advisory_weight: float = 0.2,
        confidence_threshold: float = 0.65,
        latency_budget_ms: int = 50,
    ) -> ActivePolicyBinding:
        if mode not in {ActivePolicyStatus.ACTIVE, ActivePolicyStatus.SHADOW}:
            raise ActivePolicyValidationError("binding mode must be ACTIVE or SHADOW")
        policy = self.repository.get_policy_version(candidate_id)
        if policy.version == 0 or not policy.name or not policy.checkpoint_sha256:
            raise ActivePolicyValidationError("policy candidate has no immutable artifact")
        if policy.policy_domain is None:
            raise ActivePolicyValidationError("policy candidate has no domain")
        requested_feature_schema = feature_schema_version or policy.feature_schema_version
        requested_action_schema = action_schema_version or policy.action_space_version
        path = self._safe_artifact_path(artifact_path or f"{policy.name}.pt")
        actual_digest = self._artifact_digest(path)
        try:
            if actual_digest != policy.checkpoint_sha256:
                self._persist_invalid(
                    policy, path, actual_digest, idempotency_key, "artifact digest mismatch"
                )
                raise ActivePolicyValidationError("artifact digest mismatch")
            if (
                not requested_feature_schema
                or requested_feature_schema != policy.feature_schema_version
            ):
                self._persist_invalid(
                    policy, path, actual_digest, idempotency_key, "feature schema is incompatible"
                )
                raise ActivePolicyValidationError("feature schema is incompatible")
            if requested_action_schema != policy.action_space_version:
                self._persist_invalid(
                    policy, path, actual_digest, idempotency_key, "action schema is incompatible"
                )
                raise ActivePolicyValidationError("action schema is incompatible")
            if self.runtime_version != "runtime_v1":
                self._persist_invalid(
                    policy, path, actual_digest, idempotency_key, "runtime version is incompatible"
                )
                raise ActivePolicyValidationError("runtime version is incompatible")
            if (
                mode is ActivePolicyStatus.ACTIVE
                and policy.policy_domain not in LIVE_ADVISORY_POLICY_DOMAINS
            ):
                raise ActivePolicyValidationError(
                    f"{policy.policy_domain.value} is shadow-only until "
                    "a live runtime is integrated"
                )
            binding = ActivePolicyBinding(
                policy_domain=policy.policy_domain,
                candidate_id=policy.id,
                policy_version=policy.version,
                artifact_path=path.relative_to(self.artifact_root).as_posix(),
                artifact_digest=actual_digest,
                feature_schema_version=requested_feature_schema,
                action_schema_version=requested_action_schema or ACTION_SPACE_VERSION,
                runtime_version=self.runtime_version,
                advisory_weight=advisory_weight,
                confidence_threshold=confidence_threshold,
                latency_budget_ms=latency_budget_ms,
                activated_by=activated_by,
                activated_at=None,
                fallback_policy=FallbackPolicy.DETERMINISTIC,
                status=mode,
                idempotency_key=idempotency_key,
            )
        except ActivePolicyValidationError:
            raise
        return (
            self.repository.activate_active_policy_binding(binding)[0]
            if mode is ActivePolicyStatus.ACTIVE
            else self.repository.save_active_policy_binding(binding)[0]
        )

    def get(self, binding_id: str) -> ActivePolicyBinding:
        return self.repository.get_active_policy_binding(binding_id)

    def list(self, policy_domain: PolicyDomain | None = None) -> list[ActivePolicyBinding]:
        return self.repository.list_active_policy_bindings(policy_domain)

    def active(self, policy_domain: PolicyDomain) -> ActivePolicyBinding | None:
        return self.repository.get_active_policy_binding_for_domain(policy_domain)

    def disable(
        self, policy_domain: PolicyDomain, *, reason: str, idempotency_key: str
    ) -> ActivePolicyBinding:
        return self.repository.disable_active_policy_binding(
            policy_domain, reason=reason, idempotency_key=idempotency_key
        )[0]

    def rollback(
        self, policy_domain: PolicyDomain, *, reason: str, idempotency_key: str
    ) -> ActivePolicyBinding:
        return self.repository.rollback_active_policy_binding(
            policy_domain, reason=reason, idempotency_key=idempotency_key
        )[0]

    def _persist_invalid(
        self,
        policy: PolicyVersion,
        path: Path,
        actual_digest: str,
        idempotency_key: str,
        reason: str,
    ) -> None:
        candidate = policy
        if candidate.policy_domain is None:
            return
        binding = ActivePolicyBinding(
            policy_domain=candidate.policy_domain,
            candidate_id=candidate.id,
            policy_version=candidate.version,
            artifact_path=path.relative_to(self.artifact_root).as_posix(),
            artifact_digest=actual_digest,
            feature_schema_version=candidate.feature_schema_version or "unknown",
            action_schema_version=candidate.action_space_version,
            runtime_version=self.runtime_version,
            status=ActivePolicyStatus.INVALID,
            status_reason=reason,
            idempotency_key=idempotency_key,
        )
        self.repository.save_active_policy_binding(binding)

    def _safe_artifact_path(self, artifact_path: str) -> Path:
        path = (self.artifact_root / artifact_path).resolve()
        try:
            path.relative_to(self.artifact_root)
        except ValueError as error:
            raise ActivePolicyValidationError("artifact path escapes learning directory") from error
        return path

    @staticmethod
    def _artifact_digest(path: Path) -> str:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as error:
            raise ActivePolicyValidationError("policy artifact is unavailable") from error


__all__ = [
    "LIVE_ADVISORY_POLICY_DOMAINS",
    "ActivePolicyRegistry",
    "ActivePolicyStatus",
    "ActivePolicyValidationError",
]
