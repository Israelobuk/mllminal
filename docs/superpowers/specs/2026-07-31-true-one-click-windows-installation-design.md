# True One-Click Windows Installation Design

> **Status:** Approved for implementation from `origin/main` using Inno Setup.

## Goal

Make the Windows release behave like a normal per-user application: download one `MLLminal-Setup.exe`, accept safe defaults, and finish with MLLminal installed, ready, discoverable from the Start Menu, and removable without manual Python, terminal, PATH, migration, or daemon setup.

## Scope and constraints

- Keep the default install directory at `%LocalAppData%\\Programs\\MLLminal`.
- Keep mutable MLLminal-owned state at `%LocalAppData%\\MLLminal`.
- Keep Inno Setup as the release packaging layer because it already provides per-user setup, Add/Remove Programs registration, upgrade detection, and `/VERYSILENT`/`/NORESTART` switches.
- Normal setup exposes only Welcome, Install, and Ready; advanced choices are grouped behind one optional page.
- Optional Ollama, Office, OCR, and browser components never make core installation fail.
- Owned daemon and client processes are bounded, single-instance, and stopped before repair, update, or uninstall.
- Database migrations are preceded by a SQLite backup; unknown revisions block unsafe downgrade.
- Uninstall removes only installed components and MLLminal-owned registrations by default. Local data deletion is explicit and scoped.
- Every completed change is committed and pushed in a focused PR; CI must pass before squash merge and remote branch deletion.

## Architecture

The installer remains a thin orchestration layer. Inno Setup owns the user-facing wizard, shortcuts, Add/Remove Programs registration, and silent-mode switches. A bundled PowerShell bootstrapper owns deterministic install/update/repair work: it resolves the packaged Python runtime, installs the wheel without network access, initializes data directories, creates a migration backup, repairs the database, writes a versioned manifest, and registers PATH/startup state. Mil, the TUI, and CLI commands start the daemon through a shared bounded readiness helper when they open.

The installed CLI, Mil terminal, and Textual TUI all call one shared daemon readiness helper. It first checks the authenticated local health endpoint, starts the packaged daemon only when unavailable, waits for a bounded readiness deadline, and reports a product-level error with a diagnostics path when startup fails. The daemon uses a packaged-runtime ownership lock or equivalent PID guard to avoid duplicate processes.

## User flows

### Fresh install

`Welcome → Install → Ready` uses safe defaults: per-user install, no login startup unless selected in Advanced, no optional heavyweight provider, and no data deletion. The Ready page offers Launch Mil (default), Launch MLLminal TUI, and Open documentation. Installation logs and readiness results are written under the MLLminal diagnostics directory.

Shortcuts are:

- `MLLminal` → Textual TUI
- `Mil` → conversational terminal
- `MLLminal Terminal` → interactive terminal entry point
- `MLLminal Diagnostics` → a hidden `mllminal doctor --json` check that records `%LOCALAPPDATA%\\MLLminal\\diagnostics\\doctor-shortcut.json`
- `Uninstall MLLminal` → the registered uninstaller

### Reinstall, repair, and update

Running setup over an existing manifest preserves the data root and presents a simple repair/update path. Repair replaces missing application files, reapplies PATH and shortcuts, reruns safe migrations, and restarts the daemon. Update stops owned processes, backs up SQLite, replaces the packaged application, migrates, preserves durable state, and starts the daemon again. Existing valid approvals and policy bindings remain subject to their normal validity checks.

### Uninstall

The uninstaller uses a two-step flow with one unchecked `Also delete MLLminal local data` checkbox. It stops only MLLminal-owned processes, removes application files, PATH entries, shortcuts, startup registration, browser-host registrations, and installer registry state. It never traverses user document, download, report, or workflow-output locations. Silent uninstall keeps data unless an explicit data-delete switch is supplied.

## Error handling and diagnostics

User-facing failures use actionable messages such as “MLLminal could not start its local service. Your files were not changed. Choose Retry or open Diagnostics.” Technical details go to timestamped, MLLminal-owned diagnostic logs. Optional-component absence is reported as a warning and leaves deterministic fallback available. Install/update failures preserve the pre-existing data and database backup whenever possible.

## Package and performance work

The release build will audit the current approximately 250 MB setup package and record before/after compressed size, installed size, cold install duration, first-launch duration, and daemon-ready duration. Only test files, caches, source maps, development-only packages, duplicate runtime files, unused model artifacts, and unneeded documentation bundles may be removed, and each removal must be checked against the runtime import and launch tests.

## Verification strategy

- Unit tests cover Inno contract text, bootstrap arguments, shortcut targets, safe defaults, process ownership, readiness fallback, error messages, and silent-mode behavior.
- Integration tests exercise install/repair/update against isolated temporary app/data roots and a real SQLite database, including backups, migrations, state preservation, and scoped purge.
- Packaging tests build the wheel, stage the bundled runtime, compile the Inno setup executable, inspect its PE header, and measure artifact/installed sizes.
- Windows acceptance tests run from a clean machine or isolated Windows image without Python, Git, uv, or a source checkout; they launch the shortcuts, verify daemon readiness, exercise reinstall/repair/update, and validate uninstall process/PATH/registry/data invariants.
- Final validation runs the full test suite, Ruff, formatting, mypy, installer compilation, and Windows CI before each PR is squash-merged.

## Focused PR sequence

1. Simplify installer pages and safe defaults, including friendly shortcuts.
2. Add automatic daemon startup, single-instance guarding, first-launch readiness, and product-level diagnostics.
3. Add repair/update detection with state-preserving backups and migration behavior.
4. Finish one-click uninstall and explicit scoped data deletion.
5. Add silent install/uninstall acceptance coverage.
6. Audit package contents and record size/launch performance.
7. Update README and documentation for the true one-click user flow.
8. Run the final one-click installation audit and merge cleanup.

