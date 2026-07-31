# True One-Click Windows Installation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a single per-user `MLLminal-Setup.exe` that installs, starts, repairs, updates, and removes MLLminal without requiring Python, Git, uv, a source checkout, or post-install terminal setup.

**Architecture:** Inno Setup owns the minimal user wizard, Start Menu/Add/Remove Programs integration, and silent switches. A bundled PowerShell bootstrapper owns offline wheel installation, state initialization, safe migrations, manifest/version detection, process shutdown/startup, and bounded readiness diagnostics. CLI, Mil, and TUI share the Python `ensure_daemon` readiness path.

**Tech Stack:** Inno Setup 6, PowerShell, bundled CPython runtime, Python/Typer/Textual, SQLite/SQLAlchemy/Alembic, pytest, Ruff, mypy, GitHub Actions.

## Global Constraints

- Default install directory: `%LocalAppData%\\Programs\\MLLminal`.
- Default mutable data directory: `%LocalAppData%\\MLLminal`.
- Normal setup exposes only Welcome, Install, and Ready; advanced choices are behind one optional page.
- Optional Ollama, Office, OCR, and browser components cannot fail core installation.
- Data backups occur before migrations and unsafe downgrade revisions are rejected.
- Uninstall retains data by default and can delete only explicitly confirmed MLLminal-owned directories.
- Every completed file change is committed and pushed; focused PRs wait for CI, squash-merge, and delete feature branches.
- No real-machine uninstall test may stop unrelated processes or delete outside an exact temporary fixture.

---

### Task 1: Simplify the Inno Setup wizard and safe defaults

**Files:**
- Modify: `packaging/windows/MLLminal.iss`
- Modify: `packaging/windows/install.ps1`
- Test: `tests/unit/test_windows_packaging_contract.py`

**Interfaces:**
- Inno invokes `install.ps1` with `-InstallRoot`, `-DataDirectory`, `-BackupDirectory`, `-EnableStartup`, `-CreateDesktopShortcut`, and `-Repair`.
- `install.ps1` accepts absent optional switches as safe false values and uses `%LOCALAPPDATA%\\Programs\\MLLminal` for the application root.

- [ ] **Step 1: Write failing contract tests**

Add assertions that the `.iss` file uses `DefaultDirName={localappdata}\\Programs\\MLLminal`, has no `lightweight` or `portableprovider` task, contains one Advanced page or equivalent single grouped options surface, defines the five friendly shortcut names, targets `mllminal.exe tui` for the main shortcut, targets `mllminal.exe mil` for Mil, and uses a diagnostics shortcut that runs `mllminal doctor` in a readable terminal.

- [ ] **Step 2: Run the focused test and confirm the expected failure**

Run `uv run pytest tests/unit/test_windows_packaging_contract.py -q`. It must fail on the old default path, technical tasks, and missing shortcuts.

- [ ] **Step 3: Implement the minimal installer change**

Replace technical tasks with one `Advanced` task/page containing only install location, startup-at-login, desktop shortcut, and retain-existing-data choices. Set safe defaults to no startup, no desktop shortcut, and retain data. Add Start Menu entries named `MLLminal`, `Mil`, `MLLminal Terminal`, `MLLminal Diagnostics`, and `Uninstall MLLminal`; point the first two to the packaged CLI with `tui` and `mil` parameters. Add an explicit `doctor` terminal shortcut using `powershell.exe -NoExit -Command ... mllminal doctor`.

- [ ] **Step 4: Run focused tests and a syntax check**

Run `uv run pytest tests/unit/test_windows_packaging_contract.py -q` and `git diff --check`. Both must exit 0.

- [ ] **Step 5: Commit the focused slice**

Run `git add packaging/windows/MLLminal.iss packaging/windows/install.ps1 tests/unit/test_windows_packaging_contract.py && git commit -m "feat: simplify Windows installer defaults and shortcuts"`.

### Task 2: Add packaged daemon ownership and bounded first-launch readiness

