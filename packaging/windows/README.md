# MLLminal Windows installer

The release installer is a normal per-user Inno Setup executable. It carries a bundled Python runtime, the MLLminal wheel and dependencies, the daemon, the CLI, Mil, and the Textual TUI. Installed users do not need Python, uv, Git, a source checkout, or manual environment variables.

## Build the installer

Build-time tools are intentionally separate from installed-user requirements:

```powershell
uv run ruff check src tests
uv build --wheel --out-dir packaging/windows/dist
powershell -ExecutionPolicy Bypass -File packaging/windows/build-runtime.ps1
iscc packaging/windows/MLLminal.iss
```

Or run the release helper, which performs those steps, generates a package audit, and fails clearly if Inno Setup 6 is missing:

```powershell
powershell -ExecutionPolicy Bypass -File packaging/windows/build-installer.ps1
```

The runtime staging step uses Python only on the build machine. Before packaging, it removes known development debris (`__pycache__`, `.pytest_cache`, test directories, `.pyc`, `.pyo`, and source-map files) plus PyTorch header and third-party license source trees that local inference does not import; executable modules, installed package data, entry points, and the top-level PyTorch license are retained.

## Package audit

`package-audit.ps1` records reproducible size and performance fields in JSON:

- compressed setup size and before/after installer size
- staged runtime size and installed file count
- cold-install, first-launch, and daemon-readiness timings

The build helper always emits `packaging/windows/dist/MLLminal-package-audit.json`. For measured acceptance runs, pass timings collected on a clean fixture or machine:

```powershell
powershell -ExecutionPolicy Bypass -File packaging/windows/package-audit.ps1 `
  -DistributionDirectory packaging/windows/dist `
  -RuntimeDirectory packaging/windows/runtime `
  -ReportPath packaging/windows/dist/MLLminal-package-audit.json `
  -BeforeSetupBytes 0 `
  -ColdInstallSeconds 0 `
  -FirstLaunchSeconds 0 `
  -DaemonReadySeconds 0
```

Zero is the explicit “not measured” value; release evidence should replace it with observed timings rather than estimated values.

## Install for normal users

1. Download the Windows setup executable.
2. Double-click setup and keep the safe per-user defaults.
3. Optionally choose Advanced options for launch-at-login or a desktop shortcut.
4. Click Install and wait for the Ready page.
5. Launch Mil, MLLminal, MLLminal Terminal, or MLLminal Diagnostics from the Start Menu.

The installer includes the daemon, CLI, Textual TUI, Mil, Python runtime, dependencies, migrations, shortcuts, and uninstall support. Installed users do not need Python, uv, Git, a source checkout, or manual environment variables. The application lives under `%LOCALAPPDATA%\\Programs\\MLLminal`; mutable state lives under `%LOCALAPPDATA%\\MLLminal`.

## Upgrade and repair

Run the same setup executable again to repair the current installation or update it. Setup stops only packaged MLLminal processes, backs up SQLite state before migration, preserves durable state, and checks daemon readiness. `/VERYSILENT /NORESTART` is supported for unattended setup.

Useful installed lifecycle commands:

```powershell
mllminal --version
mllminal status
mllminal doctor
mllminal service start
mllminal service stop
mllminal service restart
mllminal service status
mllminal install status
mllminal install repair
mllminal install data-path
```
## Uninstall and data retention

The normal uninstaller stops MLLminal-owned processes, removes the application, shortcuts, user PATH entry, startup shortcut, and owned browser-host registration. It retains local MLLminal data by default. The explicit CLI command below requires exact confirmation before removing only the MLLminal `data` and `backups` directories:

```powershell
mllminal install purge-data --confirm MLLMINAL
```

User-created documents, spreadsheets, PDFs, downloads, reports, and workflow outputs outside those owned directories are never targeted. Silent uninstall retains data unless an explicit purge command is used.

`doctor.ps1` provides a read-only installed-runtime report. `export-diagnostics.ps1` exports diagnostics without tokens, credentials, databases, or session material.