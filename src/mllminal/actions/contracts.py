"""Contracts for safe, user-approved device actions."""

from typing import Any, Literal

from pydantic import Field, field_validator

from mllminal.contracts import Contract


class ActionRequest(Contract):
    action: str = Field(min_length=1, max_length=96)
    application: str = Field(min_length=1, max_length=128)
    target: str | None = Field(default=None, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)
    preview: bool = True
    workflow_authorized: bool = False
    action_approved: bool = False

    @field_validator("arguments")
    @classmethod
    def reject_sensitive_arguments(cls, value: dict[str, Any]) -> dict[str, Any]:
        forbidden = {"password", "secret", "token", "cookie", "credential", "keystroke"}
        if forbidden & {str(key).casefold() for key in value}:
            raise ValueError("credential or keystroke arguments are not supported")
        return value


class ActionResult(Contract):
    action: str
    application: str
    executed: bool
    preview: bool
    approval_required: bool
    mutation_performed: bool = False
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    local_only: Literal[True] = True
