"""Non-invasive local hardware and runtime capability detection."""

from __future__ import annotations

import ctypes
import importlib.util
import os
import platform
import shutil
import sys

from mllminal.config import ProviderConfigStore, Settings
from mllminal.device.windows_adapters import WindowsUIAutomationAdapter
from mllminal.hardware.contracts import HardwareReport, RuntimeProfile


class HardwareProbe:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()

    def report(self) -> HardwareReport:
        cpu_count = max(1, os.cpu_count() or 1)
        memory = self._available_memory()
        gpu = self._gpu_available()
        configured_model = ProviderConfigStore(self.settings).load().model
        model_available = shutil.which("ollama") is not None
        uia = WindowsUIAutomationAdapter(use_native=True).capability().available
        ocr = importlib.util.find_spec("pytesseract") is not None
        profile = self._profile(cpu_count, memory, gpu)
        notes = [
            "Observation is disabled until the user explicitly enables it.",
            "Model installation and launch require explicit user confirmation.",
        ]
        if not model_available:
            notes.append(
                "No local Ollama executable was detected; deterministic mode remains available."
            )
        if not ocr:
            notes.append("Local OCR provider is not installed.")
        return HardwareReport(
            cpu_count=cpu_count,
            available_memory_bytes=memory,
            gpu_available=gpu,
            windows_version=platform.version(),
            ui_automation_available=uia,
            local_ocr_available=ocr,
            local_model_available=model_available,
            configured_model=configured_model,
            recommended_profile=profile,
            data_directory=str(self.settings.data_dir),
            notes=notes,
        )

    @staticmethod
    def _profile(cpu_count: int, memory: int, gpu: bool) -> RuntimeProfile:
        if gpu and cpu_count >= 8 and memory >= 16 * 1024**3:
            return RuntimeProfile.HIGH_CAPABILITY
        if cpu_count >= 4 and memory >= 8 * 1024**3:
            return RuntimeProfile.STANDARD
        return RuntimeProfile.LIGHT

    @staticmethod
    def _gpu_available() -> bool:
        try:
            import torch

            return bool(torch.cuda.is_available())
        except (ImportError, RuntimeError):
            return False

    @staticmethod
    def _available_memory() -> int:
        if sys.platform == "win32":

            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("length", ctypes.c_uint32),
                    ("memory_load", ctypes.c_uint32),
                    ("total_phys", ctypes.c_uint64),
                    ("available_phys", ctypes.c_uint64),
                    ("total_page", ctypes.c_uint64),
                    ("available_page", ctypes.c_uint64),
                    ("total_virtual", ctypes.c_uint64),
                    ("available_virtual", ctypes.c_uint64),
                    ("available_extended", ctypes.c_uint64),
                ]

            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.available_phys)
            return 0
        try:
            pages = os.sysconf("SC_AVPHYS_PAGES")
            size = os.sysconf("SC_PAGE_SIZE")
            return int(pages * size)
        except (ValueError, OSError):
            return 0
