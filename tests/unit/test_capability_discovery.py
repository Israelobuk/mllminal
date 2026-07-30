from mllminal.apps.contracts import (
    ApplicationAvailability,
    ApplicationState,
    CapabilityDefinition,
    CapabilityMode,
    CapabilityRequest,
    CapabilityResult,
    VerificationResult,
)
from mllminal.apps.discovery import ApplicationDiscovery
from mllminal.apps.registry import ApplicationRegistry


class UnknownApplicationAdapter:
    name = "unknown-tool"
    display_name = "Unknown Tool"

    async def detect(self) -> ApplicationAvailability:
        return ApplicationAvailability(
            application=self.name,
            display_name=self.display_name,
            detected=True,
            available=True,
            state=ApplicationState.AVAILABLE,
        )

    async def capabilities(self) -> list[CapabilityDefinition]:
        return [
            CapabilityDefinition(
                name="table.read",
                display_name="Read table",
                mode=CapabilityMode.READ_ONLY,
                permission_scope="application.read",
            ),
            CapabilityDefinition(
                name="document.export",
                display_name="Export document",
                mode=CapabilityMode.PREVIEW,
                permission_scope="document.write",
                consequential=True,
            ),
            CapabilityDefinition(
                name="control.invoke",
                display_name="Invoke control",
                mode=CapabilityMode.PREVIEW,
                permission_scope="application.write",
                consequential=True,
            ),
        ]

    async def execute(self, request: CapabilityRequest) -> CapabilityResult:
        return CapabilityResult(
            capability=request.capability,
            succeeded=False,
            preview=request.preview,
            draft_only=False,
            error="fixture_only",
        )

    async def verify(self, result: CapabilityResult) -> VerificationResult:
        return VerificationResult(succeeded=False, reason="fixture_only")


async def test_discovery_is_bounded_and_preserves_provenance_for_unknown_apps() -> None:
    registry = ApplicationRegistry()
    registry.register(UnknownApplicationAdapter())
    discovery = ApplicationDiscovery(registry, max_capabilities=2)

    report = await discovery.discover_capabilities("unknown-tool")

    assert report.application == "unknown-tool"
    assert report.bounded is True
    assert report.complete is False
    assert [item.capability.name for item in report.capabilities] == [
        "table.read",
        "document.export",
    ]
    assert report.capabilities[0].provider == "unknown-tool"
    assert report.capabilities[0].source == "registered_adapter"
    assert report.capabilities[0].confidence == 1.0

    missing = await discovery.discover_capabilities("not-registered")
    assert missing.capabilities == []
    assert missing.complete is True
    assert "No bounded adapter" in missing.explanation
