from pathlib import Path

from mllminal.learning.contracts import PolicyDomain
from mllminal.learning.replay import LearningRepository
from mllminal.learning.status import PolicyRuntimeStatusService


def test_runtime_status_audits_live_and_shadow_only_domains(tmp_path: Path) -> None:
    repository = LearningRepository(tmp_path / "learning.db")
    repository.initialize()

    snapshot = PolicyRuntimeStatusService(repository, tmp_path / "checkpoints").snapshot()

    domains = snapshot["domains"]
    assert set(domains) == {domain.value for domain in PolicyDomain}
    assert domains[PolicyDomain.BACKEND_RANKING.value]["shadow_only"] is False
    assert domains[PolicyDomain.SUGGESTION_RANKING.value]["shadow_only"] is False
    assert domains[PolicyDomain.VERIFICATION_RANKING.value]["shadow_only"] is False
    assert domains[PolicyDomain.REPAIR_RANKING.value]["shadow_only"] is True
    assert domains[PolicyDomain.CLARIFICATION_POLICY.value]["active"] is False
    assert snapshot["deterministic_safety_authoritative"] is True
    assert snapshot["online_training_enabled"] is False
    assert snapshot["automatic_promotion_enabled"] is False
