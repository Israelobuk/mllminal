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
    assert "MLLminal TUI" in installer
    assert "DefaultDirName={localappdata}\\MLLminal\\app" in installer
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
