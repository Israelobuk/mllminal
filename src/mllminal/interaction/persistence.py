"""SQLite rows for semantic interaction capture and replay permission."""

import json
from datetime import datetime

from sqlalchemy import Boolean, Integer, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import Session as DbSession

from mllminal.persistence import Base


class InteractionStateRow(Base):
    __tablename__ = "interaction_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    replay_authorized: Mapped[bool] = mapped_column(Boolean)
    updated_at: Mapped[datetime]


class InteractionEventRow(Base):
    __tablename__ = "interaction_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str]
    payload_json: Mapped[str] = mapped_column(Text)
    replayable: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime]


class InteractionIdempotencyRow(Base):
    __tablename__ = "interaction_idempotency"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    operation: Mapped[str]
    result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


def load_event_rows(database: DbSession) -> list[InteractionEventRow]:
    return list(database.scalars(select(InteractionEventRow).order_by(InteractionEventRow.created_at)))


def serialize(value: object) -> str:
    return json.dumps(value)
