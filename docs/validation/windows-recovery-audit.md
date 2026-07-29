# Windows recovery audit

## Scope

This audit is the final repository-level baseline for the cross-application workflow
milestone. It covers durable execution, restart recovery, transitions, provider fallback,
verification, idempotency, typed rollback, authenticated clients, and the four bounded
acceptance workflows documented in docs/productization/cross-application-recovery.md.

It does not claim a clean-desktop certification for Microsoft Excel, classic Outlook, or a
particular browser account. Those provider-specific checks require the corresponding
application and a user-approved non-sensitive fixture on the target Windows machine.

## Evidence from the merged baseline

- PRs #84 through #94 are squash-merged into main.
- The local Windows validation run completed with 242 passed, 4 warnings.
- Ruff format check, Ruff lint, and mypy src/mllminal passed.
- The required GitHub Actions Windows job passed on PR #94, including its full pytest step.
- The four warnings are existing dependency/Pydantic serializer warnings; they do not
  indicate a workflow failure.

The acceptance record remains honest: provider-neutral behavior is covered, while the
machine-specific Excel/Outlook and clean-session performance evidence stays deferred until
those applications are available and manually reviewed.

## Clean Windows procedure

Run from a fresh checkout with Python 3.12 and the locked environment:

    uv sync --all-groups --locked
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy src
    uv run pytest

Then, on a disposable approved workspace containing only non-sensitive fixtures:

1. Start the daemon and authenticate the CLI/desktop client.
2. Confirm emergency stop is inactive, then verify the observer can start, pause, resume,
   and stop without leaving worker threads or callbacks alive.
3. Run the filesystem-to-spreadsheet and file-intake workflows in preview, approve their
   mutations, and verify destination state.
4. Restart the daemon after a deliberately interrupted run. Compare execution, attempts,
   checkpoints, and event history before resuming.
5. Force one bounded provider failure. Confirm retry limits, stable effect idempotency, and
   no duplicate destination or draft.
6. Propose and approve a typed rollback plan. Confirm rollback state and independent
   verification are persisted.
7. If Excel or Outlook is installed, run the document/PDF and report/email-draft flows and
   retain provider availability, output verification, and visible unsent-draft evidence.
8. Exercise emergency stop, permission denial, stale approval, path traversal, symlink or
   junction escape, forged verification, and unauthorized-client checks.
9. Record evidence paths with mllminal acceptance record; do not include file contents,
   credentials, secure text, screenshots, tokens, or raw OCR.

## Exit criteria

The repository baseline is complete when the local and remote suites pass. Product
acceptance is complete only after a user reviews the clean-machine evidence, confirms every
consequential action, verifies the final draft is unsent, and records the final
user_reviewed acceptance stage. CI and fixture adapters cannot set that stage.