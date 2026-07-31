# Connected CLI and TUI client

MLLminal is a CLI-first product. The `mllminal` commands and `mllminal-ui` Textual terminal client are thin authenticated clients of the local daemon. The daemon owns sessions, messages, workflows, executions, approvals, observation, privacy, permissions, verification, learning, and persistence.

## Terminal responsibilities

The CLI provides stable inspection and control commands for daemon status, Mil conversations, applications, capabilities, workflows, executions, approvals, policies, diagnostics, service lifecycle, and emergency stop. Non-interactive projections support readable output and `--json`; consequential actions remain daemon-authorized and idempotent.

The Textual client provides keyboard-first pages for Mil chat, system status, workflows, executions, approvals, applications, capabilities, active policies, diagnostics, settings, and the event log. It refreshes daemon snapshots and consumes the authenticated event stream. It shows stale/reconnecting state and never treats a disconnected client as permission to execute.

## Boundaries

The CLI and TUI do not own execution, observation, model inference, vision inference, learning, approvals, or database state. They do not expose arbitrary PowerShell, CMD, subprocess, Python, SQL, SQLite, model-artifact, credential, or online-learning controls. All consequential actions route through typed CLI commands or authenticated daemon contracts.

## Acceptance

On a clean Windows shell, start `mllminald`, run `mllminal doctor`, `mllminal readiness`, and `mllminal status --json`, then launch `mllminal-ui`. Confirm Mil sessions survive reconnect, workflow proposals remain reviewable, approvals are explicit, progress and verification are daemon-backed, application/capability discovery is bounded, policy status is visible, and emergency stop blocks new actions.

The installer packages the daemon, CLI, Textual client, and required runtime files only. It does not package Tauri, React, Node.js, or frontend build artifacts.