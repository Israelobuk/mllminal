"""Low-overhead latency tracing for Mil request routing and inference."""

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any


@dataclass
class LatencyTrace:
    route: str
    model: str
    history_size: int
    tool_count: int
    cache_hit: bool = False
    warm: bool | None = None
    marks: dict[str, float] = field(default_factory=dict)

    def mark(self, name: str, timestamp: float | None = None) -> None:
        self.marks[name] = perf_counter() if timestamp is None else timestamp

    def to_dict(self) -> dict[str, Any]:
        durations = {
            "routing": self._duration("input_received", "routing_complete"),
            "context": self._duration("routing_complete", "context_ready"),
            "ollama_wait": self._duration(
                "ollama_request_started", "first_token_received"
            ),
            "ttft": self._duration("input_received", "first_token_received"),
            "generation": self._duration("first_token_received", "response_complete"),
            "total": self._duration("input_received", "response_complete"),
        }
        return {
            "route": self.route,
            "model": self.model,
            "history_size": self.history_size,
            "tool_count": self.tool_count,
            "cache_hit": self.cache_hit,
            "warm": self.warm,
            "durations_ms": durations,
        }

    def _duration(self, start: str, end: str) -> float | None:
        if start not in self.marks or end not in self.marks:
            return None
        return round((self.marks[end] - self.marks[start]) * 1000, 3)