**Files:**
- Modify: `src/mllminal/service_lifecycle.py`
- Modify: `src/mllminal/cli/terminal_commands.py`
- Modify: `src/mllminal/client/app.py`
- Modify: `src/mllminal/client/mil.py`
- Modify: `packaging/windows/install.ps1`
- Modify: `packaging/windows/doctor.ps1`
- Test: `tests/unit/test_service_lifecycle.py`
- Test: `tests/unit/test_cli_terminal_commands.py`
- Test: `tests/unit/test_windows_packaging_contract.py`

**Interfaces:**
- Add `daemon_lock_path(settings: Settings) -> Path`.
- Add `daemon_status(settings: Settings, client_factory: ClientFactory | None = None) -> dict[str, Any]`.
- Extend `start_daemon(settings: Settings) -> dict[str, Any]` to acquire a user-scoped ownership lock and return `already_running` when another owned daemon is alive.
- `ensure_daemon(..., wait_seconds=4.0)` remains bounded and returns a health projection or raises a product-level `DaemonStartupError` containing a diagnostics path.

- [ ] **Step 1: Write failing tests**

Test that a second start with a live lock does not call `Popen`, that stale locks are reclaimed only when the recorded PID is not running, that `ensure_daemon` returns `already_running` for a healthy daemon, and that a failed readiness deadline raises `DaemonStartupError` with a stable user-facing message. Add CLI/TUI/Mil contract assertions that all launch paths call the shared readiness helper.

- [ ] **Step 2: Run focused tests and confirm red**

Run `uv run pytest tests/unit/test_service_lifecycle.py tests/unit/test_cli_terminal_commands.py -q`. The new symbols and behavior must fail before implementation.

- [ ] **Step 3: Implement the bounded guard and diagnostics**

Use an exclusive lock file under the MLLminal data root containing the owned PID and executable path. Treat a live PID as owned only when its command line resolves to the packaged `mllminald` executable. Write startup failures to `%LOCALAPPDATA%\\MLLminal\\diagnostics\\daemon-startup.log`; expose its path in `DaemonStartupError`. Keep optional dependency checks warnings only.

- [ ] **Step 4: Run focused tests and first-launch smoke checks**

Run the focused unit tests, `uv run ruff check src tests`, and `uv run mllminal doctor --json` in an isolated temporary data directory. Confirm the test command and lint command exit 0; the smoke command may return exit 3 only when no packaged daemon is present, but its JSON/error must name the bounded startup failure and diagnostics path.

- [ ] **Step 5: Commit the focused slice**

Run `git add src/mllminal/service_lifecycle.py src/mllminal/cli/terminal_commands.py src/mllminal/client/app.py src/mllminal/client/mil.py packaging/windows/install.ps1 packaging/windows/doctor.ps1 tests/unit/test_service_lifecycle.py tests/unit/test_cli_terminal_commands.py tests/unit/test_windows_packaging_contract.py && git commit -m "feat: make packaged daemon startup deterministic"`.

### Task 3: Detect repair versus update and preserve state

**Files:**
- Modify: `src/mllminal/install_lifecycle.py`
- Modify: `packaging/windows/install.ps1`
- Modify: `packaging/windows/MLLminal.iss`
- Test: `tests/unit/test_install_lifecycle.py`
- Test: `tests/integration/test_install_upgrade.py`

**Interfaces:**
- Add `InstallLifecycle.install_mode() -> Literal["fresh", "repair", "update"]` based on the manifest and installed version.
- Add `InstallLifecycle.prepare_update() -> dict[str, Any]` that stops only owned processes, creates a timestamped SQLite/WAL/SHM backup, and returns the backup manifest.
- Keep `repair()` idempotent and reject a target version lower than the manifest version with `InstallLifecycleError`.

- [ ] **Step 1: Write failing state-preservation tests**

Create a temporary SQLite database with workflow, session, profile, policy-binding, approval, settings, and learning-metadata rows plus a manifest version. Assert fresh/repair/update mode detection, backup creation before migration, downgrade rejection, and preservation of all rows after update.

- [ ] **Step 2: Run integration tests and confirm red**

Run `uv run pytest tests/unit/test_install_lifecycle.py tests/integration/test_install_upgrade.py -q`. The new mode and update contract must fail against the current install script.

- [ ] **Step 3: Implement mode detection and update orchestration**

