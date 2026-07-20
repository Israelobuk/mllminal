"""Hardware and local-runtime profile contracts."""

from enum import StrEnum

from pydantic import Field

from mllminal.contracts import Contract


class RuntimeProfile(StrEnum):
    LIGHT = "light"
    STANDARD = "standard"
    HIGH_CAPABILITY = "high_capability"


class HardwareReport(Contract):
    cpu_count: int = Field(ge=1)
    available_memory_bytes: int = Field(ge=0)
    gpu_available: bool
    windows_version: str
    ui_automation_available: bool
    local_ocr_available: bool
    local_model_available: bool
    configured_model: str
    recommended_profile: RuntimeProfile
    observation_enabled_by_default: bool = False
    data_directory: str
    notes: list[str] = Field(default_factory=list)
