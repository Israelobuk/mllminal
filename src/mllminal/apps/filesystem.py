"""Bounded Windows filesystem and File Explorer adapter."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

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


class _ShellFileOp(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("operation", ctypes.c_uint),
        ("from_path", ctypes.c_wchar_p),
        ("to_path", ctypes.c_wchar_p),
        ("flags", ctypes.c_ushort),
        ("aborted", ctypes.c_int),
        ("name_mapping", ctypes.c_void_p),
        ("title", ctypes.c_wchar_p),
    ]


class FilesystemAdapter:
    name = "filesystem"
    display_name = "Windows filesystem"

    def __init__(
        self,
        workspace_root: Path | None = None,
        *,
        approved_roots: list[Path] | None = None,
        data_dir: Path | None = None,
    ) -> None:
        root = (workspace_root or Path.cwd()).expanduser().resolve()
        roots = [root, *(approved_roots or [])]
        self.approved_roots = tuple(dict.fromkeys(item.expanduser().resolve() for item in roots))
        self.audit_path = (data_dir or root / ".mllminal") / "filesystem-audit.jsonl"
        self.rollback_root = self.audit_path.parent / "filesystem-rollback"
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self.rollback_root.mkdir(parents=True, exist_ok=True)

    async def detect(self) -> ApplicationAvailability:
        return ApplicationAvailability(
            application=self.name,
            display_name=self.display_name,
            detected=True,
            available=True,
            state=ApplicationState.AVAILABLE,
            local_session=True,
            metadata={"approved_roots": [str(root) for root in self.approved_roots]},
        )

    async def capabilities(self) -> list[CapabilityDefinition]:
        readonly = [
            ("filesystem.list", "List an approved folder"),
            ("filesystem.inspect", "Inspect an approved filesystem item"),
            ("filesystem.find_latest", "Find the newest matching approved file"),
            ("filesystem.exists", "Check approved path existence"),
            ("filesystem.hash", "Hash an approved file"),
            ("explorer.open_folder", "Open an approved folder in File Explorer"),
            ("explorer.select_file", "Select an approved file in File Explorer"),
        ]
        mutations = [
            ("filesystem.create_folder", "Create an approved folder"),
            ("filesystem.rename", "Rename an approved filesystem item"),
            ("filesystem.copy", "Copy an approved filesystem item"),
            ("filesystem.move", "Move an approved filesystem item"),
            ("filesystem.delete_to_recycle_bin", "Move an approved item to the Recycle Bin"),
            ("filesystem.restore", "Restore an approved filesystem operation"),
        ]
        return [
            CapabilityDefinition(
                name=name,
                display_name=display_name,
                mode=CapabilityMode.READ_ONLY,
                permission_scope="filesystem.read",
                consequential=False,
            )
            for name, display_name in readonly
        ] + [
            CapabilityDefinition(
                name=name,
                display_name=display_name,
                mode=CapabilityMode.PREVIEW,
                permission_scope="filesystem.write",
                consequential=True,
            )
            for name, display_name in mutations
        ]

    async def execute(self, request: CapabilityRequest) -> CapabilityResult:
        try:
            result = self._execute(request)
        except (OSError, ValueError, RuntimeError) as error:
            result = self._failure(request, str(error))
        self._audit(request, result)
        return result

    async def verify(self, result: CapabilityResult) -> VerificationResult:
        if not result.succeeded:
            return VerificationResult(
                succeeded=False,
                reason="Filesystem operation did not succeed",
                observed=result.output,
            )
        output = result.output
        operation = str(output.get("operation", ""))
        try:
            if operation in {"rename", "move"}:
                source = self._confined_path(str(output["source"]))
                destination = self._confined_path(str(output["destination"]))
                succeeded = destination.exists() and not source.exists()
            elif operation in {"copy", "create_folder"}:
                succeeded = self._confined_path(str(output["destination"])).exists()
            elif operation == "delete_to_recycle_bin":
                succeeded = not self._confined_path(str(output["source"])).exists()
            elif operation == "restore":
                succeeded = self._confined_path(str(output["restored_path"])).exists()
            elif operation in {"list", "inspect", "find_latest", "exists", "hash"}:
                succeeded = True
            else:
                succeeded = result.succeeded
        except (KeyError, ValueError, OSError):
            succeeded = False
        return VerificationResult(
            succeeded=succeeded,
            reason=(
                "Independent filesystem state verification passed"
                if succeeded
                else "Independent filesystem state verification failed"
            ),
            observed=output,
        )

    def _execute(self, request: CapabilityRequest) -> CapabilityResult:
        capability = request.capability
        if capability == "filesystem.list":
            folder = self._confined_path(self._argument(request, "folder", "."), must_exist=True)
            if not folder.is_dir():
                raise ValueError("folder_not_found")
            limit = min(max(int(request.arguments.get("limit", 100)), 1), 1000)
            entries = [self._entry(item) for item in sorted(folder.iterdir())[:limit]]
            return self._success(request, "list", {"folder": str(folder), "entries": entries})
        if capability == "filesystem.inspect":
            path = self._confined_path(self._argument(request, "path"), must_exist=True)
            return self._success(request, "inspect", self._metadata(path))
        if capability == "filesystem.find_latest":
            folder = self._confined_path(self._argument(request, "folder", "."), must_exist=True)
            if not folder.is_dir():
                raise ValueError("folder_not_found")
            pattern = str(request.arguments.get("pattern", "*"))
            candidates = [item for item in folder.glob(pattern) if item.is_file()]
            candidates = [item for item in candidates if not self._has_link(item, folder)]
            if not candidates:
                return self._success(
                    request, "find_latest", {"folder": str(folder), "found": False}
                )
            latest = max(candidates, key=lambda item: item.stat().st_mtime_ns)
            return self._success(
                request,
                "find_latest",
                {
                    "folder": str(folder),
                    "found": True,
                    "path": str(latest),
                    **self._metadata(latest),
                },
            )
        if capability == "filesystem.exists":
            path = self._confined_path(self._argument(request, "path"))
            return self._success(request, "exists", {"path": str(path), "exists": path.exists()})
        if capability == "filesystem.hash":
            path = self._confined_path(self._argument(request, "path"), must_exist=True)
            if not path.is_file():
                raise ValueError("file_not_found")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            return self._success(request, "hash", {"path": str(path), "sha256": digest.hexdigest()})
        if capability == "filesystem.create_folder":
            destination = self._confined_path(self._argument(request, "path"))
            if destination.exists():
                if destination.is_dir():
                    return self._success(
                        request,
                        "create_folder",
                        {"destination": str(destination), "already_exists": True},
                    )
                raise ValueError("destination_collision")
            self._require_parent(destination)
            if request.preview:
                return self._preview(request, "create_folder", {"destination": str(destination)})
            destination.mkdir()
            token = self._journal("create_folder", source=None, destination=destination)
            return self._success(
                request, "create_folder", {"destination": str(destination), "rollback_token": token}
            )
        if capability in {"filesystem.rename", "filesystem.copy", "filesystem.move"}:
            source = self._confined_path(self._argument(request, "source"), must_exist=True)
            destination = self._destination_for(request, source)
            destination = self._resolve_collision(destination, request)
            self._require_parent(destination)
            if request.preview:
                return self._preview(
                    request,
                    capability.removeprefix("filesystem."),
                    {"source": str(source), "destination": str(destination)},
                )
            if capability == "filesystem.rename":
                source.rename(destination)
            elif capability == "filesystem.copy":
                self._copy(source, destination)
            else:
                shutil.move(str(source), str(destination))
            operation = capability.removeprefix("filesystem.")
            token = self._journal(operation, source=source, destination=destination)
            return self._success(
                request,
                operation,
                {"source": str(source), "destination": str(destination), "rollback_token": token},
            )
        if capability == "filesystem.delete_to_recycle_bin":
            source = self._confined_path(self._argument(request, "path"), must_exist=True)
            if request.preview:
                return self._preview(
                    request, "delete_to_recycle_bin", {"source": str(source), "recycle_bin": True}
                )
            token = new_id()
            backup = self._backup(source, token)
            try:
                self._recycle(source)
            except Exception:
                self._remove_tree(backup)
                raise
            self._save_journal(
                token,
                {
                    "operation": "delete_to_recycle_bin",
                    "source": str(source),
                    "backup": str(backup),
                },
            )
            return self._success(
                request,
                "delete_to_recycle_bin",
                {"source": str(source), "recycle_bin": True, "rollback_token": token},
            )
        if capability == "filesystem.restore":
            token_value = self._argument(request, "rollback_token")
            if not isinstance(token_value, str):
                raise ValueError("invalid_rollback_token")
            record = self._load_journal(token_value)
            return self._restore(request, record)
        if capability in {"explorer.open_folder", "explorer.select_file"}:
            path = self._confined_path(self._argument(request, "path"), must_exist=True)
            if capability == "explorer.open_folder" and not path.is_dir():
                raise ValueError("folder_not_found")
            if capability == "explorer.select_file" and not path.is_file():
                raise ValueError("file_not_found")
            if request.preview:
                return self._preview(
                    request, capability.removeprefix("explorer."), {"path": str(path)}
                )
            if sys.platform != "win32":
                raise RuntimeError("File Explorer is only available on Windows")
            if capability == "explorer.open_folder":
                os.startfile(str(path))
            else:
                subprocess.Popen(["explorer.exe", "/select,", str(path)], close_fds=True)
            return self._success(
                request, capability.removeprefix("explorer."), {"path": str(path), "opened": True}
            )
        return self._failure(request, "capability_not_supported")

    def _destination_for(self, request: CapabilityRequest, source: Path) -> Path:
        raw = request.arguments.get("destination")
        if raw is None:
            name = request.arguments.get("destination_name")
            if not isinstance(name, str) or not name.strip() or Path(name).name != name:
                raise ValueError("destination_or_destination_name_required")
            raw = str(source.parent / name)
        return self._confined_path(str(raw))

    def _resolve_collision(self, destination: Path, request: CapabilityRequest) -> Path:
        if not destination.exists():
            return destination
        policy = str(request.arguments.get("collision_policy", "reject"))
        if policy == "unique":
            stem, suffix = destination.stem, destination.suffix
            for index in range(1, 1000):
                candidate = destination.with_name(f"{stem} ({index}){suffix}")
                if not candidate.exists():
                    return candidate
        raise ValueError("destination_collision")

    def _confined_path(self, value: object, *, must_exist: bool = False) -> Path:
        if not isinstance(value, str) or not value.strip() or "\0" in value:
            raise ValueError("invalid_path")
        candidate = Path(value).expanduser()
        if any(part == ".." for part in candidate.parts):
            raise ValueError("path_traversal_not_allowed")
        path = (
            candidate.resolve()
            if candidate.is_absolute()
            else (self.approved_roots[0] / candidate).resolve()
        )
        if not any(path == root or path.is_relative_to(root) for root in self.approved_roots):
            raise ValueError("path_outside_approved_roots")
        root = next(
            root for root in self.approved_roots if path == root or path.is_relative_to(root)
        )
        if self._has_link(path, root):
            raise ValueError("symlink_or_junction_not_allowed")
        if must_exist and not path.exists():
            raise ValueError("path_not_found")
        return path

    @staticmethod
    def _has_link(path: Path, root: Path) -> bool:
        current = path
        while True:
            if current.is_symlink():
                return True
            junction_check = getattr(current, "is_junction", None)
            if callable(junction_check) and junction_check():
                return True
            if current == root or current.parent == current:
                return False
            current = current.parent

    def _require_parent(self, destination: Path) -> None:
        if not destination.parent.exists() or not destination.parent.is_dir():
            raise ValueError("destination_parent_not_found")
        self._confined_path(str(destination.parent), must_exist=True)

    @staticmethod
    def _copy(source: Path, destination: Path) -> None:
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)

    def _backup(self, source: Path, token: str) -> Path:
        folder = self.rollback_root / token
        folder.mkdir(parents=True, exist_ok=False)
        backup = folder / source.name
        self._copy(source, backup)
        return backup

    def _restore(self, request: CapabilityRequest, record: dict[str, Any]) -> CapabilityResult:
        operation = str(record.get("operation"))
        if operation == "delete_to_recycle_bin":
            source_path = self._confined_path(str(record["source"]))
            backup = Path(str(record["backup"])).resolve()
            if source_path.exists():
                raise ValueError("restore_destination_exists")
            if not backup.exists():
                raise ValueError("rollback_backup_not_found")
            if request.preview:
                return self._preview(request, "restore", {"restored_path": str(source_path)})
            self._copy(backup, source_path)
            return self._success(
                request,
                "restore",
                {
                    "restored_path": str(source_path),
                    "rollback_token": request.arguments["rollback_token"],
                },
            )
        rollback_source = (
            self._confined_path(str(record["source"])) if record.get("source") else None
        )
        destination = (
            self._confined_path(str(record["destination"])) if record.get("destination") else None
        )
        if request.preview:
            return self._preview(
                request, "restore", {"restored_path": str(rollback_source or destination)}
            )
        if (
            operation in {"rename", "move"}
            and rollback_source
            and destination
            and destination.exists()
            and not rollback_source.exists()
        ):
            destination.rename(rollback_source)
        elif operation == "copy" and destination and destination.exists():
            self._remove_tree(destination)
        elif (
            operation == "create_folder"
            and destination
            and destination.is_dir()
            and not any(destination.iterdir())
        ):
            destination.rmdir()
        else:
            raise ValueError("rollback_state_not_available")
        return self._success(
            request,
            "restore",
            {
                "restored_path": str(rollback_source or destination),
                "rollback_token": request.arguments["rollback_token"],
            },
        )

    def _journal(self, operation: str, *, source: Path | None, destination: Path) -> str:
        token = new_id()
        self._save_journal(
            token,
            {
                "operation": operation,
                "source": str(source) if source else None,
                "destination": str(destination),
            },
        )
        return token

    def _save_journal(self, token: str, record: dict[str, Any]) -> None:
        (self.rollback_root / f"{token}.json").write_text(
            json.dumps(record, sort_keys=True), encoding="utf-8"
        )

    def _load_journal(self, token: str) -> dict[str, Any]:
        if not isinstance(token, str) or Path(token).name != token:
            raise ValueError("invalid_rollback_token")
        path = self.rollback_root / f"{token}.json"
        if not path.exists():
            raise ValueError("rollback_token_not_found")
        return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))

    @staticmethod
    def _remove_tree(path: Path) -> None:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        elif path.exists() or path.is_symlink():
            path.unlink()

    @staticmethod
    def _recycle(path: Path) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Recycle Bin deletion is only available on Windows")
        source = f"{path}\0\0"
        operation = _ShellFileOp(
            operation=3,
            from_path=source,
            flags=0x0040 | 0x0010 | 0x0004,
        )
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
        if result != 0 or operation.aborted:
            raise OSError(f"Recycle Bin operation failed: {result}")

    @staticmethod
    def _entry(path: Path) -> dict[str, Any]:
        stats = path.stat()
        return {
            "name": path.name,
            "path": str(path),
            "kind": "directory" if path.is_dir() else "file",
            "size": stats.st_size,
            "modified_at": datetime.fromtimestamp(stats.st_mtime, UTC).isoformat(),
        }

    @staticmethod
    def _metadata(path: Path) -> dict[str, Any]:
        value = FilesystemAdapter._entry(path)
        value["exists"] = True
        return value

    @staticmethod
    def _argument(request: CapabilityRequest, name: str, default: object = None) -> object:
        value = request.arguments.get(name, default)
        if value is None:
            raise ValueError(f"{name}_required")
        return value

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
        return self._success(
            request.model_copy(update={"preview": True}),
            operation,
            {**output, "mutation_performed": False},
        )

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
