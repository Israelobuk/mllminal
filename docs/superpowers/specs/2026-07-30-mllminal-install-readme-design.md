# MLLminal Simple Install and Product README Design

## Goal

Make the Windows CLI-first product installable and removable without a developer environment, then document the product accurately for users and contributors.

## Decisions

- Keep Inno Setup as the single normal Windows setup executable. It already matches the requested per-user setup experience and avoids introducing a second installer technology.
- Use separate roots: immutable installed files under `%LOCALAPPDATA%\MLLminal\app`, mutable MLLminal-owned state under `%LOCALAPPDATA%\MLLminal\data`, and upgrade backups under `%LOCALAPPDATA%\MLLminal\backups`.
- Stage a self-contained Python runtime with the wheel and its dependencies inside the installer. The installed CLI, daemon, TUI, and Mil entry points are the runtime's scripts; users never need Python, uv, Git, or the source checkout.
- Make `mllminal install` a bounded local lifecycle command group. It can inspect installation state, repair the runtime/data contract, report the data path, and purge only the owned data root after explicit confirmation.
- Run database backup and Alembic migration validation before any upgrade mutation. If the installed migration set would move backward, stop without changing the database.
- Keep the daemon on-demand: service start/stop/restart/status are explicit, and Mil/TUI ensure the daemon is reachable before use. Startup-at-login remains opt-in.
- Remove PATH entries, shortcuts, startup registration, browser-host registration owned by MLLminal, and only the installed app root during uninstall. Data remains unless the user explicitly chooses deletion.

## Data flow

```text
Setup.exe
  -> per-user app/runtime + entry points
  -> install control: directories, PATH, shortcuts, migrations
  -> optional login startup

mllminal install repair
  -> validate app/runtime
  -> backup SQLite
  -> reject unsafe downgrade
  -> run Alembic upgrade to head
  -> preserve workflows, history, policies, approvals, sessions, and settings

Mil / TUI
  -> ensure authenticated local daemon
  -> daemon owns runtime state and action authority

Uninstall
  -> stop owned processes
  -> remove shortcuts/PATH/startup/browser registration
  -> remove app/runtime
  -> retain or explicitly purge only MLLminal-owned data
```

## Error and safety behavior

- Lifecycle commands use readable output, `--json` projections where applicable, and stable nonzero exit codes for missing installation, unavailable daemon, invalid confirmation, migration failure, and unsafe downgrade.
- Repair is idempotent and preserves existing data. Every database migration attempt first copies the SQLite database and SQLite sidecars to a timestamped backup.
- Purge requires an explicit `--confirm` token in noninteractive mode and an interactive confirmation otherwise. It refuses paths outside the expected MLLminal data root.
- Uninstall process matching is restricted to `mllminald`, `mllminal`, and `mllminal-ui` owned by the installation; user outputs outside the data root are never traversed.
- The README distinguishes implemented, optional, experimental, deferred, and unsupported behavior and does not claim clean-machine certification, code signing, universal application support, or Office verification without evidence.

## Validation

The installer slice will have unit tests for lifecycle projections, path safety, backup/downgrade checks, purge confirmation, and PowerShell/Inno contracts; integration tests will exercise a temporary app/data layout and migration-preserving repair. The README slice will have content-contract tests for product statement, architecture, technology purposes, safety boundaries, installation, commands, and honest limitations. Full pytest, Ruff, formatting, mypy, and Windows CI remain release gates.