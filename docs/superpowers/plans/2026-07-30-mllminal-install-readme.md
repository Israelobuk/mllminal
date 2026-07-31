# MLLminal Simple Install/Uninstall and Product README Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a self-contained per-user Windows installation lifecycle and an accurate product-quality README from the merged CLI-first baseline.

**Architecture:** Keep Inno Setup as the single setup executable. Stage a self-contained Python runtime plus wheel dependencies under the immutable app root, keep all mutable state under a separate data root, and expose lifecycle operations through the authenticated local CLI. Use Alembic-backed backup/upgrade checks for repair and upgrade, then document the resulting product surface in a separate documentation PR.

**Tech Stack:** PowerShell, Inno Setup, Python 3.12, Typer, SQLAlchemy/Alembic, SQLite, pytest, Ruff, mypy, GitHub Actions.

## Global Constraints

- Users must not need Python, uv, Git, the source repository, or manual environment variables.
- Install per user where practical and keep mutable data outside the installation directory.
- Preserve state on upgrade and back up SQLite before migrations.
- Block unsafe downgrades.
- Uninstall must stop owned MLLminal processes, remove installed components and registrations, and never delete user-created outputs outside MLLminal-owned data.
- Purge-data is separate, explicit, confirmation-protected, and path-confined.
- Every completed change is committed and pushed; each focused PR waits for CI, squash-merges, and deletes its feature branch.

---

### Task 1: Install lifecycle contract and failing tests

**Files:**
- Modify: `tests/unit/test_cli_terminal_commands.py`
- Create: `tests/unit/test_install_lifecycle.py`
- Modify: `src/mllminal/cli/terminal_commands.py`

- [ ] Add failing help/exit tests for `install status`, `install repair`, `install data-path`, and `install purge-data --confirm MLLMINAL`.
- [ ] Add failing tests that assert readable and JSON install projections expose app root, data root, runtime, PATH, daemon, and migration state.
- [ ] Add failing tests that assert purge rejects missing/incorrect confirmation and cannot delete a path outside the configured data root.
- [ ] Run `uv run pytest tests/unit/test_install_lifecycle.py tests/unit/test_cli_terminal_commands.py -q`; expected failure because the install command group is not registered.
- [ ] Implement the smallest daemon-independent install command group using an injected lifecycle service.
- [ ] Rerun the focused tests and preserve existing command compatibility.
- [ ] Run `uv run ruff check src tests` and `uv run mypy src`.

### Task 2: Runtime staging and database repair service

**Files:**
- Create: `src/mllminal/install_lifecycle.py`
- Create: `tests/unit/test_install_lifecycle.py` additions
- Modify: `src/mllminal/migrations/__init__.py`

- [ ] Add failing tests for runtime discovery, install metadata, SQLite backup including `-wal`/`-shm` sidecars, migration repair, and downgrade rejection.
- [ ] Run the focused tests to verify the new lifecycle behavior is absent.
- [ ] Implement `InstallLifecycle` with typed status/repair/purge results, validated app/data roots, timestamped database backups, Alembic head checks, and idempotent repair.
- [ ] Make repair call the existing migration entry point and record a small install manifest under the owned data root.
- [ ] Preserve database contents across repair and leave the backup when migration fails.
- [ ] Rerun focused tests, Ruff, formatting, and mypy.

### Task 3: Installer, PATH, shortcuts, startup, and uninstall

**Files:**
- Modify: `packaging/windows/install.ps1`
- Modify: `packaging/windows/uninstall.ps1`
- Modify: `packaging/windows/MLLminal.iss`
- Create: `packaging/windows/build-runtime.ps1`
- Modify: `packaging/windows/README.md`
- Modify: `tests/unit/test_windows_packaging_contract.py`

- [ ] Add failing contract assertions for runtime staging, per-user PATH marker, Mil/TUI/daemon shortcuts, repair invocation, startup cleanup, browser-host cleanup, and data retention.
- [ ] Run the packaging contract tests to verify those assertions fail against the current scripts.
- [ ] Add a release staging script that creates or validates a Python 3.12 runtime, installs the wheel and locked dependencies offline into the runtime, and fails with a clear message when staging is incomplete.
- [ ] Update Inno Setup to include the staged runtime and entry points, run install/repair after file copy, create Mil/TUI shortcuts, and pass app/data roots explicitly.
- [ ] Update install PowerShell to add one marked user PATH entry safely, initialize data, back up and migrate the database, detect existing installs, and support repair/reinstall without overwriting data.
- [ ] Update uninstall PowerShell and Inno code to stop only owned processes, remove PATH/startup/shortcuts/browser-host registration, retain data by default, and purge only when explicitly selected.
- [ ] Run PowerShell parser checks, focused packaging tests, and a temporary-directory script simulation.

### Task 4: Packaged acceptance and upgrade preservation

**Files:**
- Create: `tests/integration/test_install_upgrade.py`
- Modify: `src/mllminal/acceptance/service.py`
- Modify: `packaging/windows/README.md`

- [ ] Add failing integration coverage that seeds workflows, execution history, checkpoints, profiles, policy bindings, valid approvals, Mil sessions, settings, and learning metadata.
- [ ] Add failing coverage for repair/upgrade preserving all seeded state, creating a database backup, and refusing a lower migration target.
- [ ] Add failing coverage for uninstall retaining data, purge removing only the owned data root, and leaving an external output untouched.
- [ ] Implement the acceptance checks and honest limitation messages without claiming clean-machine or code-signing support.
- [ ] Run the integration acceptance tests and full local suite.

### Task 5: Product README and stale documentation cleanup

**Files:**
- Modify: `README.md`
- Modify: `docs/productization/windows-product-acceptance.md`
- Modify: `docs/productization/cli-tui-client.md`
- Modify: related stale docs identified by `rg -n -i "Office automation|Tauri|React|installation requires|active policy.*unimplemented" docs README.md`
- Create: `tests/unit/test_readme_contract.py`

- [ ] Add failing README contract tests for the product statement, Mil, approved observation, typed capabilities, approval/verification/recovery, local-first boundaries, implemented/optional/experimental/deferred/unsupported status, architecture flow, every required technology purpose, install/upgrade/uninstall/troubleshooting, CLI examples, Mermaid architecture, and technical-preview limitations.
- [ ] Run the README contract tests to verify the current internal foundation README is incomplete.
- [ ] Rewrite the root README as an approachable product page with a separate developer installation section and realistic commands.
- [ ] Update related docs to remove stale desktop/frontend and Office-centric framing while preserving deeper engineering details in `/docs`.
- [ ] Rerun README contract tests, stale-claim searches, Ruff, formatting, mypy, and the full suite.

### Task 6: Publish focused PRs and final audit

**Files:**
- No new product files; use Git history and CI evidence.

- [ ] Review each branch diff for scope and run `git diff --check`.
- [ ] Commit and push the installer lifecycle branch; open its focused PR into `main`.
- [ ] Wait for all required CI checks, squash-merge, delete remote and local branch.
- [ ] Start the upgrade/acceptance branch from refreshed `origin/main`, repeat validation and merge.
- [ ] Start the README/docs branch from refreshed `origin/main`, repeat validation and merge.
- [ ] Run a final requirement-by-requirement audit against the user brief and verify merged `origin/main`, full suite, Ruff, formatting, mypy, and Windows CI before marking the goal complete.