"""Provider-neutral Mil contracts and deterministic fixture provider."""

import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from mllminal.agent.ollama import OllamaProviderError
from mllminal.agent.prompts import conversation_message, repair_message, system_message
from mllminal.agent.prompts.planner_v1 import planner_message
from mllminal.agent.prompts.schemas import RESPONSE_ENVELOPE_SCHEMA
from mllminal.contracts import Message, PermissionGrant, Plan, PlanStep, ToolProposal
from mllminal.tools import ToolDefinition, ToolRegistry


class MilRequest(BaseModel):
    """The bounded, typed state a provider may use to propose work."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str
    task_id: str | None
    user_message: str
    workspace_root: str | None = None
    conversation: list[Message] = Field(default_factory=list)
    available_tools: list[ToolDefinition] = Field(default_factory=list)
    permissions: list[PermissionGrant] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    runtime_context: dict[str, Any] = Field(default_factory=dict)


class MilProviderEvent(BaseModel):
    """One provider-owned event; it cannot perform persistence or execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_type: str
    text: str | None = None
    plan: Plan | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class MilProvider(Protocol):
    def stream_response(self, request: MilRequest) -> AsyncIterator[MilProviderEvent]: ...

    def stream_conversation(self, request: MilRequest) -> AsyncIterator[MilProviderEvent]: ...


@dataclass(frozen=True)
class ValidatedResponse:
    response: str
    plan: Plan


