"""Application adapter registry."""

from mllminal.apps.contracts import ApplicationAdapter


class ApplicationRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, ApplicationAdapter] = {}

    def register(self, adapter: ApplicationAdapter) -> None:
        if adapter.name in self._adapters:
            raise ValueError(f"Application adapter already registered: {adapter.name}")
        self._adapters[adapter.name] = adapter

    def get(self, name: str) -> ApplicationAdapter:
        try:
            return self._adapters[name]
        except KeyError:
            raise KeyError(f"Unknown application adapter: {name}") from None

    def all(self) -> list[ApplicationAdapter]:
        return list(self._adapters.values())
