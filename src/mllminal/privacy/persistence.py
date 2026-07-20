"""SQLite rows owned by the privacy boundary."""

import json
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Integer, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import Session as DbSession

from mllminal.persistence import Base


class PrivacyStateRow(Base):
    __tablename__ = "privacy_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_json: Mapped[str] = mapped_column(Text)
    consent_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    incognito_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    emergency_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime]


class PrivacyRuleRow(Base):
    __tablename__ = "privacy_rules"

    rule_id: Mapped[str] = mapped_column(String, primary_key=True)
    rule_type: Mapped[str]
    pattern: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime]


class PrivacyHistoryRow(Base):
    __tablename__ = "privacy_history"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    event_category: Mapped[str]
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision: Mapped[str]
    rule_id: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str]
    timestamp: Mapped[datetime]
    adapter: Mapped[str]


class PrivacyEventRow(Base):
    __tablename__ = "privacy_events"

    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str]
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


class PrivacyIdempotencyRow(Base):
    __tablename__ = "privacy_idempotency"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    operation: Mapped[str]
    result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


def row_json(value: dict[str, Any] | None) -> str | None:
    return json.dumps(value) if value is not None else None


def load_json(value: str | None) -> dict[str, Any] | None:
    return json.loads(value) if value is not None else None


def get_state(database: DbSession) -> PrivacyStateRow:
    row = database.get(PrivacyStateRow, 1)
    if row is None:
        raise RuntimeError("Privacy state has not been initialized")
    return row


def list_rules(database: DbSession) -> list[PrivacyRuleRow]:
    return list(database.scalars(select(PrivacyRuleRow).order_by(PrivacyRuleRow.created_at)))
