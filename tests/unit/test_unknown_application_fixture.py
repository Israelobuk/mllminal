from pathlib import Path

import pytest

from mllminal.apps.contracts import (
    ApplicationAvailability,
    ApplicationState,
    CapabilityDefinition,
    CapabilityMode,
    CapabilityRequest,
    CapabilityResult,
    VerificationResult,
)
from mllminal.apps.service import ApplicationBridgeService


class UnknownApplicationFixture:
    name = "fixture-unknown-application"
    display_name = "Unknown Application Fixture"

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
                name="document.export",
                display_name="Export a document artifact",
                mode=CapabilityMode.PREVIEW,
                permission_scope="document.write",
                consequential=True,
                requires_independent_verification=True,
            )
        ]

    async def execute(self, request: CapabilityRequest) -> CapabilityResult:
        if request.capability != "document.export":
            return CapabilityResult(
                capability=request.capability,
                succeeded=False,
                preview=request.preview,
                draft_only=False,
                error="unsupported_fixture_capability",
            )
        return CapabilityResult(
            capability=request.capability,
            succeeded=True,
            preview=request.preview,
            draft_only=False,
            output={"artifact": "fixture-document", "submitted": False},
        )

    async def verify(self, result: CapabilityResult) -> VerificationResult:
        verified = (
            result.succeeded
            and result.output.get("artifact") == "fixture-document"
            and result.output.get("submitted") is False
        )
        return VerificationResult(
            succeeded=verified,
            reason="Unknown application fixture output and submission boundary checked",
            observed={"artifact": result.output.get("artifact"), "submitted": False},
        )


@pytest.mark.asyncio
async def test_unknown_application_fixture_is_discovered_executed_and_verified(
    tmp_path: Path,
) -> None:
    bridge = ApplicationBridgeService(tmp_path / "state.db", workspace_root=tmp_path)
    bridge.registry.register(UnknownApplicationFixture())

    report = await bridge.capability_discovery("fixture-unknown-application")
    assert [item.capability.name for item in report.capabilities] == ["document.export"]
    assert report.capabilities[0].source == "registered_adapter"

    request = CapabilityRequest(capability="document.export")
    preview = await bridge.execute(
        "fixture-unknown-application",
        request,
        idempotency_key="unknown-preview",
    )
    assert preview.succeeded is True
    assert preview.preview is True
    assert preview.output["submitted"] is False

    with pytest.raises(PermissionError, match="authorization"):
        await bridge.execute(
            "fixture-unknown-application",
            request.model_copy(update={"preview": False, "workflow_authorized": True}),
            idempotency_key="unknown-missing-approval",
        )

    bridge.grant(
        "fixture-unknown-application",
        "document.write",
        idempotency_key="unknown-grant",
    )
    executed = await bridge.execute(
        "fixture-unknown-application",
        request.model_copy(
            update={
                "preview": False,
                "workflow_authorized": True,
                "action_approved": True,
            }
        ),
        idempotency_key="unknown-execute",
    )
    verified = await bridge.verify("fixture-unknown-application", executed)
    assert verified.succeeded is True

    with pytest.raises(KeyError):
        await bridge.execute(
            "fixture-unknown-application",
            CapabilityRequest(capability="email.send"),
            idempotency_key="unknown-send",
        )
