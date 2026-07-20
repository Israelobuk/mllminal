from pathlib import Path

import pytest

from mllminal.actions.contracts import ActionRequest
from mllminal.actions.service import BoundedActionService
from mllminal.apps.contracts import CapabilityRequest
from mllminal.apps.filesystem import FilesystemAdapter
from mllminal.apps.service import ApplicationBridgeService
from mllminal.workflow.contracts import (
    CapabilityResult,
    WorkflowDefinition,
    WorkflowPermission,
    WorkflowRunRequest,
    WorkflowStep,
    WorkflowVerification,
)
from mllminal.workflow.service import WorkflowService


@pytest.mark.asyncio
async def test_filesystem_adapter_confines_inspection_to_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    adapter = FilesystemAdapter(workspace)

    result = await adapter.execute(
        CapabilityRequest(capability="filesystem.inspect", arguments={"folder": str(outside)})
    )

    assert result.succeeded is False
    assert result.error == "path_outside_workspace"


@pytest.mark.asyncio
async def test_application_bridge_emergency_stop_blocks_preview_and_execution(
    tmp_path: Path,
) -> None:
    bridge = ApplicationBridgeService(
        tmp_path / "state.db",
        workspace_root=tmp_path,
        emergency_stop_active=lambda: True,
    )

    with pytest.raises(PermissionError, match="Emergency stop"):
        await bridge.execute(
            "filesystem",
            CapabilityRequest(capability="filesystem.inspect"),
            idempotency_key="blocked-bridge",
        )


def test_bounded_actions_require_approval_and_honor_emergency_stop() -> None:
    blocked = BoundedActionService(emergency_stop_active=lambda: True)
    with pytest.raises(PermissionError, match="Emergency stop"):
        blocked.execute(
            ActionRequest(action="application.focus", application="fixture"),
            idempotency_key="blocked-action",
        )

    service = BoundedActionService(executor=lambda _request: {"performed": True})
    with pytest.raises(PermissionError, match="approval"):
        service.execute(
            ActionRequest(
                action="application.focus",
                application="fixture",
                preview=False,
                workflow_authorized=True,
            ),
            idempotency_key="approval-required",
        )
    result = service.execute(
        ActionRequest(
            action="application.focus",
            application="fixture",
            preview=False,
            workflow_authorized=True,
            action_approved=True,
        ),
        idempotency_key="approved-action",
    )
    assert result.executed is True
    assert result.mutation_performed is True


def test_non_preview_workflow_executes_and_persists_runtime_state(tmp_path: Path) -> None:
    service = WorkflowService(tmp_path / "workflow.db")
    definition = WorkflowDefinition(
        name="fixture workflow",
        permissions=[WorkflowPermission(capability="fixture.ok", scope="fixture")],
        steps=[
            WorkflowStep(
                order=1,
                capability="fixture.ok",
                approval_required=False,
                verification=WorkflowVerification(expected={"ok": True}),
            )
        ],
    )
    service.create(definition, idempotency_key="create-workflow")
    service.activate(definition.id, idempotency_key="activate-workflow")
    service.register_capability(
        "fixture.ok",
        lambda _arguments: CapabilityResult(
            capability="fixture.ok", succeeded=True, output={"ok": True}
        ),
    )

    run = service.run(
        definition.id,
        WorkflowRunRequest(preview=False),
        idempotency_key="run-workflow",
    )

    assert run.state.value == "succeeded"
    assert run.step_results[0].verification.state.value == "passed"
    assert service.run_record(run.id).state.value == "succeeded"


@pytest.mark.asyncio
async def test_application_bridge_verification_rejects_forged_result(tmp_path: Path) -> None:
    bridge = ApplicationBridgeService(tmp_path / "state.db", workspace_root=tmp_path)
    result = await bridge.execute(
        "filesystem",
        CapabilityRequest(capability="filesystem.inspect", arguments={"folder": "."}),
        idempotency_key="persisted-execution",
    )

    verified = await bridge.verify("filesystem", result)
    assert verified.succeeded is True

    forged = result.model_copy(update={"output": {"entries": ["forged"]}})
    with pytest.raises(PermissionError, match="persisted bridge execution"):
        await bridge.verify("filesystem", forged)
