from pathlib import Path

import torch

from mllminal.assistance.suggestion_runtime import SuggestionPolicyRuntime
from mllminal.contracts import utc_now
from mllminal.learning.active_policy_registry import ActivePolicyRegistry
from mllminal.learning.contracts import PolicyDomain
from mllminal.learning.offline_features import TrainingFeatureEncoder
from mllminal.learning.offline_training import (
    OfflineCandidateModel,
    OfflinePolicyNetwork,
    save_offline_candidate,
)
from mllminal.learning.replay import LearningRepository
from mllminal.mining.contracts import MinedStep, WorkflowCandidate


def test_suggestion_runtime_loads_active_domain_artifact_and_scores_present_action(
    tmp_path: Path,
) -> None:
    repository = LearningRepository(tmp_path / "learning.db")
    repository.initialize()
    encoder = TrainingFeatureEncoder.for_domain(PolicyDomain.SUGGESTION_RANKING)
    network = OfflinePolicyNetwork(encoder.dimension, 2, 4).cpu()
    with torch.no_grad():
        network.layers[0].weight.zero_()
        network.layers[0].bias.zero_()
        network.layers[2].weight.zero_()
        network.layers[2].bias.copy_(torch.tensor([5.0, -5.0]))
    policy = repository.create_policy_version(
        checkpoint_sha256=None,
        policy_domain=PolicyDomain.SUGGESTION_RANKING,
        feature_schema_version=encoder.schema_version,
    )
    artifact = tmp_path / "checkpoints" / f"{policy.name}.pt"
    digest = save_offline_candidate(
        OfflineCandidateModel(network, ("present", "defer"), encoder.schema_version),
        artifact,
    )
    policy = repository.update_policy_checkpoint(policy.id, digest)
    repository.promote_policy(policy.id, reason="test", idempotency_key="promote-suggestion")
    ActivePolicyRegistry(repository, tmp_path / "checkpoints").activate(
        policy.id,
        activated_by="test",
        idempotency_key="activate-suggestion",
    )
    candidate = WorkflowCandidate(
        id="candidate-1",
        application="explorer",
        steps=[
            MinedStep(application="explorer", kind="control.invoked"),
            MinedStep(application="explorer", kind="control.invoked"),
        ],
        occurrences=6,
        confidence=0.9,
        first_seen=utc_now(),
        last_seen=utc_now(),
        source_event_ids=["event-1"],
    )

    result = SuggestionPolicyRuntime(repository, tmp_path / "checkpoints").evaluate(
        candidate,
        verification_available=True,
        rejection_count=0,
    )

    assert result.score > 0.9
    assert result.provenance["active"] is True
    assert result.provenance["policy_domain"] == PolicyDomain.SUGGESTION_RANKING.value
