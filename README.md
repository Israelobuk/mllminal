# MLLminal

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
