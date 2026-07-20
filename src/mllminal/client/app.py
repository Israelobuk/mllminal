"""Small local-first Textual dashboard for MLLminal safety state."""

from __future__ import annotations

from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Header, Static


class MLLminalDesktopApp(App[None]):
    TITLE = "MLLminal"
    SUB_TITLE = "Local workflow intelligence"
    CSS = """
    Screen {
        align: center middle;
        background: $surface;
    }
    #dashboard {
        width: 72;
        height: auto;
        padding: 2 3;
        border: round $accent;
        background: $panel;
    }
    #status {
        margin: 1 0;
        color: $text;
    }
    #posture {
        color: $success;
    }
    """
    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        ("q", "quit", "Quit")
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="dashboard"):
            yield Static("MLLminal local dashboard", id="title")
            yield Static(
                "Privacy: consent and capture controls remain user-managed\n"
                "Observation: metadata-only and locally retained\n"
                "Execution: preview and explicit approval required",
                id="status",
            )
            yield Static(
                "No screen recording, credential access, cloud upload, or automatic action.",
                id="posture",
            )
        yield Footer()


def main() -> None:
    MLLminalDesktopApp().run()


if __name__ == "__main__":
    main()
