from pathlib import Path

from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document

from mllminal.client.interactive.commands import filter_commands, help_text
from mllminal.client.interactive.completion import ContextResource, MilCompleter
from mllminal.client.interactive.history import LocalPromptHistory
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


def _completion_texts(completer: MilCompleter, value: str) -> list[str]:
    document = Document(value, len(value))
    event = CompleteEvent(completion_requested=True)
    return [item.text for item in completer.get_completions(document, event)]


def test_completion_filters_slash_commands_and_real_context_resources(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("local", encoding="utf-8")
    completer = MilCompleter(
        tmp_path,
        resources=(
            ContextResource("README.md", "file", "README.md"),
            ContextResource("Weekly report", "workflow", "weekly-report"),
        ),
    )

    assert _completion_texts(completer, "/wo") == ["/workspace", "/workflows"]
    assert _completion_texts(completer, "summarize @") == ["@README.md", "@weekly-report"]


def test_file_completion_stays_inside_workspace(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "documents").mkdir()
    completer = MilCompleter(tmp_path)

    assert _completion_texts(completer, "summarize ./doc") == ["./docs/", "./documents/"]
    assert _completion_texts(completer, "summarize ../") == []


def test_local_prompt_history_is_bounded_and_skips_sensitive_prompts(tmp_path: Path) -> None:
    path = tmp_path / "mil-history.jsonl"
    history = LocalPromptHistory(path, max_entries=2)
    history.append_string("first")
    history.append_string("second")
    history.append_string("password=secret")
    history.append_string("third")

    restored = LocalPromptHistory(path, max_entries=2)

    assert restored.get_strings() == ["second", "third"]
    assert "password=secret" not in path.read_text(encoding="utf-8")
