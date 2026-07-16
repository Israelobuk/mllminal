"""`mllminald` process entry point."""

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

import portalocker
import uvicorn

from mllminal.config import Settings
from mllminal.daemon.api import create_app
from mllminal.daemon.auth import load_or_create_token
from mllminal.migrations import upgrade_database
from mllminal.runtime_store import RuntimeStore


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info is not None:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(settings: Settings) -> None:
    handler = logging.FileHandler(settings.log_path, encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def main() -> None:
    settings = Settings()
    settings.ensure_data_dir()
    configure_logging(settings)
    with portalocker.Lock(settings.lock_path, mode="a", timeout=0):
        settings.pid_path.write_text(
            json.dumps({"pid": os.getpid(), "host": settings.host, "port": settings.port}),
            encoding="utf-8",
        )
        try:
            upgrade_database(settings.database_path)
            store = RuntimeStore(settings.database_path)
            token = load_or_create_token(settings.token_path)
            app = create_app(settings, store, token)
            server = uvicorn.Server(
                uvicorn.Config(app, host=settings.host, port=settings.port, log_config=None)
            )
            app.state.shutdown_callback = lambda: setattr(server, "should_exit", True)
            server.run()
        finally:
            settings.pid_path.unlink(missing_ok=True)