Read the manifest before replacing files, compare semantic versions, call `prepare_update()` for existing installations, install the new wheel, rerun `repair()`, rewrite the manifest with the new version, and restart the daemon only after migrations succeed. Preserve the data root and existing shortcuts/PATH semantics.

- [ ] **Step 4: Run focused tests**

Run the two focused test modules plus `uv run pytest tests/unit/test_windows_packaging_contract.py -q`. All must pass.

- [ ] **Step 5: Commit the focused slice**

Run `git add src/mllminal/install_lifecycle.py packaging/windows/install.ps1 packaging/windows/MLLminal.iss tests/unit/test_install_lifecycle.py tests/integration/test_install_upgrade.py && git commit -m "feat: preserve state across Windows repair and update"`.

### Task 4: Finish one-click uninstall and silent-mode contracts

**Files:**
- Modify: `packaging/windows/uninstall.ps1`
- Modify: `packaging/windows/MLLminal.iss`
- Modify: `src/mllminal/install_lifecycle.py`
- Test: `tests/unit/test_windows_packaging_contract.py`
- Test: `tests/integration/test_install_upgrade.py`

**Interfaces:**
- `uninstall.ps1` accepts `-DeleteData` and `-Silent`, retains data when false, and returns stable exit codes/messages.
- `InstallLifecycle.purge(confirm: str | None)` remains the only data-deletion authority and requires exact `MLLMINAL` confirmation.

- [ ] **Step 1: Write failing uninstall tests**

Assert that the installer registers Add/Remove Programs, invokes uninstall silently with safe data retention, exposes `/VERYSILENT` and `/NORESTART`, removes all five shortcut targets and startup/PATH/browser-host registrations, and never contains a broad user-profile deletion target. Add a temporary-fixture test proving `-DeleteData` removes only `data` and `backups` leaves while preserving a sibling user-output directory.

- [ ] **Step 2: Run tests and confirm red**

Run `uv run pytest tests/unit/test_windows_packaging_contract.py tests/integration/test_install_upgrade.py -q` and verify the new silent/uninstall assertions fail against the current scripts.

- [ ] **Step 3: Implement the minimal safe uninstall flow**

Use one checkbox in the normal Inno uninstall page, default false. Use exact owned paths for shortcuts, startup, registry, PATH, app files, data, and backups. Make silent uninstall retain data by default; only an explicit `DeleteData` parameter can purge the scoped local state. Emit “application removed; local data retained” or “application and owned data removed” messages and write details to diagnostics.

- [ ] **Step 4: Run focused tests and PowerShell parse checks**

Run the focused pytest modules and parse both scripts with `[System.Management.Automation.Language.Parser]::ParseFile(...)`. Exit 0 with no parser errors.

- [ ] **Step 5: Commit the focused slice**

Run `git add packaging/windows/uninstall.ps1 packaging/windows/MLLminal.iss src/mllminal/install_lifecycle.py tests/unit/test_windows_packaging_contract.py tests/integration/test_install_upgrade.py && git commit -m "feat: make Windows uninstall silent and data-safe"`.

### Task 5: Audit package contents and record performance

**Files:**
- Modify: `packaging/windows/build-runtime.ps1`
- Modify: `packaging/windows/build-installer.ps1`
- Create: `packaging/windows/package-audit.ps1`
- Modify: `packaging/windows/README.md`
- Test: `tests/unit/test_windows_packaging_contract.py`

**Interfaces:**
- `package-audit.ps1 -DistributionDirectory <path> -RuntimeDirectory <path> -ReportPath <path>` emits JSON containing compressed setup size, runtime size, installed-file count, and measured build/install/first-launch/daemon-ready durations when supplied.
- Build scripts remove only known development-only files and never remove importable runtime packages.

- [ ] **Step 1: Write failing audit-contract tests**

Assert the audit script exists, emits the required JSON keys, the build scripts exclude caches/test files/source maps from the staged runtime, and the packaging README documents before/after measurement commands.

- [ ] **Step 2: Run the focused test and confirm red**

Run `uv run pytest tests/unit/test_windows_packaging_contract.py -q` and confirm the audit contract fails before the script exists.

- [ ] **Step 3: Implement conservative pruning and measurement**

