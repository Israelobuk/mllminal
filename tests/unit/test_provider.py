from pathlib import Path

from mllminal.agent.provider import DeterministicMilProvider


def test_provider_streams_mil_response_and_typed_inspection_plan(tmp_path: Path) -> None:
    provider = DeterministicMilProvider()

    response = provider.plan("task-1", "inspect this project", tmp_path)

    assert "inspect" in "".join(response.chunks).lower()
    assert response.plan.task_id == "task-1"
    assert response.plan.steps[0].proposal.tool_name == "project.inspect_metadata"
    assert response.plan.steps[0].proposal.reversible is True
