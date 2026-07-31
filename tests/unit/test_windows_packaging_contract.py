from pathlib import Path

PACKAGING = Path(__file__).parents[2] / "packaging" / "windows"


def test_windows_technical_preview_packaging_is_provider_neutral_and_safe() -> None:
    install = (PACKAGING / "install.ps1").read_text(encoding="utf-8-sig")
    doctor = (PACKAGING / "doctor.ps1").read_text(encoding="utf-8-sig")
    diagnostics = (PACKAGING / "export-diagnostics.ps1").read_text(encoding="utf-8-sig")
    installer = (PACKAGING / "MLLminal.iss").read_text(encoding="utf-8-sig")
    build_runtime = (PACKAGING / "build-runtime.ps1").read_text(encoding="utf-8-sig")

    assert 'mode = "windows_technical_preview"' in install
    assert 'provider = "windows-observer"' in install
    assert 'provider = "workspace-filesystem"' in install
    assert 'provider = "manual-handoff"' in install
    assert "provider-inventory.json" in install
    assert '"email.send"' not in install
    assert '"email.send"' not in doctor

    assert "provider-inventory.json" in doctor
    assert "first-run.json" in doctor
    assert "technical_preview" in doctor
    assert "credentials" in diagnostics
    assert "provider-inventory.json" in diagnostics
    assert "mil-provider.json" not in diagnostics

    assert "runtime\\*" in installer
    assert "MLLminal Terminal" in installer
    assert "DefaultDirName={localappdata}\\Programs\\MLLminal" in installer
    assert "DataDirectory" in installer
    assert 'Parameters: "mil"' in installer
    assert 'Parameters: "tui"' in installer
    assert "Bundled runtime ready" in build_runtime
    assert "SetEnvironmentVariable" in install
    assert "install-manifest.json" in install


def test_windows_uninstall_preserves_data_without_explicit_delete() -> None:
    uninstall = (PACKAGING / "uninstall.ps1").read_text(encoding="utf-8-sig")

    assert "[switch]$DeleteData" in uninstall
    assert "Local data was retained" in uninstall
    assert "mllminald" in uninstall
    assert "mllminal-ui" in uninstall
    assert "mllminal" in uninstall
    assert "SetEnvironmentVariable" in uninstall
    assert "NativeMessagingHosts" in uninstall


def test_installer_compiler_resolves_program_files_x86_safely() -> None:
    build_installer = (PACKAGING / "build-installer.ps1").read_text(encoding="utf-8-sig")

    assert "${env:ProgramFiles(x86)}" in build_installer
    assert "${env:LOCALAPPDATA}" in build_installer
    assert "$isccPath" in build_installer


def test_inno_run_parameters_use_inno_quote_escaping() -> None:
    installer = (PACKAGING / "MLLminal.iss").read_text(encoding="utf-8-sig")

    assert '-File ""{app}\\install.ps1""' in installer
    assert '-File \\"{app}\\install.ps1\\"' not in installer
    assert '-File ""{app}\\uninstall.ps1""' in installer


def test_one_click_installer_uses_safe_defaults_and_friendly_shortcuts() -> None:
    install = (PACKAGING / "install.ps1").read_text(encoding="utf-8-sig")
    installer = (PACKAGING / "MLLminal.iss").read_text(encoding="utf-8-sig")

    assert '[string]$InstallRoot = "$env:LOCALAPPDATA\\Programs\\MLLminal"' in install
    assert "DefaultDirName={localappdata}\\Programs\\MLLminal" in installer
    assert 'Name: "advanced"' in installer
    assert 'Name: "advanced\\startup"' in installer
    assert 'Name: "advanced\\desktop"' in installer
    assert 'Name: "advanced\\retain_data"' in installer
    assert 'Name: "{group}\\MLLminal"' in installer
    assert 'Name: "{group}\\Mil"' in installer
    assert 'Name: "{group}\\MLLminal Terminal"' in installer
    assert 'Name: "{group}\\MLLminal Diagnostics"' in installer
    assert 'Name: "{group}\\Uninstall MLLminal"' in installer
    assert 'Parameters: "tui"' in installer
    assert 'Parameters: "mil"' in installer
    assert "-NoExit" in installer
    assert "doctor" in installer
    assert "[switch]$CreateDesktopShortcut" in install


def test_installed_clients_use_bounded_daemon_readiness_and_diagnostics() -> None:
    install = (PACKAGING / "install.ps1").read_text(encoding="utf-8-sig")
    service = (Path(__file__).parents[2] / "src" / "mllminal" / "service_lifecycle.py").read_text(
        encoding="utf-8-sig"
    )

    assert "ensure_daemon" in install
    assert "diagnostics" in install
    assert "daemon_lock_path" in service
    assert "DaemonStartupError" in service
    assert "already_running" in service


def test_install_script_detects_repair_and_update_before_migration() -> None:
    install = (PACKAGING / "install.ps1").read_text(encoding="utf-8-sig")

    assert "install_mode" in install
    assert "prepare_update" in install
    assert "backup" in install.lower()


def test_uninstall_supports_silent_safe_defaults_and_removes_owned_shortcuts() -> None:
    installer = (PACKAGING / "MLLminal.iss").read_text(encoding="utf-8-sig")
    uninstall = (PACKAGING / "uninstall.ps1").read_text(encoding="utf-8-sig")

    assert "/VERYSILENT" in installer
    assert "/NORESTART" in installer
    assert "Also delete MLLminal local data" in installer
    assert "WizardSilent" in installer
    assert "[switch]$Silent" in uninstall
    assert "MLLminal Terminal" in uninstall
    assert "MLLminal Diagnostics" in uninstall
    assert "Uninstall MLLminal" in uninstall
    assert 'GetFolderPath("Desktop")' in uninstall
    assert "Local data was retained" in uninstall
    assert "DeleteData" in uninstall
    assert "$env:USERPROFILE" not in uninstall
    assert "$env:USERPROFILE" not in installer
