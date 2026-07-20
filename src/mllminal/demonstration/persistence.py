"""SQLite rows for workflow demonstrations and inactive draft candidates."""

import json
from datetime import datetime

from sqlalchemy import Boolean, Integer, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import Session as DbSession

from mllminal.persistence import Base


class DemonstrationSessionRow(Base):
    __tablename__ = "demonstration_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    label: Mapped[str]
    state: Mapped[str]
    timeout_seconds: Mapped[int] = mapped_column(Integer)
    emergency_stop_shortcut: Mapped[str]
    started_at: Mapped[datetime]
    updated_at: Mapped[datetime]
    expires_at: Mapped[datetime]
    step_count: Mapped[int] = mapped_column(Integer)
    candidate_id: Mapped[str | None] = mapped_column(String, nullable=True)


class DemonstrationStepRow(Base):
    __tablename__ = "demonstration_steps"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    payload_json: Mapped[str] = mapped_column(Text)


class DemonstrationVariableRow(Base):
    __tablename__ = "demonstration_variables"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    event_id: Mapped[str]
    label: Mapped[str]
    field_name: Mapped[str | None] = mapped_column(String, nullable=True)


class WorkflowCandidateRow(Base):
    __tablename__ = "workflow_candidates"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str]
    status: Mapped[str]
    activated: Mapped[bool] = mapped_column(Boolean)
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


class DemonstrationIdempotencyRow(Base):
    __tablename__ = "demonstration_idempotency"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    operation: Mapped[str]
    result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


def load_steps(database: DbSession, session_id: str) -> list[DemonstrationStepRow]:
    return list(
        database.scalars(
            select(DemonstrationStepRow)
            .where(DemonstrationStepRow.session_id == session_id)
            .order_by(DemonstrationStepRow.sequence)
        )
    )


def load_variables(database: DbSession, session_id: str) -> list[DemonstrationVariableRow]:
    return list(
        database.scalars(
            select(DemonstrationVariableRow)
            .where(DemonstrationVariableRow.session_id == session_id)
            .order_by(DemonstrationVariableRow.id)
        )
    )


def parse_json(value: str) -> object:
    return json.loads(value)
