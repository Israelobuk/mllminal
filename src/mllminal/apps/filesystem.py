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

    def __init__(self, workspace_root: Path | None = None) -> None:
        self.workspace_root = (workspace_root or Path.cwd()).resolve()

    async def detect(self) -> ApplicationAvailability:
        return ApplicationAvailability(
            application=self.name,
            display_name=self.display_name,
            detected=True,
            available=True,
            state=ApplicationState.AVAILABLE,
            local_session=True,
            metadata={"workspace_root": str(self.workspace_root)},
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
            try:
                folder = self._confined_path(str(request.arguments.get("folder", ".")))
            except ValueError:
                return self._failure(request, "path_outside_workspace")
            if not folder.is_dir():
                return self._failure(request, "folder_not_found")
            entries = sorted(item.name for item in folder.iterdir())[:100]
            return CapabilityResult(
                capability=request.capability,
                succeeded=True,
                preview=request.preview,
                draft_only=False,
                output={"folder": str(folder), "entries": entries},
            )
        if request.capability == "filesystem.copy_draft":
            try:
                source = self._optional_confined_path(request.arguments.get("source"))
                destination = self._optional_confined_path(request.arguments.get("destination"))
            except ValueError:
                return self._failure(request, "path_outside_workspace", draft_only=True)
            return CapabilityResult(
                capability=request.capability,
                succeeded=True,
                preview=True,
                draft_only=True,
                output={
                    "source": str(source) if source else None,
                    "destination": str(destination) if destination else None,
                    "mutation_performed": False,
                },
            )
        return self._failure(request, "capability_not_supported", draft_only=True)

    async def verify(self, result: CapabilityResult) -> VerificationResult:
        return VerificationResult(
            succeeded=result.succeeded and result.output.get("mutation_performed", False) is False,
            reason="Filesystem adapter verified bounded or draft-only behavior",
            observed=result.output,
        )

    def _confined_path(self, value: str) -> Path:
        path = (
            (self.workspace_root / value).resolve()
            if not Path(value).is_absolute()
            else Path(value).resolve()
        )
        if not path.is_relative_to(self.workspace_root):
            raise ValueError("path outside workspace")
        return path

    def _optional_confined_path(self, value: object) -> Path | None:
        return self._confined_path(str(value)) if value is not None else None

    @staticmethod
    def _failure(
        request: CapabilityRequest, error: str, *, draft_only: bool = False
    ) -> CapabilityResult:
        return CapabilityResult(
            capability=request.capability,
            succeeded=False,
            preview=request.preview,
            draft_only=draft_only,
            error=error,
        )
