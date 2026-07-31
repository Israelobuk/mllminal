"""Keyboard-first Mil terminal backed by the authenticated daemon."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mllminal.client.api import DaemonClient
from mllminal.config import Settings

ClientFactory = Callable[[Settings], DaemonClient]
TERMINAL_STATES = {"COMPLETED", "FAILED", "BLOCKED", "CANCELLED"}


def _session_path(settings: Settings) -> Path:
    return settings.data_dir / "mil-session"


def _read_session(settings: Settings) -> str | None:
    try:
        value = _session_path(settings).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


async def _prepare_session(client: DaemonClient, settings: Settings) -> str:
    client.session_id = _read_session(settings)
    if client.session_id is not None:
        try:
            await client.request("GET", f"/v1/sessions/{client.session_id}")
        except (OSError, PermissionError, RuntimeError):
            client.session_id = None
    session_id = await client.ensure_session()
    settings.ensure_data_dir()
    _session_path(settings).write_text(session_id + "\n", encoding="utf-8")
    return session_id


async def _history(client: DaemonClient, session_id: str) -> list[dict[str, Any]]:
    value = await client.request("GET", f"/v1/sessions/{session_id}")
    return value.get("messages", []) if isinstance(value, dict) else []


async def _wait_for_final(client: DaemonClient, task_id: str) -> dict[str, Any]:
    previous: str | None = None
    for _ in range(300):
        task = await client.request("GET", f"/v1/tasks/{task_id}")
        if not isinstance(task, dict):
            raise RuntimeError("daemon returned an invalid task projection")
        state = str(task.get("state", ""))
        if state != previous:
            print(f"state: {state}")
            previous = state
        if state in TERMINAL_STATES:
            return task
        await asyncio.sleep(0.2)
    raise TimeoutError("timed out waiting for the daemon to finish verification")


async def _submit(client: DaemonClient, settings: Settings, content: str) -> None:
    session_id = await _prepare_session(client, settings)
    result: dict[str, Any] | None = None
    streamed_text = ""
    async for item in client.stream_chat(content):
        if item.get("type") == "event":
            event = item.get("event", {})
            if event.get("event_type") == "response.delta":
                payload = event.get("payload", {})
                text = payload.get("text") if isinstance(payload, dict) else None
                if isinstance(text, str):
                    print(text, end="", flush=True)
                    streamed_text += text
            continue
        if item.get("type") == "error":
            error = item.get("error", {})
            message = error.get("message") if isinstance(error, dict) else None
            raise RuntimeError(str(message or "Mil provider failed"))
        if item.get("type") == "pending":
            pending = item.get("pending")
            if isinstance(pending, dict):
                result = pending
    if streamed_text:
        print()
    if result is None:
        raise RuntimeError("daemon ended the Mil stream without a pending task")
    task = result.get("task", {})
    plan = result.get("plan", {})
    approval = result.get("approval", {})
    task_id = task.get("id")
    print("Mil:")
    messages = await _history(client, session_id)
    if messages:
        latest = messages[-1]
        if latest.get("role") == "mil":
            print(latest.get("content", ""))
    print("Plan:")
    for step in plan.get("steps", []):
        proposal = step.get("proposal", {})
        title = step.get("title", proposal.get("tool_name", "action"))
        print(f"  {step.get('position', '?')}. {title}")
    approval_id = approval.get("id")
    if not approval_id or not task_id:
        print("No executable approval was returned; the daemon owns the final state.")
        return
    answer = input("Approve this plan? [y/N] ").strip().lower()
    if answer not in {"y", "yes"}:
        print("Plan left pending; no action was executed.")
        return
    decided = await client.request(
        "POST",
        f"/v1/approvals/{approval_id}/decisions",
        {"status": "APPROVED"},
        idempotency_key=f"mil-approval-{approval_id}",
    )
    if isinstance(decided, dict):
        print(f"approval: {decided.get('state', 'recorded')}")
    final = await _wait_for_final(client, str(task_id))
    final_state = str(final.get("state"))
    if final_state == "COMPLETED":
        print("Verified completion recorded by the daemon.")
    else:
        print(f"Execution ended without verified completion: {final_state}")


def run_mil_terminal(settings: Settings, client_factory: ClientFactory = DaemonClient) -> None:
    """Run a persistent local session with bounded slash commands."""
    client = client_factory(settings)
    print("Mil terminal. Type /help for commands; /quit to exit.")
    while True:
        try:
            line = input("mil> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return
        command = line.strip()
        if command in {"/quit", "/exit"}:
            return
        if command == "/help":
            print("/history  show durable session messages")
            print("/clear    start a new session")
            print("/begin    enter multiline mode")
            print("/quit     exit")
            continue
        if command == "/clear":
            _session_path(settings).unlink(missing_ok=True)
            client.session_id = None
            print("Started a new Mil session.")
            continue
        if command == "/history":
            try:
                session_id = asyncio.run(_prepare_session(client, settings))
                for message in asyncio.run(_history(client, session_id)):
                    print(f"{message.get('role', 'unknown')}: {message.get('content', '')}")
            except (OSError, PermissionError, RuntimeError, TimeoutError) as error:
                print(f"daemon unavailable: {error}")
            continue
        if command == "/begin":
            lines: list[str] = []
            print("multiline mode; finish with /end")
            while True:
                try:
                    part = input("... ")
                except (EOFError, KeyboardInterrupt):
                    return
                if part.strip() == "/end":
                    break
                lines.append(part)
            command = "\n".join(lines).strip()
        if not command:
            continue
        try:
            asyncio.run(_submit(client, settings, command))
        except (OSError, PermissionError, RuntimeError, TimeoutError) as error:
            print(f"daemon unavailable; durable state was not assumed: {error}")
