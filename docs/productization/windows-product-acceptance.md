# Real-world Windows product acceptance

Milestone 11 adds the final acceptance state machine and Windows runbook. The code records scenario evidence but never marks a clean-machine acceptance as passed automatically. Run `scripts/windows/run-product-acceptance.ps1` on a clean Windows environment and record each stage through `mllminal acceptance record` or the authenticated acceptance API.

## Required scenario

1. Enable observation explicitly.
2. Demonstrate the weekly report routine with semantic actions and a non-sensitive test workbook.
3. Stop and review the inactive candidate.
4. Compile three demonstrations into one draft workflow.
5. Label source file, reporting date, stable destination folder, and draft recipient.
6. Preview the typed workflow and review permission, approval, rollback, and verification manifests.
7. Approve the run explicitly.
8. Use the filesystem adapter to find the workbook, rename it, move it, and independently verify destination existence/source absence.
9. Use the Excel adapter to open read-only, export PDF, verify a non-empty PDF, and close without saving.
10. Use the Outlook adapter to create a draft, set recipient/subject/body, attach the approved PDF, and verify the draft remains unsent.
11. Confirm desktop and CLI show matching task/progress/verification state.
12. Review the draft and record the final stage.

There is no automatic email send capability.

## Security and performance

The acceptance report distinguishes implemented controls from manual-required clean-machine checks. Exercise secure-input suppression, malicious workflow/path/junction/symlink inputs, permission bypass, unauthorized replay, forged verification, emergency-stop bypass, stale approval reuse, duplicate execution after restart, application spoofing, malicious OCR/prompt injection, adapter crash, corrupted state, and unauthorized desktop access.

Record idle CPU/memory, observation overhead, event persistence throughput, event-stream latency, CLI/desktop startup, workflow preview, filesystem action, Excel export, and OCR latency. Keep raw measurements with the acceptance evidence; this repository does not claim those real-Windows measurements have been run from CI.

`mllminal acceptance report` reports the current scenario, implemented security boundaries, manual-required security checks, performance measurements, and the invariant that automatic email sending is disabled.
