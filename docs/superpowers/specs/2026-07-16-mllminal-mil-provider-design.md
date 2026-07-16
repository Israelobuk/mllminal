# MLLminal Mil Provider Design

## Goal

Replace the default interactive deterministic response path with a configurable local Qwen provider while preserving deterministic fixtures, typed read-only tools, approval-gated execution, durable replay, and the foundation daemon API.

## Architecture

`MilProvider` becomes an asynchronous protocol accepting a typed `MilRequest` and yielding typed provider events. `DeterministicMilProvider` implements the same protocol for CI and fixtures. `QwenMilProvider` builds versioned prompt messages and delegates HTTP transport only to a dedicated async `OllamaClient`; neither provider can access persistence or execute tools.

The runtime owns orchestration. It loads bounded, session-scoped context (recent messages, attached workspace, current task, approvals, registered tools, grants, and verified results), persists every generated event and concise provider metadata before it publishes anything, and validates a complete Pydantic response envelope before it saves a plan or creates one approval per proposed tool. Invalid output gets one constrained repair request; a second invalid response creates a typed provider failure and no plan. Tool execution and completion remain exclusively in the existing approval and verification path.

## Components

- `agent/prompts/`: explicit v1 system, planner, repair prompt builders and strict response-envelope schemas. Prompt text prohibits execution claims, fabricated results, hidden instruction disclosure, unregistered tools, path escapes, and permission changes.
- `agent/provider.py`: request/event contracts, deterministic fixture provider, Qwen provider, provider errors, output-to-plan validation, and deterministic context trimming.
- `agent/ollama.py`: cancellable `httpx.AsyncClient` transport for `/api/chat`, JSON-lines streaming, status classification, response-token accounting, and redacted diagnostics.
- `config.py`: persisted local model settings (`qwen` default, model, endpoint, temperature, context limit, timeout) plus safe provider selection.
- `runtime_store.py` and migration `0002_mil_provider.py`: provider-response metadata (provider, model, prompt version, timing, status, validation, retries, failure class, token usage) and persisted provider event envelopes. No hidden reasoning or raw prompts are stored.
- `agent/runtime.py` and `daemon/api.py`: async submission and event persistence/publishing, provider health in daemon status, typed unavailable errors, replay-compatible response/plan events, and no execution before approval.
- `cli/`: Typer `models`, `models status`, `models provider`, `models use`, and `models test`, plus incremental event rendering and the current provider label. These modules are added because the verified foundation merge does not yet contain the untracked CLI files from the separate local checkout.

## Data Flow

1. A user message creates a task in `PLANNING` and a typed request from persisted state.
2. The selected provider emits `response.started` and deltas; the runtime persists each event then publishes it to WebSocket subscribers.
3. The provider buffers the JSON response envelope, validates tools, argument schemas, workspace paths, and grants, and performs at most one repair.
4. On valid output, the runtime saves the user-visible message, provider metadata, plan, and approvals, then transitions the task to `WAITING_FOR_APPROVAL`.
5. Approval continues to invoke only the registered runtime tool path. Later model summaries receive only verified stored results and cannot claim execution otherwise.

## Failure and Safety Behavior

Unavailable servers, missing models, non-success HTTP responses, malformed JSON, timeout, and cancellation become typed provider failures. They do not stop daemon health or access to saved sessions, and Qwen is never silently replaced with the deterministic provider. Context excludes tokens, daemon metadata, unrelated sessions, arbitrary workspace files, configuration secrets, and full audit logs. Validation rejects unknown tools, invalid arguments, path traversal, unsupported actions, execution-success assertions, and invented results.

## Testing and Documentation

Unit tests cover configuration, selection, prompts, trimming, parsing, validation, repair limits, status classification, and redaction. A fake Ollama-compatible ASGI server covers streamed responses, repairs, timeouts, unavailable/missing models, cancellation, persisted/replayed synchronized events, provider switching/restart, approval gating, and verified summaries. README documents local server installation, `%LOCALAPPDATA%\\MLLminal` configuration, model commands, deterministic fixtures, and troubleshooting.

## Scope Boundaries

This slice adds no training, learning, DuckDB/Parquet, MLflow, BentoML, Tauri, browser automation, arbitrary shell or URL access, autonomous execution, or write-capable tools.
