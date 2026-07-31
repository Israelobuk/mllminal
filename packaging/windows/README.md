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

The runtime staging step uses Python only on the build machine. Before packaging, it removes only known development debris (`__pycache__`, `.pytest_cache`, test directories, `.pyc`, `.pyo`, and source-map files); it does not remove installed package data or entry points.

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

## Install, repair, and upgrade

Run setup as the current user. The default application path is `%LOCALAPPDATA%\Programs\MLLminal`; mutable state is stored separately under `%LOCALAPPDATA%\MLLminal`. Setup adds the bundled `runtime\Scripts` directory to the user PATH, initializes local state, validates or upgrades SQLite migrations after creating a database backup, starts the local daemon, and optionally creates a daemon-at-login shortcut.

After opening a new PowerShell window:

```powershell
mllminal --version
mllminal doctor
mllminal mil
mllminal tui
```

Repair an existing installation with:

```powershell
mllminal install status
mllminal install repair
mllminal install data-path
```

An unknown database revision is rejected as an unsafe downgrade. Repair and update operations back up the SQLite database and any WAL/SHM sidecars before migration while preserving workflows, history, profiles, approvals, sessions, settings, and learning metadata.

## Uninstall and data retention

The normal uninstaller stops MLLminal-owned processes, removes the application, shortcuts, user PATH entry, startup shortcut, and owned browser-host registration. It retains local MLLminal data by default. The explicit CLI command below requires exact confirmation before removing only the MLLminal `data` and `backups` directories:

```powershell
mllminal install purge-data --confirm MLLMINAL
```

User-created documents, spreadsheets, PDFs, downloads, reports, and workflow outputs outside those owned directories are never targeted. Silent uninstall retains data unless an explicit purge command is used.

`doctor.ps1` provides a read-only installed-runtime report. `export-diagnostics.ps1` exports diagnostics without tokens, credentials, databases, or session material.