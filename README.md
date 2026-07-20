# MLLminal

## Windows device observer

The Windows-first observer records structured local metadata only: application/process lifecycle, foreground/window transitions, redacted window-title classifications, UI Automation control metadata, safe semantic mouse/keyboard events, filesystem operation types, and idle/active state. On Windows it uses native pywin32/UI Automation/hooks when available; unavailable capabilities degrade without stopping the daemon. Start or control it with `mllminal device start`, `stop`, `pause`, `resume`, `status`, and `events`.

MLLminal never captures typed characters, passwords, clipboard contents, screen pixels, browser-page content, microphone audio, or camera input. Window titles are classified and redacted before persistence; secure UI Automation fields suppress keyboard metadata. Observation has no execution authority. Observer events are stored locally under the configured data directory in `device/device-events.jsonl` and replayed through `/v1/device/events/stream` after WebSocket authentication.


MLLminal is a local-first, terminal-first AI execution environment powered by Mil.

This repository is currently implementing the Windows-first foundation slice: a shared local daemon, synchronized terminal clients, durable tasks and sessions, typed approvals, and verified read-only project inspection.


## Local Qwen provider

MLLminal uses a local Ollama-compatible server by default. Install and start Ollama separately, then install a compatible Qwen instruct model:

```powershell
ollama serve
ollama pull qwen3:4b
mllminal models use qwen
mllminal models status
mllminal models test
```

The default endpoint is `http://127.0.0.1:11434`; the model, endpoint, timeout, temperature, and context limit are persisted in `%LOCALAPPDATA%\MLLminal\mil-provider.json`. The configuration contains no authentication material.

Use `mllminal models` to view the configured provider, `mllminal models provider` to print its name, and `mllminal models use deterministic` for offline deterministic fixture mode. Deterministic mode is intended for tests and reproducible fixtures; it is not a language model and never impersonates Qwen.

### Troubleshooting

- **Server unavailable:** start `ollama serve`, then run `mllminal models test` again.
- **Model missing:** run `ollama pull qwen3:4b` (or the model configured in `mil-provider.json`).
- **Timeout or insufficient memory:** choose a smaller locally installed Qwen model, increase `request_timeout_seconds`, or switch temporarily with `mllminal models use deterministic`.
- **Malformed provider response:** Mil records a typed failure after one constrained repair attempt; the daemon and saved sessions remain available.
- **Provider logs:** daemon logs contain provider/model/status diagnostics but do not include full prompts, bearer tokens, or hidden reasoning.


## Local learning candidates

Learning uses only durable, privacy-preserving replay entries. It trains CPU-only candidate action policies offline; raw prompts, provider messages, tool arguments, and tool outputs are never used as training data.

```powershell
mllminal learning status
mllminal learning train
```

Training requires the configured minimum number of eligible experiences (100 by default). Each run snapshots its replay-entry IDs, writes a SHA-256 verified checkpoint under the local learning data directory, and registers a `CANDIDATE` policy. Candidates are never promoted automatically: evaluation and an explicit operator promotion remain required.

Authenticated daemon clients can inspect `/v1/learning/status`, `/v1/learning/runs`, and `/v1/learning/policies`; `/v1/learning/events` replays durable learning events after WebSocket authentication.


### Runtime advisory behavior

When learning is enabled, the daemon loads the currently promoted checkpoint at startup and may record a masked policy recommendation at an approved planning checkpoint. Recommendations are advisory only: Mil continues to require the existing permissions, approval, tool schema, workspace confinement, task-state, and verification gates. The final runtime action remains the deterministic approval path.

MLLminal safely falls back to its deterministic policy behavior when learning is disabled, no trained policy is promoted, a checkpoint is missing or fails its digest/compatibility validation, confidence is too low, or all learned actions are masked. Only verified terminal outcomes are eligible for replay; incomplete and unverified work is excluded.

