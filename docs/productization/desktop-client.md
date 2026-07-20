# Connected desktop client

## What is real

The shipped mllminal-ui surface is a thin Textual client. It uses the authenticated daemon REST API and the /v1/events WebSocket, so task state, workflow state, approvals, observation state, privacy state, permissions, and verification remain daemon-owned. CLI-created work is refreshed into the client, and client actions use the same daemon commands.

## Simulated, unsupported, and boundaries

CI uses injected API and event clients; it does not prove a live Windows desktop session or synchronization during daemon restart. The client does not own execution, observation, model inference, vision inference, learning, approvals, or database state. A native Tauri/React shell is not claimed in this release. The daemon token is local, never displayed in the client log, and all consequential actions remain server-authorized. No desktop telemetry or screenshots are uploaded to an MLLminal service.

## Manual test procedure

1. Start the daemon and mllminal-ui on a clean Windows account.
2. Confirm connected, unavailable, starting, authentication-failed, paused, emergency-stop, awaiting-approval, executing, verification-failed, and worker-unavailable states.
3. Start a demonstration from the CLI and confirm it appears in the client.
4. Start one from the client and confirm mllminal tasks and mllminal task show expose the same task.
5. Preview, approve, and verify a bounded filesystem action; confirm both surfaces show the same result.
6. Stop the daemon and confirm the client cannot execute while disconnected.

## Automated coverage and next work

Remote CI covers Python importability, lint, formatting, typing, and existing daemon/client contracts. Live synchronization remains manual-required. Native shell packaging and clean-session evidence are next work.
