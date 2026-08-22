# MLLminal Zero-Friction Terminal Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `mllminal` the canonical local terminal agent while keeping daemon ownership, safety, approvals, verification, and existing advanced commands intact.

**Architecture:** A small `RuntimeBootstrap` coordinates workspace normalization and the existing daemon lifecycle. The CLI uses that bootstrap for the root Mil session, one-shot prompts, workspace mode, and daemon-backed common commands; the daemon remains the only state owner. Lifecycle lock metadata is validated before recovery, and normal failures are reduced to product-level diagnostics.

**Tech Stack:** Python 3.12, Typer, asyncio, httpx, pytest, pytest-asyncio, Ruff, mypy, existing packaged Windows daemon launcher.

**Spec:** `C:/Users/isobu/.codex/attachments/d6a062b7-38d9-48cd-9c82-ff972c46958a/pasted-text.txt`

## Global Constraints

- `mllminal` is the normal interactive entry point; `mil` and `chat` remain compatibility aliases.
- One-shot prompts and workspace paths use the same authenticated daemon/Mil path as interactive mode.
- A healthy daemon is reused; stale state is repaired only after ownership and process identity checks.
- Startup waits for the health endpoint, uses bounded retries, and never opens a visible background window.
- Normal output contains no internal ports, paths, tracebacks, or daemon command lines; `--verbose`/`MLLMINAL_LOG_LEVEL=DEBUG` is the diagnostic path.
- Existing workflow, learning, policy, privacy, approval, verification, and provider behavior is not changed.
- Every logical commit is pushed before moving to the next logical change.

### Task 1: Baseline and lifecycle recovery

**Files:**
- Create: `docs/superpowers/plans/2026-08-22-zero-friction-terminal.md`
- Modify: `src/mllminal/service_lifecycle.py`
- Test: `tests/unit/test_service_lifecycle.py`

Deliver the stale-lock fix first. Add lock creation metadata (`status`, owner/daemon PID, executable identity, creation timestamp, and process-start identity where available), validate a live lock before reuse, remove only verified stale state, and retry startup once when recovery is safe. Add tests for executable-mismatch stale locks, active-lock protection, PID reuse/identity mismatch, and bounded readiness behavior.

Verification: `uv run pytest tests/unit/test_service_lifecycle.py -q`, then `uv run ruff check src/mllminal/service_lifecycle.py tests/unit/test_service_lifecycle.py`.

### Task 2: Shared runtime bootstrap and invocation modes

**Files:**
- Create: `src/mllminal/runtime_bootstrap.py`
- Modify: `src/mllminal/cli/terminal_commands.py`, `src/mllminal/client/mil.py`
- Test: `tests/unit/test_runtime_bootstrap.py`, `tests/unit/test_cli_terminal_commands.py`, `tests/unit/test_client_mil.py`

Define a typed bootstrap result containing normalized workspace and readiness information. It must validate existing directories, use the current directory when no workspace is supplied, call `ensure_daemon`, and convert unrecoverable startup failures into the concise doctor guidance. Route root interactive mode, `mllminal "..."`, `mllminal .`, `mil`, `chat`, and service-dependent common commands through one bootstrap path. Add a one-shot Mil function that submits exactly one prompt through the existing streaming/approval/verification flow and returns cleanly.

Verification: run the focused bootstrap, Mil, and CLI tests and inspect captured stdout/stderr for absence of internal startup details.

### Task 3: Terminal UX, help, doctor, and compatibility

**Files:**
- Modify: `src/mllminal/cli/terminal_commands.py`, `src/mllminal/service_lifecycle.py`
- Test: `tests/unit/test_cli_terminal_commands.py`, `tests/unit/test_service_lifecycle.py`

Make root help lead with Start, Common commands, Safety and approvals, and Advanced. Print the concise version/workspace/ready banner only for root interactive and one-shot launches. Preserve existing command names and `--json` behavior. Add `doctor --repair` for safe stale-state repair, a debug switch/environment interpretation, graceful Ctrl-C/EOF handling, and concise startup failure output while retaining diagnostics on disk.

Verification: run CLI help/version/root/one-shot/workspace/doctor tests and the relevant Ruff/mypy checks.

### Task 4: Documentation and installed-command acceptance

**Files:**
- Modify: `README.md`, `packaging/windows/README.md` and only related public docs that contain stale invocation guidance
- Test: `tests/acceptance/test_windows_one_click_install.py` or a focused new headless acceptance test if the existing fixture supports it

Rewrite the quick start around `mllminal`, distinguish user installation from developer `uv` commands, document one-shot/workspace modes, aliases, approvals, stop/doctor, and the client-versus-daemon shutdown rule. Add an installed invocation check from a normal directory without a source checkout where the existing package harness permits it; do not launch GUI surfaces during agent validation.

Verification: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`, `uv run mllminal --version`, and `uv run mllminal help`.

### Task 5: GitHub delivery and final verification

After each logical implementation task, stage only its files, commit with a focused message, and push `Israelobuk/feat/zero-friction-terminal`. After the final full validation, open a PR titled `Make MLLminal a one-command terminal agent`, wait for required CI, push any fixes as additional commits, squash-merge, delete the remote and local feature branch, fetch `origin/main`, and run a final headless smoke check from the merged tree.
