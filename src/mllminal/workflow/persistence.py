"""SQLite rows for workflow definitions, runs, events, and idempotency."""

from datetime import datetime

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from mllminal.persistence import Base


class WorkflowDefinitionRow(Base):
    __tablename__ = "workflow_definitions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str]
    version: Mapped[int] = mapped_column(Integer)
    state: Mapped[str]
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


class WorkflowRunRow(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String, index=True)
    state: Mapped[str]
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class WorkflowRunEventRow(Base):
    __tablename__ = "workflow_run_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    event_type: Mapped[str]
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


class WorkflowIdempotencyRow(Base):
    __tablename__ = "workflow_idempotency"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    operation: Mapped[str]
    result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


class WorkflowExecutionRow(Base):
    __tablename__ = "workflow_executions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String, index=True)
    state: Mapped[str]
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class WorkflowStepAttemptRow(Base):
    __tablename__ = "workflow_step_attempts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    execution_id: Mapped[str] = mapped_column(String, index=True)
    step_id: Mapped[str] = mapped_column(String, index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    state: Mapped[str]
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


class WorkflowCheckpointRow(Base):
    __tablename__ = "workflow_checkpoints"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    execution_id: Mapped[str] = mapped_column(String, index=True)
    step_id: Mapped[str] = mapped_column(String, index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]
