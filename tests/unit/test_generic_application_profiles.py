from pathlib import Path

from mllminal.interaction.contracts import InteractionEvent, InteractionKind, SemanticTarget
from mllminal.learning.profile_contracts import ProfileCapability
from mllminal.learning.profiles import ApplicationInteractionProfileService
from mllminal.learning.replay import LearningRepository


def _service(path: Path) -> ApplicationInteractionProfileService:
    repository = LearningRepository(path)
    repository.initialize()
    return ApplicationInteractionProfileService(repository)


def test_profile_persists_generic_capabilities_for_an_unknown_application(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path / "learning.db")
    profile = service.observe_interaction(
        InteractionEvent(
            kind=InteractionKind.CONTROL_INVOKED,
            target=SemanticTarget(
                application="Acme Ledger",
                window="Ledger workspace",
                control_role="grid",
                control_name="Transactions",
            ),
        )
    )

    assert profile is not None
    updated = service.record_capabilities(
        profile.profile_id,
        [
            ProfileCapability(
                name="table.read",
                provider="windows.uia",
                surface="desktop",
                confidence=0.9,
            ),
            ProfileCapability(
                name="document.export",
                provider="native.provider",
                surface="desktop",
                consequence="reversible",
                confidence=0.8,
            ),
        ],
        source="bounded.discovery",
    )

    assert [item.name for item in updated.discovered_capabilities] == [
        "table.read",
        "document.export",
    ]
    assert updated.capability_sources == ["bounded.discovery"]

    restarted = _service(tmp_path / "learning.db")
    persisted = restarted.profile(profile.profile_id)
    assert persisted.application_identity == "Acme Ledger"
    assert persisted.discovered_capabilities[1].provider == "native.provider"
    assert "Excel" not in persisted.application_identity
    assert "Outlook" not in persisted.application_identity
