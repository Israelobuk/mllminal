# Performance Baseline

Date: 2026-07-20
Environment: Windows, Python 3.12.13, local validation worktree, disposable temporary data directories.

These are single-run baseline measurements, not capacity claims.

| Metric | Measurement | Method / qualification |
|---|---:|---|
| Daemon health latency | 84.31 ms | Actual `mllminald.exe`, local `/v1/health` request |
| Daemon idle working set | 4.25 MB | Actual daemon process immediately after startup |
| Daemon sampled CPU time | 0.031 s | Same idle sample |
| Observer idle overhead | 0.87 ms / 10,000 polls | `DeviceObserver` with zero adapters; empty-observer baseline |
| Database growth | 753,664 bytes / 1,000 messages | SQLite WAL-backed store; each message creates a persisted event |
| Event-store read | 2.45 ms for 101 events | `Store.list_events` local read |
| Workflow execution | 12.41 ms | One-step deterministic injected handler with verification |
| CLI startup | 7,721.20 ms | `mllminal.exe --help`, includes uv/Windows process startup |
| Desktop client import | 2,458.24 ms | Python import/construct path; UI was not interactively launched |
| Model worker lifecycle | N/A | No model request was made; Ollama was mocked in tests and unavailable for live acceptance |
| Vision worker lifecycle | N/A | No screenshot/OCR/CV worker exists |

The database figure includes SQLite/WAL behavior and should be repeated under representative retention policies before production sizing.