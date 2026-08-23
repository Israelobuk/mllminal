from pathlib import Path

from mllminal.client.interactive.commands import filter_commands, help_text
from mllminal.client.interactive.renderer import (
    ActivityItem,
    StartupSnapshot,
    TerminalRenderer,
)


def test_command_filtering_is_grouped_and_prefix_aware() -> None:
    matches = filter_commands("/wo")

    assert [item.name for item in matches] == ["/workspace", "/workflows"]
    assert "Session" in help_text()
    assert "/approvals" in help_text()


def test_wide_startup_panel_contains_product_state_and_real_activity(tmp_path: Path) -> None:
    snapshot = StartupSnapshot(
        version="0.1.0",
        model="qwen3:4b",
        provider="Qwen via Ollama",
        workspace=tmp_path,
        runtime="Ready",
        recent_activity=(ActivityItem("Organized Downloads", "completed", "18m ago"),),
        quick_starts=("Summarize files in this folder", "Show my workflows"),
        tip="Type / to browse commands.",
    )

    output = TerminalRenderer(width=110, no_color=True).startup(snapshot)

    assert "MLLminal" in output
    assert "Mil · qwen3:4b · Qwen via Ollama" in output
    assert "Workspace:" in output
    assert "● Ready" in output
    assert "Organized Downloads" in output
    assert "Show my workflows" in output
    assert "Type / to browse commands." in output


def test_narrow_startup_panel_does_not_emit_wide_layout(tmp_path: Path) -> None:
    snapshot = StartupSnapshot(
        version="0.1.0",
        model="qwen3:4b",
        provider="Qwen",
        workspace=tmp_path,
        runtime="Unavailable",
        recent_activity=(),
        quick_starts=(),
        tip="Type /help for commands.",
    )

    output = TerminalRenderer(width=42, no_color=True).startup(snapshot)

    assert output.splitlines()[0] == "MLLminal"
    assert "Workspace:" in output
    assert "Runtime: ! Unavailable" in output
    assert "Quick start" not in output
    assert max(map(len, output.splitlines())) <= 42


def test_no_color_renderer_has_no_ansi_escape_sequences(tmp_path: Path) -> None:
    snapshot = StartupSnapshot(
        version="0.1.0",
        model="deterministic",
        provider="Fixture",
        workspace=tmp_path,
        runtime="Ready",
        recent_activity=(),
        quick_starts=("Ask Mil a question",),
        tip="Type /help for commands.",
    )

    output = TerminalRenderer(width=80, no_color=True).startup(snapshot)

    assert "\x1b[" not in output
    assert "No recent activity" in output
