"""Bounded SQLite cache for context-free Mil responses."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from sqlalchemy import Float, Integer, String, Text, create_engine, delete, event, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import Session as DbSession

from mllminal.persistence import Base


class ResponseCacheRow(Base):
    __tablename__ = "mil_response_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    response: Mapped[str] = mapped_column(Text)
    created_at: Mapped[float] = mapped_column(Float)
    expires_at: Mapped[float] = mapped_column(Float, index=True)
    last_accessed_at: Mapped[float] = mapped_column(Float, index=True)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)


def response_cache_key(*, provider: str, model: str, workspace_root: str, content: str) -> str:
    """Build a stable, non-reversible key for a context-free local reply."""
    payload = json.dumps(
        {
            "content": content.strip(),
            "model": model,
            "provider": provider,
            "workspace_root": workspace_root,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


class ResponseCache:
    """Best-effort durable cache that never becomes a runtime dependency."""

    def __init__(
        self,
        database_path: Path,
        *,
        ttl_seconds: int = 300,
        max_entries: int = 128,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self.database_path = database_path
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._clock = clock or (lambda: datetime.now(UTC))
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{database_path}")

        @event.listens_for(self.engine, "connect")
        def configure_sqlite(dbapi_connection: object, _connection_record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

        ResponseCacheRow.__table__.create(self.engine, checkfirst=True)

    def get(self, key: str) -> str | None:
        """Return a fresh response and update its LRU timestamp."""
        timestamp = self._clock().timestamp()
        try:
            with DbSession(self.engine) as database, database.begin():
                row = database.get(ResponseCacheRow, key)
                if row is None:
                    return None
                if row.expires_at <= timestamp:
                    database.delete(row)
                    return None
                row.last_accessed_at = timestamp
                row.hit_count += 1
                return row.response
        except (OSError, SQLAlchemyError):
            return None

    def put(self, key: str, response: str) -> None:
        """Store one response and prune expired/least-recently-used rows."""
        if not response.strip():
            return
        timestamp = self._clock().timestamp()
        try:
            with DbSession(self.engine) as database, database.begin():
                database.execute(
                    delete(ResponseCacheRow).where(ResponseCacheRow.expires_at <= timestamp)
                )
                row = database.get(ResponseCacheRow, key)
                if row is None:
                    database.add(
                        ResponseCacheRow(
                            key=key,
                            response=response,
                            created_at=timestamp,
                            expires_at=timestamp + self.ttl_seconds,
                            last_accessed_at=timestamp,
                            hit_count=0,
                        )
                    )
                else:
                    row.response = response
                    row.created_at = timestamp
                    row.expires_at = timestamp + self.ttl_seconds
                    row.last_accessed_at = timestamp
                    row.hit_count = 0
                count = database.scalar(select(func.count()).select_from(ResponseCacheRow)) or 0
                if count > self.max_entries:
                    rows = database.scalars(
                        select(ResponseCacheRow)
                        .order_by(
                            ResponseCacheRow.last_accessed_at,
                            ResponseCacheRow.hit_count,
                            ResponseCacheRow.created_at,
                            ResponseCacheRow.key,
                        )
                        .limit(count - self.max_entries)
                    )
                    for candidate in rows:
                        database.delete(candidate)
        except (OSError, SQLAlchemyError):
            return
