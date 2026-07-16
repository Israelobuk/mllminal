"""Configured construction of provider implementations."""

from mllminal.agent.ollama import OllamaClient
from mllminal.agent.provider import DeterministicMilProvider, MilProvider, QwenMilProvider
from mllminal.config import ProviderConfig


def create_provider(config: ProviderConfig) -> MilProvider:
    """Build one provider from non-secret persisted configuration."""
    if config.provider == "deterministic":
        return DeterministicMilProvider()
    return QwenMilProvider(
        OllamaClient(
            config.base_url,
            config.model,
            timeout_seconds=config.request_timeout_seconds,
        )
    )
