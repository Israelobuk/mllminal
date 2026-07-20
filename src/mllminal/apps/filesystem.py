"""Safe local filesystem adapter with preview-only consequential operations."""

from pathlib import Path

from mllminal.apps.contracts import (
    ApplicationAvailability,
    ApplicationState,
    CapabilityDefinition,
    CapabilityMode,
    CapabilityRequest,
    CapabilityResult,
    VerificationResult,
)


class FilesystemAdapter:
    name = "filesystem"
    display_name = "Windows filesystem"

    async def detect(self) -> ApplicationAvailability:
        return ApplicationAvailability(
            application=self.name,
            display_name=self.display_name,
            detected=True,
            available=True,
            state=ApplicationState.AVAILABLE,
            local_session=True,
        )

    async def capabilities(self) -> list[CapabilityDefinition]:
        return [
            CapabilityDefinition(
                name="filesystem.inspect",
                display_name="Inspect a bounded folder",
                mode=CapabilityMode.READ_ONLY,
                permission_scope="filesystem.read",
                consequential=False,
            ),
            CapabilityDefinition(
                name="filesystem.copy_draft",
                display_name="Preview a file copy",
                mode=CapabilityMode.PREVIEW,
                permission_scope="filesystem.write",
                consequential=True,
            ),
        ]

    async def execute(self, request: CapabilityRequest) -> CapabilityResult:
        if request.capability == "filesystem.inspect":
            folder = Path(str(request.arguments.get("folder", "."))).resolve()
            if not folder.is_dir():
                return CapabilityResult(
                    capability=request.capability,
                    succeeded=False,
                    preview=request.preview,
                    draft_only=False,
                    error="folder_not_found",
                )
            entries = sorted(item.name for item in folder.iterdir())[:100]
            return CapabilityResult(
                capability=request.capability,
                succeeded=True,
                preview=request.preview,
                draft_only=False,
                output={"folder": str(folder), "entries": entries},
            )
        if request.capability == "filesystem.copy_draft":
            return CapabilityResult(
                capability=request.capability,
                succeeded=True,
                preview=True,
                draft_only=True,
                output={
                    "source": request.arguments.get("source"),
                    "destination": request.arguments.get("destination"),
                    "mutation_performed": False,
                },
            )
        return CapabilityResult(
            capability=request.capability,
            succeeded=False,
            preview=request.preview,
            draft_only=True,
            error="capability_not_supported",
        )

    async def verify(self, result: CapabilityResult) -> VerificationResult:
        return VerificationResult(
            succeeded=result.succeeded and result.output.get("mutation_performed", False) is False,
            reason="Filesystem adapter verified bounded or draft-only behavior",
            observed=result.output,
        )
