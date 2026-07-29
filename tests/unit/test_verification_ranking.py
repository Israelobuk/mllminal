from pathlib import Path

import torch

from mllminal.learning.active_policy_registry import ActivePolicyRegistry
from mllminal.learning.contracts import PolicyDomain
from mllminal.learning.offline_features import TrainingFeatureEncoder
from mllminal.learning.offline_training import (
    OfflineCandidateModel,
    OfflinePolicyNetwork,
    save_offline_candidate,
)
from mllminal.learning.profile_contracts import VerificationMethodCandidate
from mllminal.learning.replay import LearningRepository
from mllminal.learning.verification_runtime import (
    VerificationAdvisoryResult,
    VerificationRankingService,
)


def _candidate(method: str, score: float, *, eligible: bool = True) -> VerificationMethodCandidate:
    return VerificationMethodCandidate(
        method=method,
        deterministic_score=score,
        available=True,
        eligible=eligible,
    )


class _AdvisoryRuntime:
    advisory_weight = 0.2

    def evaluate(self, methods, context_features):
        return VerificationAdvisoryResult(
            scores={method: 0.95 if method == "visual.state" else 0.05 for method in methods},
            provenance={"active": True, "policy_domain": PolicyDomain.VERIFICATION_RANKING.value},
        )


def test_verification_advisory_ranks_only_eligible_methods_and_persists_provenance(
    tmp_path: Path,
) -> None:
    repository = LearningRepository(tmp_path / "learning.db")
    repository.initialize()
    service = VerificationRankingService(repository, policy_runtime=_AdvisoryRuntime())

    decision = service.rank(
        [
            _candidate("state.verify", 0.8),
            _candidate("visual.state", 0.6),
            _candidate("unsafe.untrusted", 1.0, eligible=False),
        ],
        profile_id="profile-1",
        context_features={"verification_availability": 1.0},
    )

    assert decision.selected_method == "visual.state"
    assert decision.ordered_methods == ["visual.state", "state.verify"]
    assert "unsafe.untrusted" not in decision.combined_scores
    assert decision.advisory_policy["used_in_ranking"] is True
    assert decision.verification_authoritative is True
    assert repository.list_verification_rankings()[0].explanation == decision.explanation


def test_promoted_verification_policy_is_bounded_and_domain_validated(tmp_path: Path) -> None:
    repository = LearningRepository(tmp_path / "learning.db")
    repository.initialize()
    encoder = TrainingFeatureEncoder.for_domain(PolicyDomain.VERIFICATION_RANKING)
    network = OfflinePolicyNetwork(encoder.dimension, 2, 4).cpu()
    with torch.no_grad():
        network.layers[0].weight.zero_()
        network.layers[0].bias.zero_()
        network.layers[2].weight.zero_()
        network.layers[2].bias.copy_(torch.tensor([5.0, -5.0]))
    policy = repository.create_policy_version(
        checkpoint_sha256=None,
        policy_domain=PolicyDomain.VERIFICATION_RANKING,
        feature_schema_version=encoder.schema_version,
    )
    artifact = tmp_path / "checkpoints" / f"{policy.name}.pt"
    digest = save_offline_candidate(
        OfflineCandidateModel(network, ("visual.state", "state.verify"), encoder.schema_version),
        artifact,
    )
    policy = repository.update_policy_checkpoint(policy.id, digest)
    repository.promote_policy(policy.id, reason="test", idempotency_key="promote-verification")
    ActivePolicyRegistry(repository, tmp_path / "checkpoints").activate(
        policy.id,
        activated_by="test",
        idempotency_key="activate-verification",
    )

    service = VerificationRankingService(repository, tmp_path / "checkpoints")
    decision = service.rank(
        [_candidate("visual.state", 0.8), _candidate("state.verify", 0.7)],
        context_features={"verification_availability": 1.0},
    )

    assert decision.selected_method == "visual.state"
    assert decision.advisory_scores["visual.state"] > 0.9
    assert decision.advisory_policy["policy_domain"] == PolicyDomain.VERIFICATION_RANKING.value
    assert decision.advisory_policy["advisory_only"] is True


def test_verification_policy_failure_falls_back_to_deterministic_ranking(tmp_path: Path) -> None:
    repository = LearningRepository(tmp_path / "learning.db")
    repository.initialize()

    class BrokenRuntime:
        advisory_weight = 0.2

        def evaluate(self, *_args, **_kwargs):
            raise RuntimeError("inference failed")

    decision = VerificationRankingService(repository, policy_runtime=BrokenRuntime()).rank(
        [_candidate("state.verify", 0.8), _candidate("visual.state", 0.6)]
    )

    assert decision.selected_method == "state.verify"
    assert decision.advisory_scores == {}
    assert decision.combined_scores == decision.deterministic_scores
    assert decision.advisory_policy["used_in_ranking"] is False
    assert "inference failed" not in decision.explanation
