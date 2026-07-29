"""Bounded advisory verification-method ranking with deterministic authority."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from mllminal.learning.active_policy_registry import ActivePolicyRegistry
from mllminal.learning.contracts import PolicyDomain
from mllminal.learning.offline_features import TrainingFeatureEncoder
from mllminal.learning.profile_contracts import (
    VerificationMethodCandidate,
    VerificationRankingDecision,
)
from mllminal.learning.replay import LearningRepository
from mllminal.learning.runtime_adapter import (
    ActivePolicyRuntimeAdapter,
    RuntimePolicyUnavailable,
)


@dataclass(frozen=True)
class VerificationAdvisoryResult:
    scores: dict[str, float]
    provenance: dict[str, Any]


class VerificationPolicyRuntime:
    """Run a promoted VERIFICATION_RANKING policy as score-only advice."""

    advisory_weight = 0.2

    def __init__(self, repository: LearningRepository, checkpoint_root: Path) -> None:
        encoder = TrainingFeatureEncoder.for_domain(PolicyDomain.VERIFICATION_RANKING)
        self.encoder = encoder
        self.adapter = ActivePolicyRuntimeAdapter(
            ActivePolicyRegistry(repository, checkpoint_root),
            checkpoint_root,
            policy_domain=PolicyDomain.VERIFICATION_RANKING,
            expected_feature_schema_version=encoder.schema_version,
            expected_input_dimension=encoder.dimension,
        )

    def evaluate(
        self,
        methods: Sequence[str],
        context_features: Mapping[str, float],
    ) -> VerificationAdvisoryResult:
        features = self.encoder.encode_mapping(dict(context_features))
        loaded = self.adapter.load()
        rows = self.adapter.infer([features])
        labels = dict(zip(loaded.model.action_labels, rows[0], strict=True))
        scores = {method: labels[method] for method in methods if method in labels}
        if not scores:
            raise RuntimePolicyUnavailable("verification policy has no matching method labels")
        provenance = self.adapter.status().as_dict()
        provenance["used_in_ranking"] = True
        return VerificationAdvisoryResult(scores=scores, provenance=provenance)


class VerificationRankingService:
    """Rank eligible verification methods without performing verification."""

    def __init__(
        self,
        repository: LearningRepository,
        checkpoint_root: Path | None = None,
        *,
        policy_runtime: VerificationPolicyRuntime | Any | None = None,
    ) -> None:
        self.repository = repository
        root = checkpoint_root or repository.database_path.parent / "learning" / "checkpoints"
        self.policy_runtime = policy_runtime or VerificationPolicyRuntime(repository, root)

    def rank(
        self,
        candidates: Iterable[VerificationMethodCandidate],
        *,
        profile_id: str | None = None,
        context_features: Mapping[str, float] | None = None,
    ) -> VerificationRankingDecision:
        values = list(candidates)
        if len(values) > 32:
            raise ValueError("verification method ranking is limited to 32 candidates")
        methods = [candidate.method for candidate in values]
        if len(set(methods)) != len(methods):
            raise ValueError("verification method names must be unique")
        eligible = [candidate for candidate in values if candidate.available and candidate.eligible]
        deterministic = {
            candidate.method: round(candidate.deterministic_score, 6) for candidate in eligible
        }
        advisory: dict[str, float] = {}
        policy: dict[str, Any] = {
            "active": False,
            "advisory_only": True,
            "used_in_ranking": False,
        }
        try:
            if eligible:
                result = self.policy_runtime.evaluate(
                    [candidate.method for candidate in eligible], context_features or {}
                )
                advisory = {
                    method: round(score, 6)
                    for method, score in result.scores.items()
                    if method in deterministic
                }
                policy = dict(result.provenance)
                policy["advisory_only"] = True
                policy["used_in_ranking"] = bool(advisory)
        except (RuntimePolicyUnavailable, OSError, RuntimeError, TypeError, ValueError):
            policy = {
                "active": False,
                "advisory_only": True,
                "used_in_ranking": False,
                "fallback_reason": "verification advisory unavailable",
            }
        weight = getattr(self.policy_runtime, "advisory_weight", 0.2) if advisory else 0.0
        combined = {
            method: round(
                ((1.0 - weight) * deterministic[method])
                + (weight * advisory.get(method, deterministic[method])),
                6,
            )
            for method in deterministic
        }
        ordered = sorted(
            combined,
            key=lambda method: (-combined[method], -deterministic[method], method),
        )
        explanation = [
            "Only available and independently eligible verification methods were ranked.",
            "The selected method is advisory ordering only; "
            "deterministic verification remains authoritative.",
        ]
        if advisory:
            explanation.append(f"Applied bounded advisory scores at weight {weight:.2f}.")
        else:
            explanation.append(
                "Used deterministic ranking because advisory inference was unavailable."
            )
        decision = VerificationRankingDecision(
            profile_id=profile_id,
            selected_method=ordered[0] if ordered else None,
            ordered_methods=ordered,
            deterministic_scores=deterministic,
            advisory_scores=advisory,
            combined_scores=combined,
            advisory_policy=policy,
            explanation=explanation,
        )
        return self.repository.save_verification_ranking(decision)

    def policy_status(self) -> dict[str, Any]:
        adapter = getattr(self.policy_runtime, "adapter", None)
        if adapter is None:
            return {
                "policy_domain": PolicyDomain.VERIFICATION_RANKING.value,
                "active": False,
                "advisory_only": True,
                "fallback_reason": "verification policy runtime unavailable",
            }
        return cast(dict[str, Any], adapter.status().as_dict())


__all__ = [
    "VerificationAdvisoryResult",
    "VerificationPolicyRuntime",
    "VerificationRankingService",
]
