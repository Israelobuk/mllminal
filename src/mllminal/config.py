"""Portable daemon and client configuration."""

from pathlib import Path
from typing import Literal

from platformdirs import user_data_path
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderConfig(BaseModel):
    """Persisted, non-secret local model selection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Literal["deterministic", "qwen"] = "qwen"
    model: str = "qwen3:4b"
    base_url: str = "http://127.0.0.1:11434"
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_context_tokens: int = Field(default=8192, ge=256)
    request_timeout_seconds: float = Field(default=120, gt=0)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MLLMINAL_", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 7337
    data_dir: Path = Field(default_factory=lambda: user_data_path("MLLminal", appauthor=False))
    workspace_root: Path = Field(default_factory=Path.cwd)

    @property
    def database_path(self) -> Path:
        return self.data_dir / "mllminal.db"

    @property
    def token_path(self) -> Path:
        return self.data_dir / "token"

    @property
    def pid_path(self) -> Path:
        return self.data_dir / "daemon.json"

    @property
    def lock_path(self) -> Path:
        return self.data_dir / "daemon.lock"

    @property
    def log_path(self) -> Path:
        return self.data_dir / "mllminal.log"

    @property
    def provider_config_path(self) -> Path:
        return self.data_dir / "mil-provider.json"

    @property
    def api_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def ensure_data_dir(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


class ProviderConfigStore:
    """Loads and atomically saves the model provider selection."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def load(self) -> ProviderConfig:
        path = self._settings.provider_config_path
        if not path.is_file():
            return ProviderConfig()
        return ProviderConfig.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, config: ProviderConfig) -> ProviderConfig:
        self._settings.ensure_data_dir()
        path = self._settings.provider_config_path
        temporary = path.with_suffix(".json.next")
        temporary.write_text(config.model_dump_json(indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
        return config
