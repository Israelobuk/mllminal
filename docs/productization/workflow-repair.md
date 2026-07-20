# Workflow repair and recovery

Milestone 8 adds explicit, durable repair proposals for failed workflow runs. A failure is preserved with bounded diagnostics, classified into a typed failure class, and paused for review. The repair service never blindly retries coordinate clicks or mutates a workflow during diagnosis.

## Failure and repair flow

`POST /v1/workflow-repair/propose` or `mllminal workflow repair-propose` records a proposal containing the failed run, source workflow version, failure class, diagnostics, typed changes, preview workflow, and explanation. Supported classes include target-not-found, application-unavailable, permission-denied, input-missing, state-mismatch, verification-failed, file-collision, timeout, user-cancelled, emergency-stopped, and adapter-crashed.

A caller must provide an explicit replacement capability when one is proposed. Approval through `/v1/workflow-repair/{proposal_id}/approve` or `mllminal workflow repair-approve` creates a new draft workflow version with a new ID, incremented version, parent workflow reference, updated permissions, and retained prior version. Rejection leaves the original workflow unchanged.

## Acceptance

Change File Explorer or Excel state so a saved target becomes invalid. Confirm the workflow fails safely without duplicate effects, the run state and diagnostics persist, a typed repair proposal explains the issue, the preview shows the changed capability, and approval creates a new version while the previous version remains available for rollback/history.
