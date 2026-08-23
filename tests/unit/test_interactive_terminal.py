import asyncio
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
from mllminal.client.interactive.session import InteractiveSession
from mllminal.config import Settings


def test_command_filtering_is_grouped_and_prefix_aware() -> None:
    matches = filter_commands("/wo")

    assert [item.name for item in matches] == ["/workspace", "/workflows"]
    assert "Session" in help_text()
    assert "/approvals" in help_text()


def test_prompt_toolkit_session_exposes_placeholder_and_footer(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path)
    session = InteractiveSession(settings, use_prompt_toolkit=True, width=80)

    session._configure_prompt(())

    assert session._prompt_session is not None
    assert session._prompt_session.placeholder == session.renderer.prompt_placeholder()
    assert callable(session._prompt_session.bottom_toolbar)


def test_prompt_toolkit_read_uses_distinct_input_surface(tmp_path: Path) -> None:
    calls: dict[str, object] = {}

    class FakePrompt:
        def prompt(self, message: str, **kwargs: object) -> str:
            calls["message"] = message
            calls.update(kwargs)
            return "/exit"

    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path)
    session = InteractiveSession(settings, use_prompt_toolkit=True, width=80)
    session._prompt_session = FakePrompt()  # type: ignore[assignment]

    assert session._read(session.renderer.prompt_prefix()) == "/exit"
    assert "\u2500" in str(calls["message"])
    assert calls["placeholder"] == session.renderer.prompt_placeholder()
    assert callable(calls["bottom_toolbar"])


def test_startup_context_sources_include_workspace_entries(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("local", encoding="utf-8")
    (tmp_path / "docs").mkdir()

    class StartupClient:
        def __init__(self, _settings: Settings) -> None:
            pass

        async def request(self, _method: str, path: str) -> object:
            return {
                "/v1/status": {"daemon": "Online", "model": "qwen3:4b", "provider": "qwen"},
                "/v1/tasks": [],
                "/v1/workflows": [],
                "/v1/workflow-runs": [],
                "/v1/apps": [],
            }.get(path, {})

    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path)
    session = InteractiveSession(settings, StartupClient)

    _snapshot, resources = asyncio.run(session._load_startup())

    assert ("README.md", "file") in {(item.value, item.kind) for item in resources}
    assert ("docs/", "folder") in {(item.value, item.kind) for item in resources}


def test_context_completion_exposes_category_metadata(tmp_path: Path) -> None:
    completer = MilCompleter(
        tmp_path,
        resources=(
            ContextResource("README.md", "file", "README.md"),
            ContextResource("Weekly report", "workflow", "weekly-report"),
        ),
    )

    completions = list(
        completer.get_completions(
            Document("summarize @", len("summarize @")),
            CompleteEvent(completion_requested=True),
        )
    )

    assert [item.display_meta[0][1] for item in completions] == ["file", "workflow"]


def test_wide_welcome_is_a_cohesive_application_surface(tmp_path: Path) -> None:
    snapshot = StartupSnapshot(
        version="0.1.0",
        model="qwen3:4b",
        provider="Qwen via Ollama",
        workspace=tmp_path,
        runtime="Ready",
        quick_starts=("Summarize files in this folder",),
        tip="Type / to browse commands.",
    )

    output = TerminalRenderer(width=120, no_color=True).startup(snapshot)

    assert output.splitlines()[0].startswith("╭")
    assert "Welcome back" in output
    assert "Getting started" in output
    assert "Recent activity" in output
    assert "No recent activity" in output
    assert "Type / to browse commands." in output
    assert max(map(len, output.splitlines())) <= 120


def test_first_run_welcome_has_distinct_greeting_and_bounded_card(tmp_path: Path) -> None:
    snapshot = StartupSnapshot(
        version="0.1.0",
        model="local model",
        provider="unavailable",
        workspace=tmp_path,
        runtime="Unavailable",
        first_run=True,
    )

    output = TerminalRenderer(width=100, no_color=True).startup(snapshot)

    assert "Welcome to MLLminal" in output
    assert output.splitlines()[0].startswith("╭")
    assert max(map(len, output.splitlines())) <= 100


def test_welcome_layout_stays_inside_narrow_and_medium_widths(tmp_path: Path) -> None:
    snapshot = StartupSnapshot(
        version="0.1.0",
        model="qwen3:4b",
        provider="Qwen",
        workspace=tmp_path,
        runtime="Ready",
        quick_starts=("Summarize files",),
        tip="Use @ to add context.",
    )

    for width in (50, 80, 120, 160):
        output = TerminalRenderer(width=width, no_color=True).startup(snapshot)
        assert max(map(len, output.splitlines())) <= width


def test_action_surfaces_keep_approval_and_state_bounded() -> None:
    renderer = TerminalRenderer(width=50, no_color=True)
    plan = renderer.plan(["Open the project", "Verify the result"])

    assert "Plan ready" in plan
    assert max(map(len, plan.splitlines())) <= 50
    assert "[A] Approve plan" in renderer.approval_prompt()
    assert "EXECUTING" in renderer.task_state("EXECUTING")


def test_footer_and_prompt_placeholder_use_real_snapshot_state(tmp_path: Path) -> None:
    snapshot = StartupSnapshot(
        version="0.1.0",
        model="qwen3:4b",
        provider="Qwen",
        workspace=tmp_path,
        runtime="Ready",
    )
    renderer = TerminalRenderer(width=80, no_color=True)

    assert "qwen3:4b" in renderer.footer(snapshot)
    assert "Ready" in renderer.footer(snapshot)
    assert renderer.prompt_placeholder() == "Ask Mil to work with your files, apps, or workflows..."


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
