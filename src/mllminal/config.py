"""Portable daemon and client configuration."""

from pathlib import Path

from platformdirs import user_data_path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    def api_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def ensure_data_dir(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
