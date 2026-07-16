# MLLminal Foundation Design

MLLminal's first milestone is a Windows-first, portable Python foundation. One FastAPI daemon owns Mil's deterministic provider, sessions, tasks, approvals, read-only tools, verification results, and ordered events. Typer and Textual clients use authenticated REST plus a replayable WebSocket stream; no interface owns separate state.

SQLite is authoritative and migratable. A single daemon binds to loopback, authenticates with a per-user token, confines tools to an attached workspace, persists events before publishing them, and never marks a task complete without successful verification. The initial provider is deterministic and the tool surface is deliberately limited to listing files, reading text, and inspecting project metadata.

Python 3.12, strict Pydantic models, SQLAlchemy 2, Alembic, FastAPI, Typer, Textual, Ruff, mypy, and pytest form the slice. Qwen, desktop/Tauri, unrestricted commands, learning, DuckDB/Parquet, PyTorch, BentoML, and MLflow are deferred.

