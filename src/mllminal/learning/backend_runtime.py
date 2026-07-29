"""Bounded advisory inference for explicitly active backend-ranking policies."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mllminal.learning.active_policy_registry import ActivePolicyRegistry
from mllminal.learning.adaptive_contracts import AdaptiveBackendCandidate, AdaptiveExecutionRequest
from mllminal.learning.contracts import ActivePolicyStatus, PolicyDomain
from mllminal.learning.offline_features import FEATURE_SCHEMA_VERSION, TrainingFeatureEncoder
from mllminal.learning.offline_training import OfflineCandidateModel
from mllminal.learning.profile_contracts import (
    ApplicationInteractionProfile,
    BackendReliabilityRecord,
)
from mllminal.learning.replay import LearningRepository
from mllminal.learning.runtime_adapter import (
    ActivePolicyRuntimeAdapter,
    RuntimePolicyUnavailable,
)

ADVISORY_WEIGHT = 0.20
MAX_CANDIDATES = 32
MAX_INFERENCE_SECONDS = 0.050
FAILURE_THRESHOLD = 3


@dataclass(frozen=True)
class BackendPolicyStatus:
    policy_domain: str = PolicyDomain.BACKEND_RANKING.value
    active: bool = False
    advisory_only: bool = True
    policy_id: str | None = None
    policy_name: str | None = None
    binding_id: str | None = None
    artifact_digest: str | None = None
    feature_schema_version: str | None = None
    schema_valid: bool = False
    shadow: bool = False
    circuit_open: bool = False
    consecutive_failures: int = 0
    failure_threshold: int = FAILURE_THRESHOLD
    advisory_weight: float = ADVISORY_WEIGHT
    last_fallback_reason: str | None = None
    automatic_promotion_enabled: bool = False
    automatic_retraining_enabled: bool = False

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class BackendAdvisoryResult:
    scores: dict[str, float]
    provenance: BackendPolicyStatus


class BackendPolicyRuntime:
    """Run one active backend policy without changing lifecycle state."""

    def __init__(
        self,
        repository: LearningRepository,
        checkpoint_root: Path,
        *,
        advisory_weight: float = ADVISORY_WEIGHT,
        failure_threshold: int = FAILURE_THRESHOLD,
        max_inference_seconds: float = MAX_INFERENCE_SECONDS,
        shadow_mode: bool = False,
    ) -> None:
        if not 0.0 <= advisory_weight <= 0.5:
            raise ValueError("advisory weight must be between 0 and 0.5")
        self.repository = repository
        self.checkpoint_root = checkpoint_root
        self.advisory_weight = advisory_weight
        self.failure_threshold = max(1, failure_threshold)
        self.max_inference_seconds = max(0.001, max_inference_seconds)
        self.shadow_mode = shadow_mode
        self._consecutive_failures = 0
        self._last_fallback_reason: str | None = None
        encoder = TrainingFeatureEncoder.for_domain(PolicyDomain.BACKEND_RANKING)
        self.adapter = ActivePolicyRuntimeAdapter(
            ActivePolicyRegistry(repository, checkpoint_root),
            checkpoint_root,
            policy_domain=PolicyDomain.BACKEND_RANKING,
            expected_feature_schema_version=FEATURE_SCHEMA_VERSION,
            expected_input_dimension=encoder.dimension,
            max_rows=MAX_CANDIDATES,
            max_inference_seconds=self.max_inference_seconds,
            allow_shadow=shadow_mode,
        )

    def status(self) -> BackendPolicyStatus:
        try:
            _, status = self._load()
            return status
        except (
            OSError,
            RuntimeError,
            RuntimePolicyUnavailable,
            TypeError,
            ValueError,
            KeyError,
        ) as error:
            self._last_fallback_reason = str(error)[:128] or type(error).__name__
            adapter_status = self.adapter.status()
            self._last_fallback_reason = self._normalize_fallback_reason(
                adapter_status.fallback_reason or self._last_fallback_reason
            )
            return self._status(
                active=adapter_status.active,
                policy_id=adapter_status.candidate_id,
                policy_name=self._policy_name(adapter_status.candidate_id),
                binding_id=adapter_status.binding_id,
                artifact_digest=adapter_status.artifact_digest,
                feature_schema_version=adapter_status.feature_schema_version,
                schema_valid=adapter_status.schema_valid,
                shadow=adapter_status.shadow,
            )

    def evaluate(
        self,
        request: AdaptiveExecutionRequest,
        candidates: list[AdaptiveBackendCandidate],
        profile: ApplicationInteractionProfile,
        records: dict[str, BackendReliabilityRecord],
    ) -> BackendAdvisoryResult:
        if not candidates:
            return BackendAdvisoryResult({}, self.status())
        if len(candidates) > MAX_CANDIDATES:
            self._record_failure("candidate_budget_exceeded")
            return BackendAdvisoryResult({}, self.status())
        if self._consecutive_failures >= self.failure_threshold:
            self._last_fallback_reason = "circuit_open"
            return BackendAdvisoryResult({}, self.status())
        try:
            policy, policy_status = self._load()
            feature_rows = [
                self._features(request, candidate, profile, records.get(candidate.backend))
                for candidate in candidates
            ]
            rows = self.adapter.infer(feature_rows)
            labels = dict(zip(policy.action_labels, range(len(policy.action_labels)), strict=True))
            result = {
                candidate.backend: rows[index][labels[candidate.backend]]
                for index, candidate in enumerate(candidates)
                if candidate.backend in labels
            }
            self._consecutive_failures = 0
            self._last_fallback_reason = None
            return BackendAdvisoryResult(result, policy_status)
        except (
            OSError,
            RuntimeError,
            RuntimePolicyUnavailable,
            TypeError,
            ValueError,
            KeyError,
        ) as error:
            self._record_failure(str(error)[:128] or type(error).__name__)
            return BackendAdvisoryResult({}, self.status())

    def _record_failure(self, reason: str) -> None:
        self._consecutive_failures += 1
        self._last_fallback_reason = reason

    def _load(self) -> tuple[OfflineCandidateModel, BackendPolicyStatus]:
        loaded = self.adapter.load()
        binding = loaded.binding
        policy = self.repository.get_policy_version(binding.candidate_id)
        status = self._status(
            active=binding.status is ActivePolicyStatus.ACTIVE,
            shadow=binding.status is ActivePolicyStatus.SHADOW,
            policy_id=policy.id,
            policy_name=policy.name,
            binding_id=binding.binding_id,
            artifact_digest=binding.artifact_digest,
            feature_schema_version=binding.feature_schema_version,
            schema_valid=True,
        )
        return loaded.model, status

    def _status(self, **overrides: Any) -> BackendPolicyStatus:
        return BackendPolicyStatus(
            advisory_weight=self.advisory_weight,
            failure_threshold=self.failure_threshold,
            circuit_open=self._consecutive_failures >= self.failure_threshold,
            consecutive_failures=self._consecutive_failures,
            last_fallback_reason=self._last_fallback_reason,
            **overrides,
        )

    @staticmethod
    def _normalize_fallback_reason(reason: str) -> str:
        return reason.replace("artifact digest mismatch", "checkpoint digest mismatch")

    def _policy_name(self, policy_id: str | None) -> str | None:
        if policy_id is None:
            return None
        try:
            return self.repository.get_policy_version(policy_id).name
        except KeyError:
            return None

    @staticmethod
    def _features(
        request: AdaptiveExecutionRequest,
        candidate: AdaptiveBackendCandidate,
        profile: ApplicationInteractionProfile,
        record: BackendReliabilityRecord | None,
    ) -> tuple[float, ...]:
        attempts = profile.successful_execution_count + profile.failed_execution_count
        profile_reliability = profile.successful_execution_count / attempts if attempts else 0.0
        return TrainingFeatureEncoder.for_domain(PolicyDomain.BACKEND_RANKING).encode_mapping(
            {
                "application_profile_reliability": profile_reliability,
                "backend_success_rate": record.reliability if record else 0.0,
                "backend_failure_recency": float(
                    record is not None
                    and record.last_outcome is not None
                    and record.last_outcome.value == "failed"
                ),
                "target_stability": float(
                    request.target_signature.removeprefix("automation_id:")
                    in profile.stable_automation_ids
                ),
                "verification_availability": float(candidate.verification_available),
                "consequence_class": candidate.consequence_risk,
                "provider_availability": float(candidate.available),
                "fragility": max(candidate.fragility, record.fragility if record else 0.0),
                "approval_burden": 0.0,
                "recent_emergency_stop": 0.0,
                "active_workflow_state": 0.0,
                "workflow_complexity": 0.0,
                "correction_rate": 0.0,
                "rollback_rate": 0.0,
                "interruption_cost": 0.0,
            }
        )


__all__ = ["BackendAdvisoryResult", "BackendPolicyRuntime", "BackendPolicyStatus"]
