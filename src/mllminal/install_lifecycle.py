"""Safe, local installation lifecycle operations for the Windows product."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy import create_engine
from sqlalchemy.exc import DatabaseError

from mllminal.config import Settings
from mllminal.migrations import upgrade_database


class InstallLifecycleError(RuntimeError):
    """A safe installation lifecycle operation could not be completed."""


@dataclass(frozen=True)
class InstallPaths:
    app_root: Path
    data_root: Path
    runtime_root: Path
    backup_root: Path
    manifest_path: Path


class InstallLifecycle:
    """Inspect and repair only MLLminal-owned installation state."""

    CONFIRMATION = "MLLMINAL"

    def __init__(self, settings: Settings, *, app_root: Path | None = None) -> None:
        data_root = settings.data_dir.resolve()
        self.settings = settings
        self.paths = InstallPaths(
            app_root=(app_root or data_root.parent / "app").resolve(),
            data_root=data_root,
            runtime_root=(app_root or data_root.parent / "app").resolve() / "runtime",
            backup_root=(data_root.parent / "backups").resolve(),
            manifest_path=data_root / "install-manifest.json",
        )

    def status(self) -> dict[str, Any]:
        paths = self.paths
        manifest = self._read_manifest()
        current = self._current_revision()
        head = self._migration_head()
        return {
            "installed": paths.app_root.is_dir() and paths.manifest_path.is_file(),
            "app_root": str(paths.app_root),
            "data_root": str(paths.data_root),
            "runtime_root": str(paths.runtime_root),
            "backup_root": str(paths.backup_root),
            "runtime_ready": self._runtime_ready(),
            "database_exists": self.settings.database_path.is_file(),
            "migration_current": current,
            "migration_head": head,
            "migrations_current": current == head if head is not None else False,
            "path_registered": bool(manifest.get("path_registered", False)),
            "startup_enabled": bool(manifest.get("startup_enabled", False)),
            "version": manifest.get("version"),
        }

    def data_path(self) -> dict[str, str]:
        return {
            "data_root": str(self.paths.data_root),
            "database": str(self.settings.database_path),
            "backups": str(self.paths.backup_root),
        }

    def repair(self) -> dict[str, Any]:
        paths = self.paths
        if not paths.app_root.is_dir():
            raise InstallLifecycleError(f"installed app root is missing: {paths.app_root}")
        paths.data_root.mkdir(parents=True, exist_ok=True)
        backup = self._backup_database()
        current = self._current_revision()
        head = self._migration_head()
        if current is not None and not self._revision_is_known(current):
            raise InstallLifecycleError(f"unsafe downgrade or unknown database revision: {current}")
        upgrade_database(self.settings.database_path)
        self._write_manifest(
            {
                "version": self._read_manifest().get("version"),
                "path_registered": self._read_manifest().get("path_registered", False),
                "startup_enabled": self._read_manifest().get("startup_enabled", False),
            }
        )
        return {
            "status": "repaired",
            "backup": str(backup) if backup is not None else None,
            "migration_before": current,
            "migration_after": self._current_revision(),
            "migration_head": head,
        }

    def purge(self, confirmation: str | None) -> dict[str, Any]:
        if confirmation != self.CONFIRMATION:
            raise InstallLifecycleError(
                f"confirmation required; pass --confirm {self.CONFIRMATION}"
            )
        data_root = self.paths.data_root
        if data_root == data_root.parent or data_root.name.lower() != "data":
            raise InstallLifecycleError(f"refusing to purge an unscoped data root: {data_root}")
        removed: list[str] = []
        for target in (data_root, self.paths.backup_root):
            if target.exists():
                shutil.rmtree(target)
                removed.append(str(target))
        return {"status": "purged", "removed": removed}

    def _runtime_ready(self) -> bool:
        runtime = self.paths.runtime_root
        return all(
            (runtime / relative).is_file()
            for relative in (
                Path("Scripts/python.exe"),
                Path("Scripts/mllminal.exe"),
                Path("Scripts/mllminald.exe"),
                Path("Scripts/mllminal-ui.exe"),
            )
        )

    def _read_manifest(self) -> dict[str, Any]:
        try:
            value = json.loads(self.paths.manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def _write_manifest(self, updates: dict[str, Any]) -> None:
        self.paths.data_root.mkdir(parents=True, exist_ok=True)
        value = {
            **self._read_manifest(),
            **updates,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        temporary = self.paths.manifest_path.with_suffix(".json.next")
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.paths.manifest_path)

    def _backup_database(self) -> Path | None:
        database = self.settings.database_path
        if not database.exists():
            return None
        self.paths.backup_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        destination = self.paths.backup_root / f"mllminal-{stamp}.db"
        shutil.copy2(database, destination)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{database}{suffix}")
            if sidecar.exists():
                shutil.copy2(sidecar, Path(f"{destination}{suffix}"))
        return destination

    @staticmethod
    def _migration_configuration(database_path: Path) -> Config:
        configuration = Config()
        from mllminal import migrations

        configuration.set_main_option("script_location", str(Path(migrations.__file__).parent))
        configuration.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
        return configuration

    def _migration_head(self) -> str | None:
        script = ScriptDirectory.from_config(
            self._migration_configuration(self.settings.database_path)
        )
        return script.get_current_head()

    def _revision_is_known(self, revision: str) -> bool:
        script = ScriptDirectory.from_config(
            self._migration_configuration(self.settings.database_path)
        )
        try:
            return script.get_revision(revision) is not None
        except CommandError:
            return False

    def _current_revision(self) -> str | None:
        if not self.settings.database_path.exists():
            return None
        engine = create_engine(f"sqlite:///{self.settings.database_path.as_posix()}")
        try:
            try:
                with engine.connect() as connection:
                    return MigrationContext.configure(connection).get_current_revision()
            except DatabaseError as error:
                raise InstallLifecycleError("database is not a valid SQLite database") from error
        finally:
            engine.dispose()
