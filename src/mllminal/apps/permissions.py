"""Durable per-application capability grants."""

from datetime import datetime

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from mllminal.persistence import Base


class ApplicationGrantRow(Base):
    __tablename__ = "application_grants"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    application: Mapped[str]
    scope: Mapped[str]
    granted: Mapped[bool] = mapped_column(Boolean)
    updated_at: Mapped[datetime]


class ApplicationBridgeIdempotencyRow(Base):
    __tablename__ = "application_bridge_idempotency"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    operation: Mapped[str]
    result_json: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime]
