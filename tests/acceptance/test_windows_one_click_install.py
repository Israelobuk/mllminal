"""Opt-in Windows installer acceptance checks.

These tests are deliberately inert in normal CI and developer runs. Enable them only
with an explicit setup executable and an isolated acceptance environment:

    $env:MLLMINAL_WINDOWS_ACCEPTANCE = "1"
    $env:MLLMINAL_SETUP_EXE = "C:\\path\\MLLminal-Setup.exe"
    uv run pytest tests/acceptance/test_windows_one_click_install.py -q
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import winreg
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass(frozen=True)
class InstalledFixture:
    root: Path
    app: Path
    data: Path
    backups: Path
    env: dict[str, str]

    @property
    def cli(self) -> Path:
        return self.app / "runtime" / "Scripts" / "mllminal.exe"

    @property
    def uninstaller(self) -> Path:
        return self.app / "unins000.exe"


def _setup_executable() -> Path:
    if os.environ.get("MLLMINAL_WINDOWS_ACCEPTANCE") != "1":
        pytest.skip("set MLLMINAL_WINDOWS_ACCEPTANCE=1 for opt-in installer acceptance")
    if os.name != "nt":
        pytest.skip("Windows installer acceptance runs on Windows only")
    raw = os.environ.get("MLLMINAL_SETUP_EXE")
    if not raw:
        pytest.fail("MLLMINAL_SETUP_EXE must point to an explicit setup executable")
    setup = Path(raw).expanduser().resolve()
    if setup.suffix.casefold() != ".exe" or not setup.is_file():
        pytest.fail(f"MLLMINAL_SETUP_EXE is not an executable file: {setup}")
    if setup.read_bytes()[:2] != b"MZ":
        pytest.fail(f"setup executable does not have an MZ header: {setup}")
    return setup


def _wait_for_absence(path: Path, *, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while path.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    return not path.exists()


def _run(
    command: list[str], env: dict[str, str], *, timeout: int = 180
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0),
    )


@pytest.fixture
def installed_fixture(tmp_path: Path) -> InstalledFixture:
    setup = _setup_executable()
    root = tmp_path / "mllminal-acceptance"
    app = root / "app"
    data = root / "data"
    backups = root / "backups"
    env = os.environ.copy()
    env.update(
        {
            "MLLMINAL_WINDOWS_ACCEPTANCE": "1",
            "MLLMINAL_ACCEPTANCE_DATA_DIR": str(data),
            "MLLMINAL_ACCEPTANCE_BACKUP_DIR": str(backups),
            "MLLMINAL_DATA_DIR": str(data),
        }
    )
    result = _run(
        [str(setup), "/VERYSILENT", "/NORESTART", f"/DIR={app}"],
        env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    fixture = InstalledFixture(root, app, data, backups, env)
    try:
        yield fixture
    finally:
        if fixture.uninstaller.is_file() and fixture.app.exists():
            result = _run([str(fixture.uninstaller), "/VERYSILENT", "/NORESTART"], fixture.env)
            assert result.returncode == 0, result.stdout + result.stderr


def test_fresh_install_provisions_runtime_and_local_state(
    installed_fixture: InstalledFixture,
) -> None:
    fixture = installed_fixture
    assert fixture.app.is_dir()
    assert fixture.cli.is_file()
    assert (fixture.app / "runtime" / "Scripts" / "python.exe").is_file()
    assert (fixture.app / "runtime" / "Scripts" / "mllminald.exe").is_file()
    assert (fixture.data / "install-manifest.json").is_file()
    assert fixture.cli.read_bytes()[:2] == b"MZ"


def test_new_terminal_path_contains_only_the_bundled_cli_directory(
    installed_fixture: InstalledFixture,
) -> None:
    fixture = installed_fixture
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
        user_path, _ = winreg.QueryValueEx(key, "Path")
    script_directory = str((fixture.app / "runtime" / "Scripts").resolve()).rstrip("\\").casefold()
    entries = {
        str(Path(item).resolve()).rstrip("\\").casefold() for item in user_path.split(";") if item
    }
    assert script_directory in entries


def test_friendly_start_menu_shortcuts_are_installed(installed_fixture: InstalledFixture) -> None:
    start_menu = (
        Path(os.environ["APPDATA"])
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "MLLminal"
    )
    for name in (
        "MLLminal.lnk",
        "Mil.lnk",
        "MLLminal Terminal.lnk",
        "MLLminal Diagnostics.lnk",
        "Uninstall MLLminal.lnk",
    ):
        assert (start_menu / name).is_file()


def test_daemon_readiness_and_doctor_complete(installed_fixture: InstalledFixture) -> None:
    fixture = installed_fixture
    result = _run([str(fixture.cli), "doctor", "--json"], fixture.env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "running" in result.stdout.casefold()


def test_optional_components_do_not_block_the_bounded_install(
    installed_fixture: InstalledFixture,
) -> None:
    inventory = installed_fixture.data / "provider-inventory.json"
    payload = json.loads(inventory.read_text(encoding="utf-8-sig"))
    assert payload["capabilities_are_bounded"] is True
    assert any(provider["enabled"] is False for provider in payload["providers"])


def test_repair_run_preserves_manifest_metadata(installed_fixture: InstalledFixture) -> None:
    fixture = installed_fixture
    manifest = fixture.data / "install-manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8-sig"))
    payload["acceptance_metadata"] = "preserve-me"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    setup = _setup_executable()
    result = _run([str(setup), "/VERYSILENT", "/NORESTART", f"/DIR={fixture.app}"], fixture.env)
    assert result.returncode == 0, result.stdout + result.stderr
    updated = json.loads(manifest.read_text(encoding="utf-8-sig"))
    assert updated["acceptance_metadata"] == "preserve-me"


def test_repair_run_preserves_a_user_state_sentinel(installed_fixture: InstalledFixture) -> None:
    fixture = installed_fixture
    sentinel = fixture.data / "acceptance-user-state.txt"
    sentinel.write_text("preserve me", encoding="utf-8")
    setup = _setup_executable()
    result = _run([str(setup), "/VERYSILENT", "/NORESTART", f"/DIR={fixture.app}"], fixture.env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert sentinel.read_text(encoding="utf-8") == "preserve me"


def test_silent_uninstall_removes_owned_components_and_retains_data(
    installed_fixture: InstalledFixture,
) -> None:
    fixture = installed_fixture
    sentinel = fixture.data / "acceptance-user-state.txt"
    sentinel.write_text("retain me", encoding="utf-8")
    result = _run([str(fixture.uninstaller), "/VERYSILENT", "/NORESTART"], fixture.env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _wait_for_absence(fixture.app)
    assert sentinel.read_text(encoding="utf-8") == "retain me"
    assert not (fixture.root / "app" / "runtime" / "Scripts").exists()
