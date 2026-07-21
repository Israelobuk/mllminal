"""Resolve abstract workflow capabilities to the safest available provider."""

from collections.abc import Iterable

from mllminal.providers.contracts import (
    AbstractCapability,
    CapabilityProvider,
    CapabilityResolution,
    ProviderAvailability,
    ProviderKind,
    ProviderStatus,
)
from mllminal.providers.registry import ProviderRegistry


class CapabilityResolver:
    """Resolve native, browser, local, portable, and manual providers in order."""

    def __init__(self, providers: Iterable[CapabilityProvider] = ()) -> None:
        self.registry = ProviderRegistry()
        for provider in providers:
            self.registry.register(provider)
        self._availability: dict[str, ProviderAvailability] = {}

    async def discover(self) -> list[ProviderAvailability]:
        values = []
        for provider in self.registry.all():
            availability = await provider.discover()
            self._availability[provider.name] = availability
            values.append(availability)
        return values

    async def resolve(
        self,
        capability: AbstractCapability | str,
        *,
        preferred_provider: str | None = None,
    ) -> CapabilityResolution:
        requested = AbstractCapability(capability)
        if not self._availability:
            await self.discover()
        candidates = [
            availability
            for availability in self._availability.values()
            if requested in availability.capabilities
            and availability.status in {ProviderStatus.AVAILABLE, ProviderStatus.DETECTED}
        ]
        if preferred_provider:
            candidates.sort(key=lambda item: (item.provider != preferred_provider, item.provider))
        else:
            candidates.sort(key=lambda item: self.registry.get(item.provider).priority)
        if candidates:
            selected = candidates[0]
            return CapabilityResolution(
                capability=requested,
                status=selected.status,
                provider=selected.provider,
                provider_kind=selected.kind,
                available_providers=[item.provider for item in candidates],
                explanation=f"Selected {selected.display_name} for {requested.value}.",
            )
        known = [
            availability
            for availability in self._availability.values()
            if requested in availability.capabilities
        ]
        manual = next((item for item in known if item.kind == ProviderKind.MANUAL), None)
        if manual:
            return CapabilityResolution(
                capability=requested,
                status=ProviderStatus.MANUAL_REQUIRED,
                provider=manual.provider,
                provider_kind=manual.kind,
                available_providers=[item.provider for item in known],
                explanation=manual.explanation,
                manual_steps=list(manual.metadata.get("manual_steps", [])),
            )
        return CapabilityResolution(
            capability=requested,
            status=ProviderStatus.UNSUPPORTED,
            available_providers=[item.provider for item in known],
            explanation=(
                f"No safe provider is available for {requested.value}; install or connect "
                "a supported provider, or revise the workflow."
            ),
        )
