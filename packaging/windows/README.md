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

Or run the release helper, which performs those steps and fails clearly if Inno Setup 6 is missing:

```powershell
powershell -ExecutionPolicy Bypass -File packaging/windows/build-installer.ps1
```

The runtime staging step uses Python only on the build machine. The resulting setup executable installs under `%LOCALAPPDATA%\MLLminal\app`; mutable state is stored separately under `%LOCALAPPDATA%\MLLminal\data`, with migration backups under `%LOCALAPPDATA%\MLLminal\backups`.

## Install, repair, and upgrade

Run setup as the current user. It adds the bundled `runtime\Scripts` directory to the user PATH, initializes local state, validates or upgrades SQLite migrations after creating a database backup, and optionally creates a daemon-at-login shortcut. Existing data, workflows, history, profiles, approvals, sessions, settings, and learning metadata remain outside the application directory during upgrades.

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

An unknown database revision is rejected as an unsafe downgrade. The repair operation backs up the SQLite database and any WAL/SHM sidecars before migration.

## Uninstall and data retention

The normal uninstaller stops MLLminal-owned processes, removes the application, shortcuts, user PATH entry, startup shortcut, and owned browser-host registration. It retains local MLLminal data by default. The explicit CLI command below requires exact confirmation before removing only the MLLminal `data` and `backups` directories:

```powershell
mllminal install purge-data --confirm MLLMINAL
```

User-created documents, spreadsheets, PDFs, downloads, reports, and workflow outputs outside those owned directories are never targeted.

`doctor.ps1` provides a read-only installed-runtime report. `export-diagnostics.ps1` exports diagnostics without tokens, credentials, databases, or session material.