"""SQLite-backed authoritative state store."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    func,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.orm import Session as DbSession

from mllminal.contracts import (
    EventEnvelope,
    Message,
    MessageRole,
    Session,
    Task,
    TaskState,
    utc_now,
)
from mllminal.state_machine import require_transition


class Base(DeclarativeBase):
    pass


class SessionRow(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_root: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


class MessageRow(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("session_id", "idempotency_key"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    role: Mapped[str]
    content: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str]
    created_at: Mapped[datetime]


class TaskRow(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    title: Mapped[str]
    goal: Mapped[str] = mapped_column(Text)
    state: Mapped[str]
    origin_interface: Mapped[str]
    blocker: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class EventRow(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("session_id", "sequence"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    sequence: Mapped[int]
    event_type: Mapped[str]
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


class Store:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.engine = create_engine(f"sqlite:///{database_path}")

        @event.listens_for(self.engine, "connect")
        def configure_sqlite(dbapi_connection: Any, _connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        Base.metadata.create_all(self.engine)

    @contextmanager
    def transaction(self) -> Iterator[DbSession]:
        with DbSession(self.engine) as database, database.begin():
            yield database

    def create_session(self, workspace_root: str) -> Session:
        session = Session(workspace_root=workspace_root)
        with self.transaction() as database:
            database.add(SessionRow(**session.model_dump(exclude={"schema_version"})))
            self._append_event(
                database, session.id, "session.created", session.model_dump(mode="json")
            )
        return session

    def get_session(self, session_id: str) -> Session:
        with DbSession(self.engine) as database:
            row = database.get(SessionRow, session_id)
            if row is None:
                raise KeyError(session_id)
            return self._session(row)

    def add_message(
        self,
        session_id: str,
        role: MessageRole,
        content: str,
        idempotency_key: str,
    ) -> tuple[Message, bool]:
        with self.transaction() as database:
            existing = database.scalar(
                select(MessageRow).where(
                    MessageRow.session_id == session_id,
                    MessageRow.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                return self._message(existing), False
            message = Message(session_id=session_id, role=role, content=content)
            database.add(
                MessageRow(
                    **message.model_dump(exclude={"schema_version", "role"}),
                    role=message.role.value,
                    idempotency_key=idempotency_key,
                )
            )
            self._append_event(
                database, session_id, "message.created", message.model_dump(mode="json")
            )
            return message, True

    def list_messages(self, session_id: str) -> list[Message]:
        with DbSession(self.engine) as database:
            rows = database.scalars(
                select(MessageRow)
                .where(MessageRow.session_id == session_id)
                .order_by(MessageRow.created_at)
            )
            return [self._message(row) for row in rows]

    def create_task(self, session_id: str, title: str, goal: str) -> Task:
        task = Task(session_id=session_id, title=title, goal=goal)
        with self.transaction() as database:
            database.add(
                TaskRow(
                    **task.model_dump(exclude={"schema_version", "state"}), state=task.state.value
                )
            )
            self._append_event(database, session_id, "task.created", task.model_dump(mode="json"))
        return task

    def get_task(self, task_id: str) -> Task:
        with DbSession(self.engine) as database:
            row = database.get(TaskRow, task_id)
            if row is None:
                raise KeyError(task_id)
            return self._task(row)

    def list_tasks(self) -> list[Task]:
        with DbSession(self.engine) as database:
            rows = database.scalars(select(TaskRow).order_by(TaskRow.created_at.desc()))
            return [self._task(row) for row in rows]

    def transition_task(self, task_id: str, target: TaskState, blocker: str | None = None) -> Task:
        with self.transaction() as database:
            row = database.get(TaskRow, task_id)
            if row is None:
                raise KeyError(task_id)
            require_transition(TaskState(row.state), target)
            row.state = target.value
            row.blocker = blocker
            row.updated_at = utc_now()
            task = self._task(row)
            self._append_event(
                database, row.session_id, "task.transitioned", task.model_dump(mode="json")
            )
            return task

    def list_events(self, session_id: str, after_sequence: int = 0) -> list[EventEnvelope]:
        with DbSession(self.engine) as database:
            rows = database.scalars(
                select(EventRow)
                .where(EventRow.session_id == session_id, EventRow.sequence > after_sequence)
                .order_by(EventRow.sequence)
            )
            return [
                EventEnvelope(
                    session_id=row.session_id,
                    sequence=row.sequence,
                    event_type=row.event_type,
                    payload=json.loads(row.payload_json),
                    created_at=row.created_at,
                )
                for row in rows
            ]

    def _append_event(
        self, database: DbSession, session_id: str, event_type: str, payload: dict[str, Any]
    ) -> EventEnvelope:
        sequence = (
            database.scalar(
                select(func.max(EventRow.sequence)).where(EventRow.session_id == session_id)
            )
            or 0
        ) + 1
        envelope = EventEnvelope(
            session_id=session_id,
            sequence=sequence,
            event_type=event_type,
            payload=payload,
        )
        database.add(
            EventRow(
                session_id=session_id,
                sequence=sequence,
                event_type=event_type,
                payload_json=json.dumps(payload),
                created_at=envelope.created_at,
            )
        )
        return envelope

    @staticmethod
    def _session(row: SessionRow) -> Session:
        return Session(id=row.id, workspace_root=row.workspace_root, created_at=row.created_at)

    @staticmethod
    def _message(row: MessageRow) -> Message:
        return Message(
            id=row.id,
            session_id=row.session_id,
            role=MessageRole(row.role),
            content=row.content,
            created_at=row.created_at,
        )

    @staticmethod
    def _task(row: TaskRow) -> Task:
        return Task(
            id=row.id,
            session_id=row.session_id,
            title=row.title,
            goal=row.goal,
            state=TaskState(row.state),
            origin_interface=row.origin_interface,
            blocker=row.blocker,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
