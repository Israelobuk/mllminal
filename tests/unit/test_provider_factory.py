from mllminal.agent.factory import create_provider
from mllminal.agent.provider import DeterministicMilProvider, QwenMilProvider
from mllminal.config import ProviderConfig


def test_provider_factory_selects_configured_implementation() -> None:
    deterministic = create_provider(ProviderConfig(provider="deterministic"))
    qwen = create_provider(
        ProviderConfig(provider="qwen", model="qwen:test", base_url="http://ollama.test")
    )

    assert isinstance(deterministic, DeterministicMilProvider)
    assert isinstance(qwen, QwenMilProvider)
