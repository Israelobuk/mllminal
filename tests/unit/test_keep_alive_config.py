from mllminal.config import ProviderConfig


def test_provider_config_keeps_ollama_warm_by_default() -> None:
    assert ProviderConfig().keep_alive == "10m"
    assert ProviderConfig(keep_alive="30m").keep_alive == "30m"
