from pathlib import Path

import pytest

from mllminal.learning.active_policy_registry import ActivePolicyRegistry
from mllminal.learning.contracts import PolicyDomain
from mllminal.learning.offline_features import TrainingFeatureEncoder
from mllminal.learning.offline_training import (
    OfflineCandidateModel,
    OfflinePolicyNetwork,
    save_offline_candidate,
)
from mllminal.learning.replay import LearningRepository
from mllminal.learning.runtime_adapter import (
    ActivePolicyRuntimeAdapter,
    RuntimePolicyUnavailable,
)


def _runtime(tmp_path: Path) -> ActivePolicyRuntimeAdapter:
    repository = LearningRepository(tmp_path / "learning.db")
    repository.initialize()
    encoder = TrainingFeatureEncoder.for_domain(PolicyDomain.BACKEND_RANKING)
    network = OfflinePolicyNetwork(encoder.dimension, 2, 4).cpu()
    artifact = tmp_path / "checkpoints" / "policy_v1.pt"
    digest = save_offline_candidate(
        OfflineCandidateModel(network, ("windows.uia", "local.vision"), encoder.schema_version),
        artifact,
    )
    policy = repository.create_policy_version(
        checkpoint_sha256=None,
        policy_domain=PolicyDomain.BACKEND_RANKING,
        feature_schema_version=encoder.schema_version,
    )
    artifact.rename(tmp_path / "checkpoints" / f"{policy.name}.pt")
    policy = repository.update_policy_checkpoint(policy.id, digest)
    repository.promote_policy(policy.id, reason="test approval", idempotency_key="test-promote")
    registry = ActivePolicyRegistry(repository, tmp_path / "checkpoints")
    registry.activate(
        policy.id,
        activated_by="test",
        idempotency_key="activate-runtime-adapter",
    )
    return ActivePolicyRuntimeAdapter(
        registry,
        tmp_path / "checkpoints",
        policy_domain=PolicyDomain.BACKEND_RANKING,
        expected_feature_schema_version=encoder.schema_version,
        expected_input_dimension=encoder.dimension,
    )


def test_runtime_adapter_loads_active_binding_and_runs_bounded_cpu_inference(
    tmp_path: Path,
) -> None:
    adapter = _runtime(tmp_path)
    rows = adapter.infer([[0.0] * 15, [1.0] * 15])

    assert len(rows) == 2
    assert all(len(row) == 2 for row in rows)
    assert all(0.0 <= score <= 1.0 for row in rows for score in row)
    status = adapter.status()
    assert status.active is True
    assert status.schema_valid is True
    assert status.policy_domain == PolicyDomain.BACKEND_RANKING.value
    assert status.automatic_promotion_enabled is False
    assert status.automatic_retraining_enabled is False


def test_runtime_adapter_falls_back_without_active_binding(tmp_path: Path) -> None:
    repository = LearningRepository(tmp_path / "learning.db")
    repository.initialize()
    encoder = TrainingFeatureEncoder.for_domain(PolicyDomain.BACKEND_RANKING)
    adapter = ActivePolicyRuntimeAdapter(
        ActivePolicyRegistry(repository, tmp_path / "checkpoints"),
        tmp_path / "checkpoints",
        policy_domain=PolicyDomain.BACKEND_RANKING,
        expected_feature_schema_version=encoder.schema_version,
        expected_input_dimension=encoder.dimension,
    )

    with pytest.raises(RuntimePolicyUnavailable, match="no active policy binding"):
        adapter.load()

    status = adapter.status()
    assert status.active is False
    assert status.fallback_reason == "no active policy binding"


def test_runtime_adapter_rejects_tampered_artifact_and_schema_mismatch(tmp_path: Path) -> None:
    adapter = _runtime(tmp_path)
    artifact = next((tmp_path / "checkpoints").glob("policy_v*.pt"))
    artifact.write_bytes(artifact.read_bytes() + b"tampered")

    with pytest.raises(RuntimePolicyUnavailable, match="artifact digest mismatch"):
        adapter.load()

    assert adapter.status().schema_valid is False
    assert adapter.status().fallback_reason == "artifact digest mismatch"


def test_runtime_adapter_enforces_row_and_latency_budgets(tmp_path: Path) -> None:
    adapter = _runtime(tmp_path)
    adapter.max_rows = 1

    with pytest.raises(RuntimePolicyUnavailable, match="inference row budget exceeded"):
        adapter.infer([[0.0] * 15, [0.0] * 15])
