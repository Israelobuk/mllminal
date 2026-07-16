# MLLminal Foundation Implementation Plan

> **For agentic workers:** Implement each checkbox test-first and push every completed checkpoint to `origin/Israelobuk/mllminal-foundation`.

**Goal:** Deliver a durable local daemon and synchronized terminal clients with typed approvals and verified read-only project inspection.

**Architecture:** A modular Python package exposes `mllminald` and `mllminal`. SQLite stores all authoritative state; FastAPI REST mutates and reads state while WebSocket events provide ordered replay.

**Tech Stack:** Python 3.12, uv, Pydantic 2, SQLAlchemy 2, Alembic, FastAPI, Typer, Textual, pytest, Ruff, mypy.

## Checklist

- [ ] Define and test versioned contracts, state transitions, configuration, and error envelopes.
- [ ] Define and test SQLite models, migrations, idempotency, and durable event ordering.
- [ ] Define and test deterministic Mil plans, typed read-only tools, approvals, and verifiers.
- [ ] Define and test authenticated REST, WebSocket replay, and daemon lifecycle behavior.
- [ ] Define and test Typer commands, Textual interactions, reconnect behavior, and deferred commands.
- [ ] Run the complete release gate and verify both local and remote branch state.

