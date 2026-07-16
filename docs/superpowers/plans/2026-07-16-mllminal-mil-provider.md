# MLLminal Mil Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a configurable, streamed, validation-gated local Qwen provider without weakening typed approvals or verified execution.

**Architecture:** An async provider protocol and a dedicated Ollama transport emit typed provider events. The runtime turns persisted session state into bounded context, validates the final response envelope before saving plans/approvals, and persists provider metadata and emitted events before WebSocket publication.

**Tech Stack:** Python 3.12, Pydantic 2, httpx async streaming, SQLAlchemy 2, Alembic, FastAPI, Typer, Textual, pytest, Ruff, mypy.

## Global Constraints

- Default interactive provider is `qwen`; deterministic remains a first-class fixture/CI provider.
- Only registered read-only tools can be proposed; all tool executions require approval.
- Never persist chain-of-thought, secrets, raw prompts, or authentication material.
- Allow one structured-output repair only; invalid repair produces no plan or approval.
- Do not add deferred learning, training, desktop, browser, shell, arbitrary URL, or write-tool capabilities.

---

### Task 1: Typed provider contracts, prompts, and response validation

**Files:**
- Create: `src/mllminal/agent/prompts/__init__.py`, `system_v1.py`, `planner_v1.py`, `repair_v1.py`, `schemas.py`
- Modify: `src/mllminal/contracts.py`, `src/mllminal/agent/provider.py`, `src/mllminal/tools.py`
- Test: `tests/unit/test_provider.py`, `tests/unit/test_contracts.py`

**Interfaces:**
- Produces `MilRequest`, `MilProviderEvent`, `ProviderMetadata`, `MilProvider.stream_response(request)`, `StructuredResponse`, and `validate_plan_envelope(...)`.
- Consumes registry `ToolDefinition` and `PermissionGrant`; emits only validated `Plan` values.

- [ ] **Step 1: Write failing contract tests** for async deterministic streaming, unknown-tool rejection, invalid arguments, path traversal, execution-claim rejection, prompt version, and bounded trimming.
- [ ] **Step 2: Run `uv run pytest tests/unit/test_provider.py tests/unit/test_contracts.py -v`** and confirm failures identify missing async contracts and validator behavior.
- [ ] **Step 3: Implement strict Pydantic schemas and versioned prompt builders.** Use an envelope shaped as `{response: str, plan: {title: str, steps: [{step_id, description, tool: {name, arguments}}]}}`; reject `extra` fields and transform validated entries into registry-derived `ToolProposal` values only.
- [ ] **Step 4: Implement async deterministic fixture events** in the order `response.started`, `response.delta`, `response.completed`, `plan.proposed`; remove the old synchronous `plan()` protocol.
- [ ] **Step 5: Re-run the focused tests, then commit** `feat: add provider-neutral Mil model contracts`.

### Task 2: Dedicated Ollama streaming client and Qwen provider

**Files:**
- Create: `src/mllminal/agent/ollama.py`
- Modify: `src/mllminal/agent/provider.py`, `src/mllminal/config.py`
- Test: `tests/unit/test_ollama.py`, `tests/unit/test_config.py`

**Interfaces:**
- Produces `OllamaClient.stream_chat(messages)` and `OllamaProviderError(category, retryable)`.
- `QwenMilProvider` consumes `Settings` and emits the Task 1 provider events.

- [ ] **Step 1: Write failing ASGI-transport tests** for JSON-lines deltas, malformed JSON, 404 model missing, unavailable transport, timeout, cancellation, and redacted errors.
- [ ] **Step 2: Run `uv run pytest tests/unit/test_ollama.py tests/unit/test_config.py -v`** and confirm each fails for the absent transport/configuration.
- [ ] **Step 3: Add `MilSettings`** with `provider`, `model`, `base_url`, `temperature`, `max_context_tokens`, and `request_timeout_seconds`; keep configuration persisted under the data directory and validate `deterministic|qwen`.
- [ ] **Step 4: Implement `OllamaClient`** using `httpx.AsyncClient.stream`, `/api/chat`, connect/read/write/pool timeouts, `aiter_lines`, structured error classification, `aclose`, and logs containing only provider/model/duration/status/tokens/retries/error category.
- [ ] **Step 5: Implement `QwenMilProvider`** to stream visible deltas while buffering the structured envelope, make one repair request with validation messages, and yield `provider.failed` after a second failure.
- [ ] **Step 6: Re-run focused tests and commit** `feat: add local Qwen streaming client`.

### Task 3: Durable provider events and metadata

**Files:**
- Create: `src/mllminal/migrations/versions/0002_mil_provider.py`
- Modify: `src/mllminal/runtime_store.py`, `src/mllminal/persistence.py`, `src/mllminal/contracts.py`
- Test: `tests/unit/test_persistence.py`, `tests/unit/test_migrations.py`

**Interfaces:**
- Produces `RuntimeStore.save_provider_metadata`, `list_provider_metadata`, and `append_provider_event`.
- Provider metadata fields are provider, model, prompt version, response id, timestamps, completion, validation, retry count, failure category, and token counts.

