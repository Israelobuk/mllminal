"""Bounded advisory inference for promoted backend-ranking policies."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch

from mllminal.learning.adaptive_contracts import AdaptiveBackendCandidate, AdaptiveExecutionRequest
from mllminal.learning.contracts import PolicyDomain
from mllminal.learning.offline_features import FEATURE_SCHEMA_VERSION, TrainingFeatureEncoder
from mllminal.learning.offline_training import OfflineCandidateModel, load_offline_candidate
from mllminal.learning.profile_contracts import (
    ApplicationInteractionProfile,
    BackendReliabilityRecord,
)
from mllminal.learning.replay import LearningRepository

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
    artifact_digest: str | None = None
    feature_schema_version: str | None = None
    schema_valid: bool = False
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
    """Load and run one promoted backend policy without changing lifecycle state."""

    def __init__(
        self,
        repository: LearningRepository,
        checkpoint_root: Path,
        *,
        advisory_weight: float = ADVISORY_WEIGHT,
        failure_threshold: int = FAILURE_THRESHOLD,
        max_inference_seconds: float = MAX_INFERENCE_SECONDS,
    ) -> None:
        if not 0.0 <= advisory_weight <= 0.5:
            raise ValueError("advisory weight must be between 0 and 0.5")
        self.repository = repository
        self.checkpoint_root = checkpoint_root
        self.advisory_weight = advisory_weight
        self.failure_threshold = max(1, failure_threshold)
        self.max_inference_seconds = max(0.001, max_inference_seconds)
        self._consecutive_failures = 0
        self._last_fallback_reason: str | None = None
        self._loaded: tuple[str, str, OfflineCandidateModel] | None = None

    def status(self) -> BackendPolicyStatus:
        try:
            _, status = self._load()
            return status
        except (OSError, RuntimeError, TypeError, ValueError, KeyError) as error:
            self._last_fallback_reason = str(error)[:128] or type(error).__name__
            try:
                policy = self.repository.get_promoted_policy()
            except KeyError:
                return self._status()
            return self._status(
                policy_id=policy.id,
                policy_name=policy.name,
                artifact_digest=policy.checkpoint_sha256,
                feature_schema_version=policy.feature_schema_version,
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
            features = torch.tensor(
                [
                    self._features(request, candidate, profile, records.get(candidate.backend))
                    for candidate in candidates
                ],
                dtype=torch.float32,
            )
            started = time.perf_counter()
            with torch.inference_mode():
                output = policy.network(features)
            if time.perf_counter() - started > self.max_inference_seconds:
                raise ValueError("inference_budget_exceeded")
            if output.ndim != 2 or output.shape[0] != len(candidates):
                raise ValueError("inference output shape is invalid")
            if not torch.isfinite(output).all():
                raise ValueError("inference output is not finite")
            rows = output.detach().cpu().tolist()
            if len(rows) != len(candidates) or any(
                len(row) != len(policy.action_labels) for row in rows
            ):
                raise ValueError("inference output dimensions are invalid")
            labels = dict(zip(policy.action_labels, range(len(policy.action_labels)), strict=True))
            result = {
                candidate.backend: min(max(float(rows[index][labels[candidate.backend]]), 0.0), 1.0)
                for index, candidate in enumerate(candidates)
                if candidate.backend in labels
            }
            self._consecutive_failures = 0
            self._last_fallback_reason = None
            return BackendAdvisoryResult(result, policy_status)
        except (OSError, RuntimeError, TypeError, ValueError, KeyError) as error:
            self._record_failure(str(error)[:128] or type(error).__name__)
            return BackendAdvisoryResult({}, self.status())

    def _record_failure(self, reason: str) -> None:
        self._consecutive_failures += 1
        self._last_fallback_reason = reason

    def _load(self) -> tuple[OfflineCandidateModel, BackendPolicyStatus]:
        policy = self.repository.get_promoted_policy()
        if policy.policy_domain is not PolicyDomain.BACKEND_RANKING:
            raise ValueError("active policy domain is not BACKEND_RANKING")
        if policy.version == 0 or not policy.name or not policy.checkpoint_sha256:
            raise ValueError("no promoted backend-ranking artifact")
        if policy.feature_schema_version != FEATURE_SCHEMA_VERSION:
            raise ValueError("active policy feature schema is incompatible")
        path = self.checkpoint_root / f"{policy.name}.pt"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != policy.checkpoint_sha256:
            raise ValueError("checkpoint digest mismatch")
        cache_key = (policy.id, digest)
        if self._loaded is None or self._loaded[:2] != cache_key:
            model = load_offline_candidate(path)
            encoder = TrainingFeatureEncoder.for_domain(PolicyDomain.BACKEND_RANKING)
            if model.feature_schema_version != encoder.schema_version:
                raise ValueError("artifact feature schema is incompatible")
            if model.network.layers[0].in_features != encoder.dimension:
                raise ValueError("artifact feature dimension is incompatible")
            self._loaded = (policy.id, digest, model)
        status = self._status(
            active=True,
            policy_id=policy.id,
            policy_name=policy.name,
            artifact_digest=digest,
            feature_schema_version=policy.feature_schema_version,
            schema_valid=True,
        )
        return self._loaded[2], status

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
