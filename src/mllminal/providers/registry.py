"""Deterministic registry for capability providers."""

from mllminal.providers.contracts import CapabilityProvider


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, CapabilityProvider] = {}

    def register(self, provider: CapabilityProvider) -> None:
        if provider.name in self._providers:
            raise ValueError(f"Provider already registered: {provider.name}")
        self._providers[provider.name] = provider

    def get(self, name: str) -> CapabilityProvider:
        try:
            return self._providers[name]
        except KeyError as exc:
            raise KeyError(f"Unknown provider: {name}") from exc

    def all(self) -> list[CapabilityProvider]:
        return sorted(self._providers.values(), key=lambda item: (item.priority, item.name))
