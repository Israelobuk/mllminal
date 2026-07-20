# Real-world Windows product acceptance

Milestone 11 adds the acceptance state machine, readiness classification, and Windows runbook. It records evidence but never marks a clean-machine acceptance as passed automatically.

Companion evidence documents:

- acceptance-results.md: current certification state and evidence ledger
- security-model.md: enforced and manual security boundaries
- performance-baseline.md: required raw measurements
- desktop-client.md: live synchronization acceptance
- packaging.md: clean install and uninstall acceptance

Run scripts/windows/run-product-acceptance.ps1 on a clean Windows environment and record each stage through mllminal acceptance record or the authenticated acceptance API.

## Required scenario

1. Enable observation explicitly.
2. Demonstrate the weekly report routine with semantic actions and a non-sensitive test workbook.
3. Stop and review the inactive candidate.
4. Compile three demonstrations into one draft workflow.
5. Label source file, reporting date, stable destination folder, and draft recipient.
6. Preview the typed workflow and review permission, approval, rollback, and verification manifests.
7. Approve explicitly.
8. Find, rename, move, and independently verify the workbook through the filesystem adapter.
9. Open read-only in Excel, export PDF, verify non-empty output, and close without saving.
10. Create an Outlook draft, set recipient/subject/body, attach the approved PDF, and verify it remains unsent.
11. Confirm desktop and CLI show matching task, progress, and verification state.
12. Review the draft and record the final stage.

There is no automatic email send capability.

## Security, performance, and current status

The report distinguishes implemented controls from manual-required clean-machine checks and includes readiness classification. Exercise all security cases in security-model.md and record all metrics in performance-baseline.md. This repository currently has no clean-machine passing acceptance record. Do not label the product complete until the workflow runs against real Windows applications without fixture substitution.
