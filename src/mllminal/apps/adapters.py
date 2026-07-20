"""Local Excel and email application adapters."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import Any

from mllminal.apps.contracts import (
    ApplicationAvailability,
    ApplicationState,
    CapabilityDefinition,
    CapabilityMode,
    CapabilityRequest,
    CapabilityResult,
    VerificationResult,
)
from mllminal.contracts import new_id


@dataclass
class _ExcelSession:
    application: Any
    workbook: Any
    path: Path
    macro_enabled: bool


class ExcelAdapter:
    name = "excel"
    display_name = "Excel desktop"

    def __init__(self, workspace_root: Path | None = None, data_dir: Path | None = None) -> None:
        self.workspace_root = (workspace_root or Path.cwd()).expanduser().resolve()
        self.sessions: dict[str, _ExcelSession] = {}
        self.audit_path = (data_dir or self.workspace_root / ".mllminal") / "excel-audit.jsonl"
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self._win32com = self._optional_module("win32com.client")

    async def detect(self) -> ApplicationAvailability:
        available = (
            sys.platform == "win32"
            and self._win32com is not None
            and self._excel_binary() is not None
        )
        return ApplicationAvailability(
            application=self.name,
            display_name=self.display_name,
            detected=available,
            available=available,
            state=ApplicationState.AVAILABLE if available else ApplicationState.DETECTED,
            local_session=available,
            metadata={
                "provider": "excel.com",
                "binary": str(self._excel_binary()) if available else None,
                "reason": None if available else "local_excel_com_unavailable",
            },
        )

    async def capabilities(self) -> list[CapabilityDefinition]:
        readonly = [
            ("excel.detect", "Detect installed Excel"),
            ("excel.open_workbook", "Open a workbook read-only"),
            ("excel.list_sheets", "List workbook sheets"),
            ("excel.inspect_metadata", "Inspect workbook metadata"),
            ("excel.select_sheet", "Select a workbook sheet"),
            ("excel.close_workbook", "Close a workbook without saving"),
            ("excel.verify_output", "Verify an exported workbook output"),
        ]
        writable = [
            ("excel.save_copy", "Save a workbook copy to an approved path"),
            ("excel.export_pdf", "Export a workbook sheet or workbook to PDF"),
        ]
        return [
            CapabilityDefinition(
                name=name,
                display_name=display_name,
                mode=CapabilityMode.READ_ONLY,
                permission_scope="excel.read",
                consequential=False,
            )
            for name, display_name in readonly
        ] + [
            CapabilityDefinition(
                name=name,
                display_name=display_name,
                mode=CapabilityMode.PREVIEW,
                permission_scope="excel.write",
                consequential=True,
            )
            for name, display_name in writable
        ]

    async def execute(self, request: CapabilityRequest) -> CapabilityResult:
        try:
            result = await self._execute(request)
        except Exception as error:
            self._close_after_failure(request)
            result = self._failure(request, str(error) or "excel_automation_failed")
        self._audit(request, result)
        return result

    async def verify(self, result: CapabilityResult) -> VerificationResult:
        if not result.succeeded:
            return VerificationResult(
                succeeded=False,
                reason="Excel operation did not succeed",
                observed=result.output,
            )
        operation = str(result.output.get("operation", ""))
        output_path = result.output.get("path")
        if operation in {"save_copy", "export_pdf", "verify_output"} and output_path:
            path = Path(str(output_path))
            succeeded = path.is_file() and path.stat().st_size > 0
        else:
            succeeded = operation in {
                "detect",
                "open_workbook",
                "list_sheets",
                "inspect_metadata",
                "select_sheet",
                "close_workbook",
            }
        return VerificationResult(
            succeeded=succeeded,
            reason=(
                "Independent Excel state verification passed"
                if succeeded
                else "Excel output verification failed"
            ),
            observed=result.output,
        )

    async def _execute(self, request: CapabilityRequest) -> CapabilityResult:
        capability = request.capability
        if capability == "excel.detect":
            availability = await self.detect()
            return self._success(request, "detect", availability.model_dump(mode="json"))
        if capability == "excel.verify_output":
            path = self._approved_path(self._argument(request, "path"), must_exist=False)
            exists = path.is_file() and path.stat().st_size > 0 if path.exists() else False
            return self._success(
                request,
                "verify_output",
                {"path": str(path), "exists": exists, "non_empty": exists},
            )
        if capability == "excel.open_workbook":
            path = self._approved_path(self._argument(request, "path"), must_exist=True)
            if not path.is_file():
                raise ValueError("workbook_not_found")
            if not self.available:
                raise RuntimeError("local_excel_com_unavailable")
            session_id = new_id()
            win32com = self._win32com
            if win32com is None:
                raise RuntimeError("local_excel_com_unavailable")
            application = win32com.DispatchEx("Excel.Application")
            application.Visible = False
            application.DisplayAlerts = False
            with suppress(Exception):
                application.AutomationSecurity = 3
            workbook = application.Workbooks.Open(
                str(path),
                UpdateLinks=0,
                ReadOnly=True,
                AddToMru=False,
                IgnoreReadOnlyRecommended=True,
            )
            macro_enabled = path.suffix.casefold() in {".xlsm", ".xltm", ".xlsb"}
            self.sessions[session_id] = _ExcelSession(application, workbook, path, macro_enabled)
            return self._success(
                request,
                "open_workbook",
                {
                    "workbook_id": session_id,
                    "path": str(path),
                    "read_only": True,
                    "macro_enabled": macro_enabled,
                    "external_links_updated": False,
                },
            )
        session_id_value = self._argument(request, "workbook_id")
        if not isinstance(session_id_value, str) or session_id_value not in self.sessions:
            raise ValueError("workbook_session_not_found")
        session_id = session_id_value
        session = self.sessions[session_id]
        if capability == "excel.list_sheets":
            sheets = [
                str(session.workbook.Worksheets(index).Name)
                for index in range(1, int(session.workbook.Worksheets.Count) + 1)
            ]
            return self._success(
                request, "list_sheets", {"workbook_id": session_id, "sheets": sheets}
            )
        if capability == "excel.inspect_metadata":
            return self._success(request, "inspect_metadata", self._metadata(session_id, session))
        if capability == "excel.select_sheet":
            sheet_name = self._argument(request, "sheet")
            sheet = session.workbook.Worksheets(str(sheet_name))
            if not request.preview:
                sheet.Activate()
            return self._success(
                request,
                "select_sheet",
                {
                    "workbook_id": session_id,
                    "sheet": str(sheet.Name),
                    "selected": not request.preview,
                },
            )
        if capability in {"excel.save_copy", "excel.export_pdf"}:
            destination = self._approved_output(self._argument(request, "path"))
            self._require_new_output(destination)
            if request.preview:
                return self._preview(
                    request,
                    capability.removeprefix("excel."),
                    {
                        "workbook_id": session_id,
                        "path": str(destination),
                        "mutation_performed": False,
                    },
                )
            if capability == "excel.save_copy":
                session.workbook.SaveCopyAs(str(destination))
            else:
                sheet_name = request.arguments.get("sheet")
                if sheet_name:
                    session.workbook.Worksheets(str(sheet_name)).ExportAsFixedFormat(
                        0, str(destination), 0, True, False, 0, 0
                    )
                else:
                    session.workbook.ExportAsFixedFormat(0, str(destination), 0, True, False, 0, 0)
            return self._success(
                request,
                capability.removeprefix("excel."),
                {"workbook_id": session_id, "path": str(destination), "original_preserved": True},
            )
        if capability == "excel.close_workbook":
            if not request.preview:
                self._close_session(session_id)
            return self._success(
                request,
                "close_workbook",
                {"workbook_id": session_id, "closed": not request.preview, "saved": False},
            )
        return self._failure(request, "capability_not_supported")

    @property
    def available(self) -> bool:
        return (
            sys.platform == "win32"
            and self._win32com is not None
            and self._excel_binary() is not None
        )

    def _approved_path(self, value: object, *, must_exist: bool) -> Path:
        if not isinstance(value, str) or not value.strip() or "\x00" in value:
            raise ValueError("invalid_path")
        candidate = Path(value).expanduser()
        if any(part == ".." for part in candidate.parts):
            raise ValueError("path_traversal_not_allowed")
        path = (candidate if candidate.is_absolute() else self.workspace_root / candidate).resolve()
        if path != self.workspace_root and not path.is_relative_to(self.workspace_root):
            raise ValueError("path_outside_workspace")
        if path.is_symlink():
            raise ValueError("symlink_not_allowed")
        if must_exist and not path.exists():
            raise ValueError("path_not_found")
        return path

    def _approved_output(self, value: object) -> Path:
        path = self._approved_path(value, must_exist=False)
        if not path.parent.exists() or not path.parent.is_dir():
            raise ValueError("output_parent_not_found")
        return path

    @staticmethod
    def _require_new_output(path: Path) -> None:
        if path.exists():
            raise ValueError("output_collision")

    def _metadata(self, session_id: str, session: _ExcelSession) -> dict[str, Any]:
        sheets = [
            str(session.workbook.Worksheets(index).Name)
            for index in range(1, int(session.workbook.Worksheets.Count) + 1)
        ]
        return {
            "workbook_id": session_id,
            "path": str(session.path),
            "extension": session.path.suffix.casefold(),
            "size": session.path.stat().st_size,
            "sha256": self._hash(session.path),
            "sheets": sheets,
            "macro_enabled": session.macro_enabled,
            "read_only": True,
            "external_links_updated": False,
        }

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _close_session(self, session_id: str) -> None:
        session = self.sessions.pop(session_id, None)
        if session is None:
            return
        with suppress(Exception):
            session.workbook.Close(SaveChanges=False)
        with suppress(Exception):
            session.application.Quit()

    def _close_after_failure(self, request: CapabilityRequest) -> None:
        session_id = request.arguments.get("workbook_id")
        if isinstance(session_id, str):
            self._close_session(session_id)

    @staticmethod
    def _argument(request: CapabilityRequest, name: str, default: object = None) -> object:
        value = request.arguments.get(name, default)
        if value is None:
            raise ValueError(f"{name}_required")
        return value

    @staticmethod
    def _optional_module(name: str) -> Any | None:
        try:
            return import_module(name)
        except ImportError:
            return None

    @staticmethod
    def _excel_binary() -> Path | None:
        if sys.platform != "win32":
            return None
        found = shutil.which("EXCEL.EXE")
        if found:
            return Path(found)
        with suppress(Exception):
            winreg = import_module("winreg")
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\excel.exe",
            ) as key:
                value = winreg.QueryValue(key, None)
                if value:
                    return Path(str(value))
        return None

    def _success(
        self, request: CapabilityRequest, operation: str, output: dict[str, Any]
    ) -> CapabilityResult:
        return CapabilityResult(
            capability=request.capability,
            succeeded=True,
            preview=request.preview,
            draft_only=request.preview,
            output={"operation": operation, **output},
        )

    def _preview(
        self, request: CapabilityRequest, operation: str, output: dict[str, Any]
    ) -> CapabilityResult:
        return self._success(request.model_copy(update={"preview": True}), operation, output)

    @staticmethod
    def _failure(request: CapabilityRequest, error: str) -> CapabilityResult:
        return CapabilityResult(
            capability=request.capability,
            succeeded=False,
            preview=request.preview,
            draft_only=request.preview,
            error=error,
        )

    def _audit(self, request: CapabilityRequest, result: CapabilityResult) -> None:
        record = {
            "at": datetime.now(UTC).isoformat(),
            "execution_id": result.execution_id,
            "capability": request.capability,
            "succeeded": result.succeeded,
            "preview": result.preview,
            "error": result.error,
            "output": result.output,
        }
        with self.audit_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")


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
            succeeded=result.succeeded and result.draft_only,
            reason="Email adapter is draft-only until a bounded desktop bridge is granted",
            observed=result.output,
        )
