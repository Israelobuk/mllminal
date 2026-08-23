# MLLminal Interactive Terminal UX Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `mllminal` into a responsive, discoverable, terminal-native Mil session while preserving authenticated daemon ownership, approval gates, durable task state, verification, privacy, and headless CLI behavior.

**Architecture:** Keep `client/mil.py` as a compatibility boundary and move presentation/orchestration into `client/interactive/`. A renderer produces deterministic plain/ANSI output; a command registry owns slash-command discovery; prompt-toolkit is used only when an interactive TTY is available for history and completion; non-TTY input remains simple and script-safe. Live status, tasks, workflows, applications, approvals, and session data are read through existing authenticated daemon routes.

**Tech Stack:** Python 3.11+, prompt-toolkit for terminal input/history/completion, existing httpx/daemon client, existing provider contracts, pytest fixtures, Ruff, mypy, and the current Windows packaging/runtime bootstrap.

**Spec:** Attached milestone “MLLminal Interactive Terminal UX Upgrade”; the screenshot is a visual reference only and is not a source of branding, commands, or proprietary behavior.

## Global Constraints

- Never expose chain-of-thought, internal ports, PIDs, database paths, tokens, or raw tracebacks in normal interactive output.
- Preserve existing approval, permission, verification, emergency-stop, privacy, bounded-action, durable-task, workflow, packaging, one-shot, and headless JSON behavior.
- Never fabricate recent activity, mentions, context percentages, model availability, capability availability, or execution progress.
- Keep mutable state outside the install directory and keep prompt history local/privacy-aware.
- No GUI windows or visible daemon consoles are part of this change; all validation uses headless commands/tests.
- Every logical implementation change is committed and pushed before moving to the next stage.

## Tasks

- [ ] **Task 1: establish the interactive module contracts and deterministic fixtures**
  - **Files:** `src/mllminal/client/interactive/__init__.py`, `commands.py`, `renderer.py`, `session.py`, `completion.py`, `history.py`, and focused unit tests.
  - Add immutable command metadata, grouped help, prefix filtering, a terminal renderer with width-aware wide/medium/narrow layouts, status symbols, NO_COLOR handling, and injectable I/O seams.
  - Add failing tests for command discovery/filtering, startup rendering, narrow/wide output, no-color output, and deterministic recent-activity/quick-start behavior; run those focused tests to record the red state.
  - Implement the smallest contracts that satisfy the tests and preserve plain text output when no TTY is present; run the focused tests to green.
  - Commit and push: `feat(cli): add interactive terminal presentation layer`.

- [ ] **Task 2: add prompt completion, mentions, path safety, and privacy-aware history**
  - **Files:** `src/mllminal/client/interactive/completion.py`, `history.py`, `session.py`, `pyproject.toml`, `uv.lock`, and tests.
  - Add prompt-toolkit only if needed for reliable TTY completion/history. Implement slash completion, `@` resources from real daemon/workspace records, workspace-confined file/folder completion, multiline `/begin`/`/end`, prompt history, and non-TTY fallback.
  - Add failing tests for slash filtering, keyboard-completion data, valid/invalid mentions, path traversal rejection, history retention, multiline collection, and non-TTY behavior; run focused tests.
  - Implement and rerun focused tests; keep sensitive content out of UI personalization/history beyond existing policy.
  - Commit and push: `feat(cli): add terminal completion and local history`.

- [ ] **Task 3: integrate the session shell and product commands**
  - **Files:** `src/mllminal/client/interactive/session.py`, `commands.py`, `renderer.py`, `src/mllminal/client/mil.py`, `src/mllminal/cli/terminal_commands.py`, and tests.
  - Implement startup onboarding/tips, `/help`, `/status`, `/workspace`, `/model`, `/apps`, `/workflows`, `/approvals`, `/tasks`, `/task <id>`, `/history`, `/context`, `/clear`, `/compact`, `/doctor`, `/stop`, `/exit`, Ctrl+C cancellation semantics, and clean EOF exit using current daemon APIs.
  - Show durable recent tasks/workflow activity only when available. Keep `/clear` visible-only/session-reset behavior distinct from durable deletion. Make `/compact` honest about the existing bounded context and preserve durable objectives/state. Keep `/stop` conservative and never silently trigger emergency stop.
  - Add failing tests for command projections, startup onboarding once, recent activity, clear/compact, status/model/workspace/apps/workflows/tasks, friendly errors, Ctrl+C, and clean exit; run focused tests.
  - Implement through the modular layer, preserving `_submit`, `run_mil_prompt`, and current approval polling compatibility; rerun focused tests.
  - Commit and push: `feat(cli): upgrade Mil to an interactive terminal session`.

- [ ] **Task 4: improve provider-visible progress and safe Qwen validation feedback**
  - **Files:** `src/mllminal/agent/prompts/system_v1.py`, `planner_v1.py`, `schemas.py`, `src/mllminal/agent/provider.py`, `src/mllminal/client/mil.py`, and provider tests.
  - Include the actual supplied tool registry, permission boundary, and exact JSON envelope/schema in the Qwen prompt. Add a safe `response.started` progress event before buffered validation and structured provider-failure presentation without exposing hidden reasoning.
  - Add tests proving the prompt contains only supplied tools, the schema/JSON-only instruction, progress occurs before completion, and invalid output yields an actionable safe error after the bounded repair attempt.
  - Implement and rerun provider/client focused tests. Do not weaken validation or claim streamed model text when it cannot be validated incrementally.
  - Commit and push: `fix(agent): make local model progress and validation failures visible`.

- [ ] **Task 5: preserve public CLI/headless behavior and documentation**
  - **Files:** `README.md` only if required for user-facing terminal commands, `docs/` relevant terminal docs, and CLI tests.
  - Keep `mllminal --version`, `mllminal help`, `mllminal status --json`, one-shot mode, installed-CLI behavior, and JSON output free of decorative UI. Document interactive commands and `/begin`/`/end` multiline behavior without stale claims.
  - Add/adjust deterministic tests for headless JSON and one-shot compatibility; run the focused CLI suite.
  - Commit and push: `docs(cli): document the interactive Mil terminal`.

- [ ] **Task 6: full validation and acceptance audit**
  - Run focused interactive/provider tests, then `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`, `uv run mllminal --version`, and `uv run mllminal help`.
  - Run installed-CLI/headless smoke checks from a normal PowerShell directory without opening any GUI or daemon window. Verify narrow/wide/plain output through deterministic renderer fixtures, no-color output, OneDrive paths, Unicode, second launch, and clean `/exit`.
  - Fix failures in focused commits, push each fix, and record any environment-only limitation explicitly.

- [ ] **Task 7: PR, CI, merge, cleanup, and final verification**
  - Open PR titled `Upgrade Mil to an interactive terminal agent`, wait for all CI checks, fix failures through pushed commits, squash-merge only after green CI, delete local/remote feature branches, update local main from origin, confirm the merge commit on `origin/main`, and verify a clean worktree.
  - Run the final CLI smoke commands against the merged main and report exact validation evidence.

---

## Self-review checklist

- [ ] All attached requirements are either implemented or explicitly called out as unavailable without fabricating behavior.
- [ ] Interactive presentation remains modular and does not move safety authority into the client.
- [ ] TTY and non-TTY behavior are deterministic, and JSON output stays machine-readable.
- [ ] Qwen failures explain what happened without exposing private reasoning or weakening validation.
- [ ] Every completed file change was committed and pushed.
- [ ] CI was green before squash merge and both branches were removed afterward.
