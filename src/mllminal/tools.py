"""Narrow, typed, read-only project tools."""

from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from mllminal.contracts import RiskLevel, VerificationResult


class WorkspaceBoundaryError(PermissionError):
    pass


class ToolDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    risk: RiskLevel = RiskLevel.LOW
    required_permission: str = "filesystem.read"
    reversible: bool = True
    verifier: str


class ToolRegistry:
    definitions: ClassVar[dict[str, ToolDefinition]] = {
        "project.list_files": ToolDefinition(
            name="project.list_files", verifier="verify_file_listing"
        ),
        "project.read_text": ToolDefinition(name="project.read_text", verifier="verify_text_read"),
        "project.inspect_metadata": ToolDefinition(
            name="project.inspect_metadata", verifier="verify_project_metadata"
        ),
    }

    def execute(self, name: str, arguments: dict[str, Any], workspace: Path) -> dict[str, Any]:
        if name not in self.definitions:
            raise KeyError(name)
        root = workspace.resolve(strict=True)
        if name == "project.list_files":
            target = self._confined(root, str(arguments.get("path", ".")))
            all_files = sorted(
                path.relative_to(root).as_posix()
                for path in target.rglob("*")
                if path.is_file() and not path.is_symlink()
            )
            return {"root": str(root), "files": all_files[:200], "truncated": len(all_files) > 200}
        if name == "project.read_text":
            target = self._confined(root, str(arguments["path"]))
            if target.stat().st_size > 1_048_576:
                raise ValueError("File exceeds the 1 MiB read limit")
            return {
                "path": target.relative_to(root).as_posix(),
                "content": target.read_text(encoding="utf-8"),
            }
        configs = [
            item
            for item in ("pyproject.toml", "requirements.txt", "Cargo.toml", "package.json")
            if (root / item).is_file()
        ]
        if {"pyproject.toml", "requirements.txt"} & set(configs):
            project_type = "python"
        elif "Cargo.toml" in configs:
            project_type = "rust"
        elif "package.json" in configs:
            project_type = "node"
        else:
            project_type = "unknown"
        return {
            "root": str(root),
            "project_type": project_type,
            "configuration_files": configs,
            "file_count": sum(1 for path in root.rglob("*") if path.is_file()),
        }

    def verify(self, name: str, output: dict[str, Any]) -> VerificationResult:
        if name == "project.list_files":
            succeeded = isinstance(output.get("files"), list)
        elif name == "project.read_text":
            succeeded = isinstance(output.get("content"), str)
        else:
            succeeded = bool(output.get("root")) and isinstance(output.get("file_count"), int)
        return VerificationResult(
            task_id="pending",
            execution_id="pending",
            succeeded=succeeded,
            detail="Typed tool result validated" if succeeded else "Tool result failed validation",
        )

    @staticmethod
    def _confined(root: Path, relative_path: str) -> Path:
        candidate = (root / relative_path).resolve(strict=True)
        if not candidate.is_relative_to(root):
            raise WorkspaceBoundaryError(f"Path escapes attached workspace: {relative_path}")
        return candidate
