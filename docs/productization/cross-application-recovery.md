# Cross-application workflow recovery

The cross-application runtime is a durable, approval-governed execution boundary. A
workflow definition names typed inputs, explicit dependencies, application surfaces,
provider candidates, transitions, retry policy, bindings, and independent verification.
The runtime persists the definition, run, step attempts, checkpoints, transitions, and
rollback plan so a daemon or client restart does not turn an interrupted action into an
implicit duplicate.

## Operating sequence

1. Create and activate a workflow definition. Activation is required before a live run.
2. Preview the workflow and inspect its inputs, permissions, provider candidates,
   transitions, approval points, and verification requirements.
3. Start the live run. Consequential steps and cross-application transitions pause for
   explicit approval.
4. Inspect execution state, attempts, and checkpoints while the run is active or paused.
5. Resume only the recoverable run after a daemon or client restart. Verified resumable
   checkpoints are restored; completed effects retain their stable idempotency key.
6. If the run cannot safely continue, propose a typed rollback plan, approve it, execute
   it, and retain the resulting provenance.

The CLI surfaces are:

    mllminal workflow preview <workflow-id> --inputs JSON
    mllminal workflow run <workflow-id> --live --inputs JSON
    mllminal workflow approve <run-id> --approved true
    mllminal workflow execution <run-id>
    mllminal workflow attempts <run-id>
    mllminal workflow checkpoints <run-id>
    mllminal workflow resume <run-id>
    mllminal workflow rollback-plan <run-id>
    mllminal workflow rollback-approve <plan-id> --approved true
    mllminal workflow rollback-execute <plan-id>

The authenticated daemon exposes the equivalent REST resources under
/v1/workflow-runs/{run_id} and a replayable WebSocket at
/v1/workflow-runs/{run_id}/events/stream. The desktop client is a thin authenticated
view of the same state; it does not own execution or approval state.

## Acceptance workflows

The repository includes provider-neutral acceptance definitions and bounded tests for:

- local filesystem to spreadsheet: copy an approved workbook, cross into the spreadsheet
  surface, inspect metadata, and verify the destination;
- document to PDF: inspect an approved source, export through a selected document provider,
  and independently verify the PDF output;
- report to email draft: verify the report, create and populate an email draft, attach the
  report, and stop at a verified draft=true, sent=false state;
- file intake organization: find the latest approved intake file, move it to an approved
  destination, and verify source absence and destination state.

These workflows deliberately do not declare email.send, read credentials, submit forms,
make purchases, or invoke an unrestricted shell. Native Excel, Outlook, document, and
browser providers remain optional and must report their own availability and verification
strength. Fixture adapters prove contract and recovery behavior; they do not replace clean
Windows acceptance with the real applications.

## Recovery and failure handling

| Condition | Required behavior |
| --- | --- |
| provider unavailable | select an eligible fallback or fail with a typed explanation |
| transient provider error | retry only the declared bounded retryable errors |
| duplicate request | return the durable idempotent result without repeating the effect |
| daemon/client restart | restore only verified, resumable checkpoints |
| application transition unavailable | fail before the next application step executes |
| verification failure | keep the run failed/recoverable; never infer success |
| rollback requested | require a typed plan and explicit approval before execution |
| emergency stop or permission loss | block execution immediately and preserve provenance |

Learning and advisory ranking may explain or order eligible providers, but neither may add
an ineligible capability, bypass approval, auto-promote a policy, or retrain during a run.