class _StructuredTool(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    arguments: dict[str, Any]


class _StructuredStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    step_id: str
    description: str
    tool: _StructuredTool


class _StructuredPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    title: str
    steps: list[_StructuredStep] = Field(min_length=1)


class _StructuredEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    response: str
    plan: _StructuredPlan


_EXECUTION_CLAIM = re.compile(
    r"\b(?:i|we)\s+(?:have\s+)?(?:ran|executed|inspected|read|found|completed)\b", re.IGNORECASE
)


def build_bounded_context(messages: list[Message], max_messages: int) -> tuple[list[Message], bool]:
    """Keep the newest persisted messages deterministically."""
    if max_messages < 1:
        raise ValueError("max_messages must be positive")
    trimmed = len(messages) > max_messages
    return messages[-max_messages:], trimmed


def validate_plan_envelope(
    envelope: object,
    task_id: str,
    workspace: Path,
    registry: ToolRegistry,
    permissions: set[str],
) -> ValidatedResponse:
    """Treat model output as untrusted and derive proposals from the registry."""
    try:
        parsed = _StructuredEnvelope.model_validate(envelope)
    except ValidationError as error:
        raise ValueError(f"invalid structured response: {error}") from error
    if _EXECUTION_CLAIM.search(parsed.response):
        raise ValueError("response contains an unverified execution claim")

    steps: list[PlanStep] = []
    for position, step in enumerate(parsed.plan.steps, start=1):
        definition = registry.definitions.get(step.tool.name)
        if definition is None:
            raise ValueError(f"unknown tool: {step.tool.name}")
        if definition.required_permission not in permissions:
            raise ValueError(f"permission not granted: {definition.required_permission}")
        arguments = _validate_arguments(step.tool.name, step.tool.arguments, workspace)
        steps.append(
            PlanStep(
                position=position,
                title=step.description,
                proposal=ToolProposal(
                    tool_name=definition.name,
                    arguments=arguments,
                    risk=definition.risk,
                    required_permission=definition.required_permission,
                    reversible=definition.reversible,
                    verifier=definition.verifier,
                ),
            )
        )
    return ValidatedResponse(response=parsed.response, plan=Plan(task_id=task_id, steps=steps))


def _validate_arguments(name: str, arguments: dict[str, Any], workspace: Path) -> dict[str, Any]:
    if name == "project.inspect_metadata":
        if arguments:
            raise ValueError("project.inspect_metadata does not accept arguments")
        return {}
    path = arguments.get("path")
    if not isinstance(path, str) or set(arguments) != {"path"}:
        raise ValueError(f"invalid arguments for {name}")
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("path escapes attached workspace")
    if name == "project.list_files":
        return {"path": path}
    if name == "project.read_text":
        return {"path": path}
    raise ValueError(f"unknown tool: {name}")


class DeterministicMilProvider:
    """Reproducible provider used in tests and offline fixture mode."""

    async def stream_response(self, request: MilRequest) -> AsyncIterator[MilProviderEvent]:
        if request.task_id is None:
            yield MilProviderEvent(
                event_type="provider.failed", text="A task is required for planning."
            )
            return
        registry = ToolRegistry()
        available = {tool.name for tool in request.available_tools}
        if "project.inspect_metadata" not in available:
            yield MilProviderEvent(
                event_type="provider.failed", text="Inspection tool is unavailable."
            )
            return
        envelope = {
            "response": "I can inspect the attached project metadata after your approval.",
            "plan": {
                "title": "Inspect project metadata",
                "steps": [
                    {
                        "step_id": "inspect_metadata",
                        "description": "Inspect project metadata",
                        "tool": {"name": "project.inspect_metadata", "arguments": {}},
                    }
                ],
            },
        }
        permissions = {grant.permission for grant in request.permissions if grant.allowed}
        validated = validate_plan_envelope(
            envelope,
            request.task_id,
            Path(request.workspace_root or "."),
            registry,
            permissions,
        )
        yield MilProviderEvent(event_type="response.started")
        yield MilProviderEvent(event_type="response.delta", text=validated.response)
        yield MilProviderEvent(event_type="response.completed", text=validated.response)
        yield MilProviderEvent(event_type="plan.proposed", plan=validated.plan)

    async def stream_conversation(self, request: MilRequest) -> AsyncIterator[MilProviderEvent]:
        yield MilProviderEvent(
            event_type="provider.failed",
            text="Qwen is required for conversational responses.",
            detail={"category": "provider_unavailable"},
        )


class QwenMilProvider:
    """Ollama-backed provider that emits only validated typed proposals."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def stream_conversation(self, request: MilRequest) -> AsyncIterator[MilProviderEvent]:
        messages = [{"role": "system", "content": conversation_message()}]
        messages.extend(
            {"role": message.role.value, "content": message.content}
            for message in request.conversation
        )
        if request.runtime_context:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Verified local runtime context (facts only; formulate the answer "
                        "yourself):\n" + json.dumps(request.runtime_context, sort_keys=True)
                    ),
                }
            )
        if request.tool_results:
            messages.append(
                {
                    "role": "system",
                    "content": "Verified tool results:\n"
                    + json.dumps(request.tool_results, sort_keys=True),
                }
            )
        messages.append({"role": "user", "content": request.user_message})
        yield MilProviderEvent(event_type="response.started")
        response_parts: list[str] = []
        usage: dict[str, int] = {}
        try:
            stream_chat = getattr(self._client, "stream_chat", None)
            if stream_chat is None:
                chunks, fallback_usage = await self._client.complete(messages)
                usage.update(fallback_usage)
                for chunk_text in chunks:
                    if chunk_text:
                        response_parts.append(chunk_text)
                        yield MilProviderEvent(event_type="response.delta", text=chunk_text)
            else:
                async for chunk in stream_chat(messages, think=False, max_output_tokens=512):
                    if chunk.text:
                        response_parts.append(chunk.text)
                        yield MilProviderEvent(event_type="response.delta", text=chunk.text)
                    usage.update(chunk.usage)
        except OllamaProviderError as error:
            yield MilProviderEvent(
                event_type="provider.failed",
                text=str(error),
                detail={"category": error.category},
            )
            return
        response = "".join(response_parts).strip()
        if not response:
            yield MilProviderEvent(
                event_type="provider.failed",
                text="Model returned an empty conversational response.",
                detail={"category": "malformed_response"},
            )
            return
        yield MilProviderEvent(event_type="response.completed", text=response, detail=usage)

    async def stream_response(self, request: MilRequest) -> AsyncIterator[MilProviderEvent]:
        if request.task_id is None:
            yield MilProviderEvent(
                event_type="provider.failed", text="A task is required for planning."
            )
            return
        messages = [
            {
                "role": "system",
                "content": system_message(),
            },
            {"role": "system", "content": _planning_contract(request)},
        ]
        messages.extend(
            {"role": message.role.value, "content": message.content}
            for message in request.conversation
        )
        messages.append({"role": "user", "content": request.user_message})
        yield MilProviderEvent(event_type="response.started")
        for attempt in range(2):
            try:
                chunks, usage = await self._client.complete(messages)
            except OllamaProviderError as error:
                yield MilProviderEvent(
                    event_type="provider.failed",
                    text=str(error),
                    detail={"category": error.category, "retry_count": attempt},
                )
                return
            try:
                validated = self._validate_response(request, "".join(chunks))
            except (ValueError, json.JSONDecodeError) as error:
                if attempt == 0:
                    messages.append(
                        {
                            "role": "user",
                            "content": repair_message(str(error)),
                        }
                    )
                    continue
                yield MilProviderEvent(
                    event_type="provider.failed",
                    text="Model output could not be validated after one repair attempt.",
                    detail={
                        "category": "validation_failed",
                        "retry_count": attempt,
                        "reason": str(error)[:240],
                    },
                )
                return
            yield MilProviderEvent(event_type="response.delta", text=validated.response)
            yield MilProviderEvent(event_type="response.completed", text=validated.response)
            yield MilProviderEvent(event_type="plan.proposed", plan=validated.plan, detail=usage)
            return

    @staticmethod
    def _validate_response(request: MilRequest, raw_response: str) -> ValidatedResponse:
        validated = validate_plan_envelope(
            json.loads(raw_response),
            request.task_id or "",
            Path(request.workspace_root or "."),
            ToolRegistry(),
            {grant.permission for grant in request.permissions if grant.allowed},
        )
        available = {tool.name for tool in request.available_tools}
        if any(step.proposal.tool_name not in available for step in validated.plan.steps):
            raise ValueError("response proposes a tool outside the supplied registry")

        return validated


def _planning_contract(request: MilRequest) -> str:
    tools = [tool.model_dump(mode="json") for tool in request.available_tools]
    permissions = sorted({grant.permission for grant in request.permissions if grant.allowed})
    payload = {
        "available_tools": tools,
        "allowed_permissions": permissions,
        "response_schema": RESPONSE_ENVELOPE_SCHEMA,
    }
    return planner_message() + "\n" + json.dumps(payload, sort_keys=True)
