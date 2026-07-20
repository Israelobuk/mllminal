"""SQLite rows for the deterministic activity projection."""

from datetime import datetime

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from mllminal.persistence import Base


class ActivitySegmentRow(Base):
    __tablename__ = "activity_segments"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


class ApplicationSessionRow(Base):
    __tablename__ = "application_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


class TaskSessionRow(Base):
    __tablename__ = "task_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


class ContextSwitchRow(Base):
    __tablename__ = "activity_context_switches"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


class TaskBoundaryRow(Base):
    __tablename__ = "task_boundaries"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


class ActivitySummaryRow(Base):
    __tablename__ = "activity_summaries"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


class ActivityIdempotencyRow(Base):
    __tablename__ = "activity_idempotency"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    operation: Mapped[str]
    result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]