- [ ] **Step 1: Write failing persistence/migration tests** proving provider metadata and streamed events survive a fresh store instance and omit raw prompts/secrets.
- [ ] **Step 2: Run `uv run pytest tests/unit/test_persistence.py tests/unit/test_migrations.py -v`** and confirm failures.
- [ ] **Step 3: Add models/store methods and Alembic revision** with transactional metadata/event insertion and compact JSON payloads.
- [ ] **Step 4: Re-run focused tests and commit** `feat: persist Mil provider metadata and events`.

### Task 4: Async runtime, bounded context, validated plans, and approvals

**Files:**
- Modify: `src/mllminal/agent/runtime.py`, `src/mllminal/agent/provider.py`, `src/mllminal/runtime_store.py`, `src/mllminal/tools.py`
- Test: `tests/integration/test_runtime.py`, `tests/unit/test_provider.py`

**Interfaces:**
- `MilRuntime.submit` becomes `async`, persists/publishes-ready provider events, returns a pending task only after a valid plan and approvals exist.
- `MilRuntime` accepts an injected provider and exposes persisted events for the API publisher.

- [ ] **Step 1: Write failing tests** for context ordering/trimming, one repair, no plan after repair failure, approval per step, zero execution before approval, and summaries sourced only from verified results.
- [ ] **Step 2: Run `uv run pytest tests/integration/test_runtime.py tests/unit/test_provider.py -v`** and confirm failures.
- [ ] **Step 3: Build request context from only current-session data:** latest messages, task, pending approvals, registry definitions, grants, and successful verified current-task results; persist a trim notice without message contents.
- [ ] **Step 4: Consume provider events in order, persist them before returning/publishing, save the completed visible message and validated plan only after successful validation, and make approvals for every proposal.**
- [ ] **Step 5: Preserve existing `decide` execution/verification semantics, then re-run focused tests and commit** `feat: validate structured Mil plans`.

### Task 5: Daemon integration, provider selection, and model CLI

**Files:**
- Create: `src/mllminal/cli/__init__.py`, `src/mllminal/cli/main.py`, `src/mllminal/cli/tui.py`
- Modify: `src/mllminal/daemon/api.py`, `src/mllminal/daemon/main.py`, `src/mllminal/config.py`, `src/mllminal/agent/__init__.py`
- Test: `tests/integration/test_api.py`, `tests/unit/test_cli.py`, `tests/unit/test_tui.py`

**Interfaces:**
- Daemon status returns provider/model/availability/endpoint/streaming without secrets.
- CLI exposes `models`, `models status`, `models provider`, `models use deterministic`, `models use qwen`, and `models test`.

- [ ] **Step 1: Write failing API/CLI tests** for Qwen default, status when unavailable, safe persisted selection/restart, no silent fallback, streamed client events/replay, and provider labels.
- [ ] **Step 2: Run `uv run pytest tests/integration/test_api.py tests/unit/test_cli.py tests/unit/test_tui.py -v`** and confirm failures.
- [ ] **Step 3: Inject the selected provider into the daemon runtime; await submit; convert/publish persisted provider events; preserve health and saved sessions on provider failure.**
- [ ] **Step 4: Implement Typer commands and incremental event consumer.** Store only selected model configuration in the local config file and display Qwen Local or Deterministic fixture.
- [ ] **Step 5: Re-run focused tests and commit** `feat: integrate Qwen provider with daemon` and `feat: add model management commands`.

### Task 6: End-to-end fake-server coverage and documentation

**Files:**
- Modify: `tests/integration/test_api.py`, `tests/integration/test_runtime.py`, `README.md`
- Create: `tests/integration/test_qwen_provider.py`

**Interfaces:**
- Fake Ollama server returns scripted JSON-line chunks through the actual `OllamaClient` transport.

- [ ] **Step 1: Write failing integration tests** for valid streaming plans, repair success/failure, unavailable/missing model/timeout/cancellation, two synchronized clients, reconnect replay, provider switching/restart, approval gating, and verified-only summary.
- [ ] **Step 2: Run `uv run pytest tests/integration -v`** and confirm failures identify missing coverage/behavior.
- [ ] **Step 3: Add only the production seams needed to make the actual fake-server flows pass; do not introduce test-only provider behavior.**
- [ ] **Step 4: Document Ollama-compatible setup, `%LOCALAPPDATA%\\MLLminal` configuration, model commands, deterministic mode, and troubleshooting for unavailable/missing/timeout/memory/logs.**
- [ ] **Step 5: Run `uv run pytest tests/integration -v`, then commit** `test: cover local provider and recovery flows` and `docs: document local Mil provider setup`.

### Task 7: Release verification and delivery

**Files:**
- Verify: all changed files and repository release commands

- [ ] **Step 1: Run** `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`, and `uv run pytest`.
- [ ] **Step 2: Run the existing foundation subprocess acceptance test** (identified from the resulting test tree) and capture its complete output.
- [ ] **Step 3: Inspect `git diff --check`, `git status --short`, migration compatibility, and the requirement checklist against the implementation prompt.**
- [ ] **Step 4: Commit any final validation/docs fixes, push every checkpoint to `origin/Israelobuk/mllminal-mil-provider`, and open a draft PR into `main`.**
