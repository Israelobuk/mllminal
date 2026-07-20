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
from mllminal.contracts import new_id, utc_now


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


@dataclass
class _OutlookSession:
    application: Any
    item: Any
    entry_id: str


class EmailDraftAdapter:
    """Outlook desktop draft adapter; sending and credential access are absent."""

    name = "email"
    display_name = "Outlook desktop drafts"

    def __init__(self, workspace_root: Path | None = None, data_dir: Path | None = None) -> None:
        self.workspace_root = (workspace_root or Path.cwd()).expanduser().resolve()
        self.audit_path = (data_dir or self.workspace_root / ".mllminal") / "email-audit.jsonl"
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self.sessions: dict[str, _OutlookSession] = {}
        self._win32com = self._optional_module("win32com.client")

    async def detect(self) -> ApplicationAvailability:
        available = (
            sys.platform == "win32"
            and self._win32com is not None
            and self._outlook_binary() is not None
        )
        return ApplicationAvailability(
            application=self.name,
            display_name=self.display_name,
            detected=available,
            available=available,
            state=ApplicationState.AVAILABLE if available else ApplicationState.DETECTED,
            local_session=available,
            metadata={
                "provider": "outlook.com",
                "binary": str(self._outlook_binary()) if available else None,
                "reason": None if available else "local_outlook_com_unavailable",
                "send_supported": False,
            },
        )

    async def capabilities(self) -> list[CapabilityDefinition]:
        definitions = [
            (
                "email.detect_client",
                "Detect the local Outlook client",
                CapabilityMode.READ_ONLY,
                False,
            ),
            ("email.create_draft", "Create an Outlook draft", CapabilityMode.PREVIEW, True),
            ("email.set_recipients", "Set draft recipients", CapabilityMode.PREVIEW, True),
            ("email.set_subject", "Set draft subject", CapabilityMode.PREVIEW, True),
            ("email.set_body", "Set draft body", CapabilityMode.PREVIEW, True),
            ("email.attach_file", "Attach an approved local file", CapabilityMode.PREVIEW, True),
            (
                "email.verify_draft",
                "Verify an unsent Outlook draft",
                CapabilityMode.READ_ONLY,
                False,
            ),
        ]
        return [
            CapabilityDefinition(
                name=name,
                display_name=display_name,
                mode=mode,
                permission_scope="email.draft",
                consequential=consequential,
            )
            for name, display_name, mode, consequential in definitions
        ]

    async def execute(self, request: CapabilityRequest) -> CapabilityResult:
        try:
            result = await self._execute(request)
        except Exception as error:
            result = self._failure(request, str(error) or "outlook_automation_failed")
        self._audit(request, result)
        return result

    async def verify(self, result: CapabilityResult) -> VerificationResult:
        if not result.succeeded:
            return VerificationResult(
                succeeded=False,
                reason="Email draft operation did not succeed",
                observed=result.output,
            )
        sent = bool(result.output.get("sent", False))
        draft = bool(result.output.get("draft", False))
        succeeded = draft and not sent
        return VerificationResult(
            succeeded=succeeded,
            reason=(
                "Outlook draft verified and remains unsent"
                if succeeded
                else "Outlook draft verification failed"
            ),
            observed=result.output,
        )

    async def _execute(self, request: CapabilityRequest) -> CapabilityResult:
        capability = request.capability
        if capability == "email.detect_client":
            availability = await self.detect()
            return self._success(request, "detect_client", availability.model_dump(mode="json"))
        if capability == "email.create_draft":
            if request.preview:
                return self._preview(
                    request,
                    "create_draft",
                    {"draft": True, "sent": False, "created": False},
                )
            if not self.available:
                raise RuntimeError("local_outlook_com_unavailable")
            win32com = self._win32com
            if win32com is None:
                raise RuntimeError("local_outlook_com_unavailable")
            application = win32com.Dispatch("Outlook.Application")
            item = application.CreateItem(0)
            item.Save()
            entry_id = str(item.EntryID)
            self.sessions[entry_id] = _OutlookSession(application, item, entry_id)
            return self._success(
                request,
                "create_draft",
                {"draft_id": entry_id, "draft": True, "sent": False, "created": True},
            )
        draft_id_value = self._argument(request, "draft_id")
        if not isinstance(draft_id_value, str):
            raise ValueError("draft_id_required")
        draft_id = draft_id_value
        session = self._session(draft_id)
        if capability == "email.set_recipients":
            recipients = request.arguments.get("recipients")
            if (
                not isinstance(recipients, list)
                or not recipients
                or not all(
                    isinstance(value, str) and self._valid_address(value) for value in recipients
                )
            ):
                raise ValueError("valid_recipients_required")
            if request.preview:
                return self._preview(
                    request,
                    "set_recipients",
                    {
                        "draft_id": draft_id,
                        "recipient_count": len(recipients),
                        "draft": True,
                        "sent": False,
                    },
                )
            session.item.To = "; ".join(recipients)
            session.item.Save()
            return self._draft_success(request, "set_recipients", draft_id)
        if capability == "email.set_subject":
            subject = self._argument(request, "subject")
            if (
                not isinstance(subject, str)
                or not subject.strip()
                or "\r" in subject
                or "\n" in subject
            ):
                raise ValueError("valid_subject_required")
            if request.preview:
                return self._preview(
                    request, "set_subject", {"draft_id": draft_id, "draft": True, "sent": False}
                )
            session.item.Subject = subject[:255]
            session.item.Save()
            return self._draft_success(request, "set_subject", draft_id)
        if capability == "email.set_body":
            body = self._argument(request, "body")
            if not isinstance(body, str) or len(body) > 200_000:
                raise ValueError("valid_body_required")
            if request.preview:
                return self._preview(
                    request,
                    "set_body",
                    {"draft_id": draft_id, "body_length": len(body), "draft": True, "sent": False},
                )
            session.item.BodyFormat = 1
            session.item.Body = body
            session.item.Save()
            return self._draft_success(request, "set_body", draft_id)
        if capability == "email.attach_file":
            attachment = self._approved_path(self._argument(request, "path"), must_exist=True)
            if not attachment.is_file():
                raise ValueError("attachment_not_found")
            if request.preview:
                return self._preview(
                    request,
                    "attach_file",
                    {"draft_id": draft_id, "path": str(attachment), "draft": True, "sent": False},
                )
            session.item.Attachments.Add(str(attachment), 1)
            session.item.Save()
            return self._draft_success(request, "attach_file", draft_id, path=str(attachment))
        if capability == "email.verify_draft":
            saved = bool(getattr(session.item, "Saved", False))
            sent = bool(getattr(session.item, "Sent", False))
            return self._success(
                request,
                "verify_draft",
                {"draft_id": draft_id, "draft": saved and not sent, "saved": saved, "sent": sent},
            )
        return self._failure(request, "capability_not_supported")

    def _session(self, draft_id: str) -> _OutlookSession:
        cached = self.sessions.get(draft_id)
        if cached is not None:
            return cached
        if not self.available:
            raise RuntimeError("local_outlook_com_unavailable")
        win32com = self._win32com
        if win32com is None:
            raise RuntimeError("local_outlook_com_unavailable")
        application = win32com.Dispatch("Outlook.Application")
        namespace = application.GetNamespace("MAPI")
        item = namespace.GetItemFromID(draft_id)
        session = _OutlookSession(application, item, draft_id)
        self.sessions[draft_id] = session
        return session

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

    @staticmethod
    def _valid_address(value: str) -> bool:
        local, separator, domain = value.partition("@")
        return bool(separator and local and domain and " " not in value and "." in domain)

    @property
    def available(self) -> bool:
        return (
            sys.platform == "win32"
            and self._win32com is not None
            and self._outlook_binary() is not None
        )

    @staticmethod
    def _optional_module(name: str) -> Any | None:
        try:
            return import_module(name)
        except ImportError:
            return None

    @staticmethod
    def _outlook_binary() -> Path | None:
        if sys.platform != "win32":
            return None
        found = shutil.which("OUTLOOK.EXE")
        if found:
            return Path(found)
        with suppress(Exception):
            winreg = import_module("winreg")
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE",
            ) as key:
                value = winreg.QueryValue(key, None)
                if value:
                    return Path(str(value))
        return None

    def _draft_success(
        self, request: CapabilityRequest, operation: str, draft_id: str, **extra: Any
    ) -> CapabilityResult:
        return self._success(
            request, operation, {"draft_id": draft_id, "draft": True, "sent": False, **extra}
        )

    def _success(
        self, request: CapabilityRequest, operation: str, output: dict[str, Any]
    ) -> CapabilityResult:
        return CapabilityResult(
            capability=request.capability,
            succeeded=True,
            preview=request.preview,
            draft_only=True,
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
            draft_only=True,
            error=error,
        )

    @staticmethod
    def _argument(request: CapabilityRequest, name: str) -> object:
        value = request.arguments.get(name)
        if value is None:
            raise ValueError(f"{name}_required")
        return value

    def _audit(self, request: CapabilityRequest, result: CapabilityResult) -> None:
        record = {
            "at": utc_now().isoformat(),
            "execution_id": result.execution_id,
            "capability": request.capability,
            "succeeded": result.succeeded,
            "preview": result.preview,
            "error": result.error,
            "output": result.output,
        }
        with self.audit_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
