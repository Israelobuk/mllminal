import pytest

from mllminal.agent.routing import MilRoute, route_request


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("hello", MilRoute.CHAT),
        ("what does MLLminal do?", MilRoute.CHAT),
        ("what model are you using?", MilRoute.LOCAL_INFORMATION),
        ("what apps are open right now?", MilRoute.LOCAL_INFORMATION),
        ("is Mil ready?", MilRoute.LOCAL_INFORMATION),
        ("list the files in this folder", MilRoute.READ_ONLY_TOOL),
        ("read README.md", MilRoute.READ_ONLY_TOOL),
        ("open the report", MilRoute.ACTION),
        ("automate this workflow", MilRoute.WORKFLOW),
        ("delete the draft", MilRoute.DESTRUCTIVE_ACTION),
    ],
)
def test_route_request_uses_meaningful_modes(prompt: str, expected: MilRoute) -> None:
    assert route_request(prompt) is expected


