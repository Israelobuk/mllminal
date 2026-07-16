from pathlib import Path

from mllminal.config import ProviderConfig, ProviderConfigStore, Settings


def test_provider_config_defaults_to_qwen_and_persists_selection(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, workspace_root=tmp_path)
    store = ProviderConfigStore(settings)

    assert store.load().provider == "qwen"

    stored = store.save(ProviderConfig(provider="deterministic", model="fixture"))
    reloaded = ProviderConfigStore(settings).load()

    assert stored.provider == "deterministic"
    assert reloaded == stored
    assert settings.provider_config_path.is_file()