Prune only `__pycache__`, `.pyc`, test directories, source maps, build metadata, and duplicate installer logs from the staging directory. Generate a JSON report with byte counts and elapsed measurements; leave optional provider/model artifacts untouched unless the runtime import check proves they are unused.

- [ ] **Step 4: Build and verify the package**

Run `powershell -ExecutionPolicy Bypass -File packaging/windows/build-installer.ps1 -ProjectRoot (Get-Location)` and then the audit script. Record the before/after numbers in `packaging/windows/README.md`; verify the setup output begins with `MZ` and the staged runtime still passes `mllminal --version`, `mllminal doctor`, and import smoke checks.

- [ ] **Step 5: Commit the focused slice**

Run `git add packaging/windows/build-runtime.ps1 packaging/windows/build-installer.ps1 packaging/windows/package-audit.ps1 packaging/windows/README.md tests/unit/test_windows_packaging_contract.py && git commit -m "chore: audit Windows package size and launch performance"`.

### Task 6: Add clean-machine acceptance harness and update product documentation

**Files:**
- Create: `tests/acceptance/test_windows_one_click_install.py`
- Modify: `README.md`
- Modify: `packaging/windows/README.md`
- Modify: `tests/unit/test_readme_contract.py`

**Interfaces:**
- Acceptance tests are skipped unless `MLLMINAL_WINDOWS_ACCEPTANCE=1` and require an explicit setup executable path, preventing accidental mutation of a developer machine.
- The README normal-user installation section contains only download, double-click, Install, and Start Menu steps; developer/source installation is separate.

- [ ] **Step 1: Write failing documentation and harness contracts**

Assert README normal-user instructions do not require CLI commands, mention the main/TUI/Mil shortcut behavior, document repair/update/uninstall/silent modes, and state limitations honestly. Add acceptance test names for fresh install, new-terminal PATH, shortcut launch, readiness, optional-component fallback, repair/update preservation, silent modes, and clean uninstall.

- [ ] **Step 2: Run the focused tests and confirm red**

Run `uv run pytest tests/unit/test_readme_contract.py tests/unit/test_windows_packaging_contract.py -q` and confirm the new documentation/harness assertions identify stale post-install instructions.

- [ ] **Step 3: Implement guarded acceptance tests and documentation**

Use isolated `%TEMP%` roots and explicit process snapshots; never call the real uninstaller unless the environment variable is set and the fixture path is validated. Rewrite both docs to distinguish end-user setup, developer build, troubleshooting, data retention, and optional dependency warnings.

- [ ] **Step 4: Run documentation, lint, type, and full-suite checks**

Run `uv run pytest -q`, `uv run ruff check src tests`, `uv run ruff format --check src tests`, and `uv run mypy src`. Record any clean-machine gap explicitly rather than claiming it passed locally.

- [ ] **Step 5: Commit the focused slice**

Run `git add tests/acceptance/test_windows_one_click_install.py README.md packaging/windows/README.md tests/unit/test_readme_contract.py && git commit -m "docs: document true one-click Windows installation"`.

### Task 7: Final packaging audit and delivery gates

**Files:**
- Modify: `docs/superpowers/plans/2026-07-31-true-one-click-windows-installation.md` only if execution notes need recording.

- [ ] **Step 1: Build the release executable**

Run the release build on Windows and record setup size, staged/installed size, cold install time, first-launch time, and daemon-ready time in the audit report.

- [ ] **Step 2: Run the full verification matrix**

Run `uv run pytest -q`, `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run mypy src`, PowerShell parser checks, and the guarded Windows acceptance suite. Verify each command’s exit code and save the CI run URL.

- [ ] **Step 3: Audit every objective requirement**

Check one `.exe`, no Python/Git/uv/source checkout, safe default wizard, PATH/new terminal, five shortcuts, automatic daemon/readiness, optional fallback, repair/update/reinstall, state preservation, silent modes, uninstall safety, no orphan processes, no stale PATH/startup/browser registration, package measurements, and documentation.

- [ ] **Step 4: Publish each focused branch**

For every implementation branch: inspect `git status -sb` and `git diff --check`, push with tracking, open a ready PR, wait for the full GitHub CI result, squash-merge, delete the remote feature ref, fetch `origin/main`, and delete the merged local branch before starting the next slice.

