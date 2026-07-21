"""Spreadsheet capability providers with honest rendering boundaries."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any, ClassVar
from xml.etree import ElementTree

from mllminal.apps.adapters import ExcelAdapter
from mllminal.apps.contracts import CapabilityRequest
from mllminal.providers.contracts import (
    AbstractCapability,
    ProviderAvailability,
    ProviderKind,
    ProviderRequest,
    ProviderResult,
    ProviderStatus,
)


class ExcelDesktopProvider:
    name = "excel-desktop"
    display_name = "Microsoft Excel desktop (optional)"
    kind = ProviderKind.NATIVE
    priority = 10

    def __init__(self, workspace_root: Path, data_dir: Path) -> None:
        self.adapter = ExcelAdapter(workspace_root, data_dir)

    async def discover(self) -> ProviderAvailability:
        detected = await self.adapter.detect()
        return ProviderAvailability(
            provider=self.name,
            display_name=self.display_name,
            kind=self.kind,
            status=(ProviderStatus.AVAILABLE if detected.available else ProviderStatus.UNAVAILABLE),
            detected=detected.detected,
            capabilities=[
                AbstractCapability.SPREADSHEET_INSPECT,
                AbstractCapability.SPREADSHEET_EXPORT_PDF,
                AbstractCapability.SPREADSHEET_VERIFY_OUTPUT,
            ],
            permission_scopes=["spreadsheet.read", "spreadsheet.export"],
            verification_strength="native-application",
            install_state="installed" if detected.detected else "not_installed",
            explanation=(
                "Excel desktop automation is available."
                if detected.available
                else (
                    "Excel desktop or its COM automation dependency is unavailable; "
                    "this provider is optional."
                )
            ),
            metadata=detected.metadata,
        )

    async def execute(self, request: ProviderRequest) -> ProviderResult:
        capability_map = {
            AbstractCapability.SPREADSHEET_INSPECT: "excel.inspect_metadata",
            AbstractCapability.SPREADSHEET_EXPORT_PDF: "excel.export_pdf",
            AbstractCapability.SPREADSHEET_VERIFY_OUTPUT: "excel.verify_output",
        }
        legacy = capability_map[request.capability]
        result = await self.adapter.execute(
            CapabilityRequest(
                capability=legacy,
                arguments=request.arguments,
                preview=request.preview,
                workflow_authorized=request.workflow_authorized,
                action_approved=request.action_approved,
            )
        )
        return ProviderResult(
            capability=request.capability,
            provider=self.name,
            succeeded=result.succeeded,
            preview=result.preview,
            draft_only=result.draft_only,
            output=result.output,
            error=result.error,
        )


class PythonSpreadsheetInspectionProvider:
    """Dependency-light workbook inspection; it never claims Excel PDF fidelity."""

    name = "python-spreadsheet-inspection"
    display_name = "Bundled Python workbook inspection"
    kind = ProviderKind.BUNDLED
    priority = 30
    _formats: ClassVar[set[str]] = {".xlsx", ".xlsm", ".xltx", ".xltm"}

    async def discover(self) -> ProviderAvailability:
        return ProviderAvailability(
            provider=self.name,
            display_name=self.display_name,
            kind=self.kind,
            status=ProviderStatus.AVAILABLE,
            detected=True,
            capabilities=[AbstractCapability.SPREADSHEET_INSPECT],
            permission_scopes=["spreadsheet.read"],
            verification_strength="zip-xml-metadata",
            install_state="bundled",
            explanation=(
                "The bundled inspector reads supported OOXML workbook metadata without Excel. "
                "It does not reproduce Excel formulas, recalculation, or PDF rendering."
            ),
            metadata={"formats": sorted(self._formats), "rendering": "not_supported"},
        )

    async def execute(self, request: ProviderRequest) -> ProviderResult:
        path = _input_path(request.arguments.get("path"))
        if path.suffix.casefold() not in self._formats:
            return _failure(request, self.name, "unsupported_workbook_format")
        if not path.is_file():
            return _failure(request, self.name, "workbook_not_found")
        try:
            output = self._inspect(path)
        except (OSError, ValueError, zipfile.BadZipFile, ElementTree.ParseError) as error:
            return _failure(request, self.name, str(error) or "workbook_inspection_failed")
        return ProviderResult(
            capability=request.capability,
            provider=self.name,
            succeeded=True,
            preview=True,
            output={"operation": "inspect", **output},
        )

    @staticmethod
    def _inspect(path: Path) -> dict[str, Any]:
        namespace = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        with zipfile.ZipFile(path) as workbook:
            workbook_xml = ElementTree.fromstring(workbook.read("xl/workbook.xml"))
            sheets = [
                item.attrib.get("name", "")
                for item in workbook_xml.findall("main:sheets/main:sheet", namespace)
            ]
            external_links = any(
                name.startswith("xl/externalLinks/") for name in workbook.namelist()
            )
            return {
                "path": str(path),
                "extension": path.suffix.casefold(),
                "size": path.stat().st_size,
                "sha256": _sha256(path),
                "sheets": sheets,
                "macro_enabled": path.suffix.casefold() in {".xlsm", ".xltm"},
                "external_links_present": external_links,
                "formula_recalculation": "not_evaluated",
                "pdf_rendering": "not_supported_by_this_provider",
            }


class LibreOfficeProvider:
    name = "libreoffice"
    display_name = "LibreOffice headless (optional portable provider)"
    kind = ProviderKind.PORTABLE
    priority = 40

    def __init__(self, executable: Path | None = None) -> None:
        self.executable = executable or self._find_executable()

    async def discover(self) -> ProviderAvailability:
        detected = self.executable is not None
        return ProviderAvailability(
            provider=self.name,
            display_name=self.display_name,
            kind=self.kind,
            status=ProviderStatus.AVAILABLE if detected else ProviderStatus.UNAVAILABLE,
            detected=detected,
            capabilities=[
                AbstractCapability.SPREADSHEET_INSPECT,
                AbstractCapability.SPREADSHEET_EXPORT_PDF,
                AbstractCapability.SPREADSHEET_VERIFY_OUTPUT,
            ],
            permission_scopes=["spreadsheet.read", "spreadsheet.export"],
            verification_strength="headless-renderer" if detected else "none",
            install_state="installed" if detected else "skipped",
            explanation=(
                "LibreOffice can inspect and render supported workbooks headlessly. "
                "Its output is not asserted to be identical to Excel output."
                if detected
                else (
                    "LibreOffice is not installed; the installer may offer it as an "
                    "optional portable provider."
                )
            ),
            metadata={"executable": str(self.executable) if self.executable else None},
        )

    async def execute(self, request: ProviderRequest) -> ProviderResult:
        if self.executable is None:
            return _failure(request, self.name, "libreoffice_unavailable")
        if request.capability == AbstractCapability.SPREADSHEET_INSPECT:
            return await PythonSpreadsheetInspectionProvider().execute(request)
        if request.capability == AbstractCapability.SPREADSHEET_VERIFY_OUTPUT:
            path = _input_path(request.arguments.get("path"))
            valid = path.is_file() and path.stat().st_size > 0
            return ProviderResult(
                capability=request.capability,
                provider=self.name,
                succeeded=valid,
                preview=True,
                output={"path": str(path), "exists": valid, "non_empty": valid},
                error=None if valid else "output_not_found_or_empty",
            )
        source = _input_path(request.arguments.get("path"))
        destination = _output_path(request.arguments.get("output_path"))
        if not source.is_file():
            return _failure(request, self.name, "workbook_not_found")
        if destination.exists():
            return _failure(request, self.name, "output_collision")
        if request.preview:
            return ProviderResult(
                capability=request.capability,
                provider=self.name,
                succeeded=True,
                preview=True,
                output={
                    "operation": "export_pdf",
                    "path": str(destination),
                    "mutation_performed": False,
                    "renderer": "libreoffice",
                },
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [
                str(self.executable),
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(destination.parent),
                str(source),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        generated = destination.parent / f"{source.stem}.pdf"
        if completed.returncode != 0 or not generated.is_file():
            return _failure(request, self.name, "libreoffice_export_failed")
        if generated != destination:
            generated.replace(destination)
        return ProviderResult(
            capability=request.capability,
            provider=self.name,
            succeeded=True,
            preview=False,
            output={"operation": "export_pdf", "path": str(destination), "renderer": "libreoffice"},
        )

    @staticmethod
    def _find_executable() -> Path | None:
        found = shutil.which("soffice") or shutil.which("soffice.exe")
        if found:
            return Path(found)
        candidates = []
        for root in filter(
            None, (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"))
        ):
            candidates.append(Path(root) / "LibreOffice" / "program" / "soffice.exe")
        return next((candidate for candidate in candidates if candidate.is_file()), None)


class BrowserSpreadsheetProvider:
    name = "browser-spreadsheet"
    display_name = "Signed-in browser spreadsheet surface"
    kind = ProviderKind.BROWSER
    priority = 20

    def __init__(self, browser_bridge: Any) -> None:
        self.browser_bridge = browser_bridge

    async def discover(self) -> ProviderAvailability:
        connected = bool(getattr(self.browser_bridge, "connected", False))
        return ProviderAvailability(
            provider=self.name,
            display_name=self.display_name,
            kind=self.kind,
            status=ProviderStatus.AVAILABLE if connected else ProviderStatus.MANUAL_REQUIRED,
            detected=connected,
            capabilities=[
                AbstractCapability.SPREADSHEET_INSPECT,
                AbstractCapability.SPREADSHEET_EXPORT_PDF,
            ],
            permission_scopes=["browser.spreadsheet"],
            verification_strength="semantic-dom" if connected else "none",
            install_state="connected" if connected else "extension_not_connected",
            explanation=(
                "A signed-in browser spreadsheet surface is connected through the local bridge."
                if connected
                else (
                    "Connect the MLLminal browser extension to use a signed-in spreadsheet surface."
                )
            ),
            metadata={
                "credentials_read": False,
                "manual_steps": [
                    "Install or enable the MLLminal browser extension.",
                    "Approve the spreadsheet domain permission.",
                ],
            },
        )

    async def execute(self, request: ProviderRequest) -> ProviderResult:
        if not getattr(self.browser_bridge, "connected", False):
            return _failure(request, self.name, "browser_bridge_not_connected")
        output = self.browser_bridge.prepare(
            domain=str(request.arguments.get("domain", "spreadsheet")),
            fields=request.arguments,
            capability=request.capability.value,
        )
        return ProviderResult(
            capability=request.capability,
            provider=self.name,
            succeeded=True,
            preview=True,
            output=output,
        )


class ManualSpreadsheetHandoffProvider:
    name = "manual-spreadsheet-handoff"
    display_name = "Manual spreadsheet export handoff"
    kind = ProviderKind.MANUAL
    priority = 50

    async def discover(self) -> ProviderAvailability:
        return ProviderAvailability(
            provider=self.name,
            display_name=self.display_name,
            kind=self.kind,
            status=ProviderStatus.MANUAL_REQUIRED,
            capabilities=[AbstractCapability.SPREADSHEET_EXPORT_PDF],
            permission_scopes=["spreadsheet.manual_handoff"],
            verification_strength="user-confirmed",
            explanation=(
                "No safe local renderer is available; the user must export the workbook manually."
            ),
            metadata={
                "manual_steps": [
                    "Open the workbook in any trusted spreadsheet application.",
                    "Export or print the workbook to PDF.",
                    "Return the PDF path to MLLminal for independent file verification.",
                ]
            },
        )

    async def execute(self, request: ProviderRequest) -> ProviderResult:
        availability = await self.discover()
        return ProviderResult(
            capability=request.capability,
            provider=self.name,
            succeeded=True,
            preview=True,
            output={"operation": "manual_handoff", "steps": availability.metadata["manual_steps"]},
        )


def _input_path(value: object) -> Path:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError("invalid_path")
    path = Path(value).expanduser().resolve()
    if any(part == ".." for part in Path(value).parts):
        raise ValueError("path_traversal_not_allowed")
    return path


def _output_path(value: object) -> Path:
    path = _input_path(value)
    if path.exists():
        raise ValueError("output_collision")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _failure(request: ProviderRequest, provider: str, error: str) -> ProviderResult:
    return ProviderResult(
        capability=request.capability,
        provider=provider,
        succeeded=False,
        preview=request.preview,
        error=error,
    )
