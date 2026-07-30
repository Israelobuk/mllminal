"""Provider-neutral application discovery facade."""

from mllminal.apps.contracts import (
    ApplicationAdapter,
    ApplicationAvailability,
    CapabilityDefinition,
    CapabilityDiscoveryReport,
    DiscoveredCapability,
)
from mllminal.apps.registry import ApplicationRegistry


class ApplicationDiscovery:
    def __init__(self, registry: ApplicationRegistry, *, max_capabilities: int = 128) -> None:
        if max_capabilities < 1:
            raise ValueError("max_capabilities must be positive")
        self.registry = registry
        self.max_capabilities = max_capabilities

    async def discover(self) -> list[ApplicationAvailability]:
        return [await adapter.detect() for adapter in self.registry.all()]

    async def capabilities(self, application: str) -> list[CapabilityDefinition]:
        adapter: ApplicationAdapter = self.registry.get(application)
        return await adapter.capabilities()

    async def discover_capabilities(self, application: str) -> CapabilityDiscoveryReport:
        """Discover only registered, bounded capabilities and retain their provenance."""

        try:
            adapter: ApplicationAdapter = self.registry.get(application)
        except KeyError:
            return CapabilityDiscoveryReport(
                application=application,
                explanation="No bounded adapter is registered for this application.",
            )
        try:
            definitions = await adapter.capabilities()
        except Exception as error:
            return CapabilityDiscoveryReport(
                application=application,
                complete=False,
                explanation=(f"Capability discovery failed safely: {error.__class__.__name__}."),
            )
        bounded_definitions = definitions[: self.max_capabilities]
        return CapabilityDiscoveryReport(
            application=application,
            capabilities=[
                DiscoveredCapability(
                    capability=definition,
                    provider=adapter.name,
                    source="registered_adapter",
                    confidence=1.0,
                )
                for definition in bounded_definitions
            ],
            complete=len(definitions) <= self.max_capabilities,
            explanation=(
                "Capabilities discovered from a registered bounded adapter."
                if len(definitions) <= self.max_capabilities
                else "Capability list was truncated at the configured discovery bound."
            ),
        )
