"""Initial preview/draft application adapters."""

from mllminal.apps.contracts import (
    ApplicationAvailability,
    ApplicationState,
    CapabilityDefinition,
    CapabilityMode,
    CapabilityRequest,
    CapabilityResult,
    VerificationResult,
)


class ExcelAdapter:
    name = "excel"
    display_name = "Excel desktop"

    async def detect(self) -> ApplicationAvailability:
        return ApplicationAvailability(
            application=self.name,
            display_name=self.display_name,
            detected=False,
            available=False,
            state=ApplicationState.DETECTED,
            metadata={"reason": "desktop_adapter_not_connected"},
        )

    async def capabilities(self) -> list[CapabilityDefinition]:
        return [
            CapabilityDefinition(
                name="excel.export_report_draft",
                display_name="Draft an Excel report export",
                mode=CapabilityMode.DRAFT_ONLY,
                permission_scope="excel.draft",
                consequential=True,
            )
        ]

    async def execute(self, request: CapabilityRequest) -> CapabilityResult:
        return CapabilityResult(
            capability=request.capability,
            succeeded=True,
            preview=True,
            draft_only=True,
            output={"draft": request.arguments, "export_started": False},
        )

    async def verify(self, result: CapabilityResult) -> VerificationResult:
        return VerificationResult(
            succeeded=result.succeeded and result.draft_only,
            reason="Excel adapter is draft-only until a bounded desktop bridge is granted",
            observed=result.output,
        )


class EmailDraftAdapter:
    name = "email"
    display_name = "Email draft surface"

    async def detect(self) -> ApplicationAvailability:
        return ApplicationAvailability(
            application=self.name,
            display_name=self.display_name,
            detected=False,
            available=False,
            state=ApplicationState.DETECTED,
            metadata={"reason": "browser_or_desktop_draft_bridge_not_connected"},
        )

    async def capabilities(self) -> list[CapabilityDefinition]:
        return [
            CapabilityDefinition(
                name="email.create_draft",
                display_name="Create an email draft",
                mode=CapabilityMode.DRAFT_ONLY,
                permission_scope="email.draft",
                consequential=True,
            )
        ]

    async def execute(self, request: CapabilityRequest) -> CapabilityResult:
        return CapabilityResult(
            capability=request.capability,
            succeeded=True,
            preview=True,
            draft_only=True,
            output={"draft": request.arguments, "sent": False},
        )

    async def verify(self, result: CapabilityResult) -> VerificationResult:
        return VerificationResult(
            succeeded=result.succeeded and result.output.get("sent") is False,
            reason="Email adapter verified draft-only behavior; no message was sent",
            observed=result.output,
        )
