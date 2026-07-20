"""Allowlist and approval gate for device actions."""

from __future__ import annotations

from typing import Any, Protocol

from mllminal.actions.contracts import ActionRequest, ActionResult


class ActionExecutor(Protocol):
    def __call__(self, request: ActionRequest) -> dict[str, Any]:
        """Perform one already-authorized bounded action."""


class BoundedActionService:
    ALLOWED_ACTIONS = frozenset(
        {
            "application.focus",
            "window.focus",
            "control.invoke",
            "filesystem.open_readonly",
        }
    )

    def __init__(self, executor: ActionExecutor | None = None) -> None:
        self.executor = executor
        self._results: dict[str, ActionResult] = {}

    def actions(self) -> list[str]:
        return sorted(self.ALLOWED_ACTIONS)

    def execute(self, request: ActionRequest, *, idempotency_key: str) -> ActionResult:
        cached = self._results.get(idempotency_key)
        if cached is not None:
            return cached
        self._validate_action(request)
        if request.preview:
            return self._remember(
                idempotency_key,
                ActionResult(
                    action=request.action,
                    application=request.application,
                    executed=False,
                    preview=True,
                    approval_required=True,
                    output={"target": request.target, "arguments": request.arguments},
                ),
            )
        if not request.workflow_authorized or not request.action_approved:
            raise PermissionError(
                "Workflow authorization and explicit action approval are required"
            )
        if self.executor is None:
            return self._remember(
                idempotency_key,
                ActionResult(
                    action=request.action,
                    application=request.application,
                    executed=False,
                    preview=False,
                    approval_required=False,
                    error="action_executor_not_configured",
                ),
            )
        output = self.executor(request)
        return self._remember(
            idempotency_key,
            ActionResult(
                action=request.action,
                application=request.application,
                executed=True,
                preview=False,
                approval_required=False,
                mutation_performed=request.action != "filesystem.open_readonly",
                output=output,
            ),
        )

    def _remember(self, key: str, result: ActionResult) -> ActionResult:
        self._results[key] = result
        return result

    def _validate_action(self, request: ActionRequest) -> None:
        if request.action not in self.ALLOWED_ACTIONS:
            raise ValueError(f"Action is not allowlisted: {request.action}")
        if request.action == "control.invoke" and not request.target:
            raise ValueError("control.invoke requires a semantic target")
        if request.action == "filesystem.open_readonly" and "path" not in request.arguments:
            raise ValueError("filesystem.open_readonly requires a path")
