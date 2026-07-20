# Connected desktop client

Milestone 9 upgrades `mllminal-ui` into a thin connected local client. The current desktop surface is Textual so it can ship with the existing Python package; it uses the same authenticated daemon REST and WebSocket contracts as the CLI. The client owns no database, workflow execution, model inference, observation, vision, learning, or approval state.

## Connected responsibilities

The client shows daemon connection states, shared task and workflow counts, pending approvals, verification failures, observation/privacy state, permissions, and latest visual verification metadata. It can chat with Mil, start a demonstration, pause observation, trigger emergency stop, and display a command-oriented embedded terminal panel. `/v1/events` is consumed for live task progress and the client refreshes snapshots from the daemon, so CLI-created tasks appear in the desktop and desktop-created tasks remain visible through `mllminal tasks`, `mllminal task show`, and `mllminal events`.

Supported desktop states include daemon unavailable/starting, connected, authentication failed, observation paused, emergency stop active, workflow awaiting approval, action executing, verification failed, and worker unavailable. Any consequential action remains governed by the daemon's existing approval and permission checks.

## Acceptance

Start the daemon, run `mllminal-ui`, authenticate through the local token, send a Mil message, start a demonstration, review its candidate, preview and approve a workflow, and watch task/progress/verification updates. Confirm the same task is visible through the CLI and that the desktop remains unusable for execution when the daemon is unavailable or authentication fails.

A native Tauri/React shell can later wrap this same client contract; the current shipped surface keeps packaging and runtime dependencies local to MLLminal.
