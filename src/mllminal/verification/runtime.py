"""Bounded local Windows frame capture and provider-neutral visual inspection."""

from __future__ import annotations

import ctypes
import hashlib
import struct
import sys
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol

from mllminal.contracts import new_id
from mllminal.device.windows_adapters import (
    WindowsForegroundAdapter,
    WindowsUIAutomationAdapter,
)
from mllminal.privacy.contracts import (
    CaptureCategory,
    CaptureContext,
    CaptureRequest,
    SensitiveControlClassification,
)
from mllminal.privacy.service import PrivacyService
from mllminal.verification.contracts import (
    FrameCaptureMode,
    FrameRegion,
    LocalVisualObservation,
    VisionInspectionResult,
    VisionProviderResult,
    VisionRequest,
    VisualElement,
    VisualVerificationRequest,
)
from mllminal.verification.service import LocalVisualVerificationService


class VisionProvider(Protocol):
    name: str
    available: bool

    async def inspect(
        self, frame: WindowFrameLike, request: VisionRequest
    ) -> VisionProviderResult: ...


class WindowFrameLike(Protocol):
    @property
    def path(self) -> str: ...

    @property
    def application(self) -> str: ...

    @property
    def window_class(self) -> str: ...


@dataclass(frozen=True)
class _WindowContext:
    application: str
    executable_path: str | None
    window_class: str
    title_classification: str
    secure: bool
    hwnd: int
    left: int
    top: int
    width: int
    height: int


class FrameCaptureError(RuntimeError):
    pass


class _Rect(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_uint32),
        ("width", ctypes.c_int32),
        ("height", ctypes.c_int32),
        ("planes", ctypes.c_uint16),
        ("bit_count", ctypes.c_uint16),
        ("compression", ctypes.c_uint32),
        ("size_image", ctypes.c_uint32),
        ("x_pixels_per_meter", ctypes.c_int32),
        ("y_pixels_per_meter", ctypes.c_int32),
        ("colors_used", ctypes.c_uint32),
        ("colors_important", ctypes.c_uint32),
    ]


class _BitmapInfo(ctypes.Structure):
    _fields_ = [("header", _BitmapInfoHeader), ("colors", ctypes.c_uint32 * 3)]


class WindowsFrameCapture:
    """Capture one bounded active-window frame through Windows GDI."""

    def __init__(
        self,
        data_dir: Path,
        *,
        secure_focus: Callable[[], bool] | None = None,
    ) -> None:
        self.data_dir = data_dir
        self.frames_dir = data_dir / "frames"
        self.debug_dir = data_dir / "debug"
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        self.secure_focus = secure_focus
        self.foreground = WindowsForegroundAdapter(use_native=True)

    @property
    def available(self) -> bool:
        return sys.platform == "win32"

    def context(self) -> _WindowContext:
        if not self.available:
            raise FrameCaptureError("Windows GDI capture is unavailable on this platform")
        user32 = ctypes.windll.user32
        hwnd = int(user32.GetForegroundWindow())
        if not hwnd:
            raise FrameCaptureError("No foreground window is available")
        rect = _Rect()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise FrameCaptureError("Foreground window bounds are unavailable")
        window_class = self._window_class(user32, hwnd)
        title = self._window_title(user32, hwnd)
        title_classification = self._classify_title(title, window_class)
        metadata = self.foreground.current_metadata()
        application = str(metadata.get("process_name") or "unknown") if metadata else "unknown"
        executable_path = (
            str(metadata["executable_path"])
            if metadata and metadata.get("executable_path")
            else None
        )
        if metadata:
            window_class = str(metadata.get("window_class") or window_class)
            title_classification = str(metadata.get("title_classification") or title_classification)
        return _WindowContext(
            application=application,
            executable_path=executable_path,
            window_class=window_class,
            title_classification=title_classification,
            secure=title_classification == "secure-dialog"
            or bool(self.secure_focus and self.secure_focus()),
            hwnd=hwnd,
            left=int(rect.left),
            top=int(rect.top),
            width=max(1, int(rect.right - rect.left)),
            height=max(1, int(rect.bottom - rect.top)),
        )

    def capture(
        self,
        request: VisionRequest,
        context: _WindowContext,
    ) -> tuple[CapturedFrame, _WindowContext]:
        if request.mode is FrameCaptureMode.USER_SELECTED_REGION and request.region is None:
            raise ValueError("user_selected_region requires a region")
        left, top, width, height = self._capture_bounds(context, request.region)
        pixels = self._capture_pixels(left, top, width, height)
        self._mask_pixels(pixels, width, height, request.sensitive_regions, request.region)
        target_dir = self.debug_dir if request.debug_retention_seconds else self.frames_dir
        if request.debug_retention_seconds:
            self._cleanup_debug(request.debug_retention_seconds)
        filename = f"{new_id()}.bmp"
        target = target_dir / filename
        self._write_bmp(target, width, height, pixels)
        frame = CapturedFrame(
            path=str(target),
            application=context.application,
            window_class=context.window_class,
            mode=request.mode,
            width=width,
            height=height,
            temporary=not bool(request.debug_retention_seconds),
            fingerprint=hashlib.sha256(pixels).hexdigest(),
        )
        return frame, context

    @staticmethod
    def _capture_bounds(
        context: _WindowContext, region: FrameRegion | None
    ) -> tuple[int, int, int, int]:
        if region is None:
            return context.left, context.top, context.width, context.height
        left = max(0, min(region.left, context.width - 1))
        top = max(0, min(region.top, context.height - 1))
        width = min(region.width, context.width - left)
        height = min(region.height, context.height - top)
        if width <= 0 or height <= 0:
            raise ValueError("capture region falls outside the foreground window")
        return context.left + left, context.top + top, width, height

    @staticmethod
    def _capture_pixels(left: int, top: int, width: int, height: int) -> bytearray:
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        screen = user32.GetDC(0)
        if not screen:
            raise FrameCaptureError("Unable to acquire the Windows screen device context")
        memory = gdi32.CreateCompatibleDC(screen)
        bitmap = gdi32.CreateCompatibleBitmap(screen, width, height)
        selected = gdi32.SelectObject(memory, bitmap)
        try:
            if not gdi32.BitBlt(
                memory, 0, 0, width, height, screen, left, top, 0x00CC0020 | 0x40000000
            ):
                raise FrameCaptureError("Windows BitBlt capture failed")
            info = _BitmapInfo()
            info.header = _BitmapInfoHeader(
                size=ctypes.sizeof(_BitmapInfoHeader),
                width=width,
                height=-height,
                planes=1,
                bit_count=24,
                compression=0,
                size_image=0,
                x_pixels_per_meter=0,
                y_pixels_per_meter=0,
                colors_used=0,
                colors_important=0,
            )
            stride = (width * 3 + 3) & ~3
            pixels = ctypes.create_string_buffer(stride * height)
            copied = gdi32.GetDIBits(memory, bitmap, 0, height, pixels, ctypes.byref(info), 0)
            if copied != height:
                raise FrameCaptureError("Windows GetDIBits capture failed")
            return bytearray(pixels.raw)
        finally:
            gdi32.SelectObject(memory, selected)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(memory)
            user32.ReleaseDC(0, screen)

    @staticmethod
    def _mask_pixels(
        pixels: bytearray,
        width: int,
        height: int,
        regions: list[FrameRegion],
        capture_region: FrameRegion | None,
    ) -> None:
        if not regions:
            return
        offset_left = capture_region.left if capture_region else 0
        offset_top = capture_region.top if capture_region else 0
        stride = (width * 3 + 3) & ~3
        for region in regions:
            left = max(0, region.left - offset_left)
            top = max(0, region.top - offset_top)
            right = min(width, region.left + region.width - offset_left)
            bottom = min(height, region.top + region.height - offset_top)
            for row in range(top, max(top, bottom)):
                start = row * stride + left * 3
                end = row * stride + right * 3
                pixels[start:end] = b"\x00" * max(0, end - start)

    @staticmethod
    def _write_bmp(path: Path, width: int, height: int, pixels: bytearray) -> None:
        info = struct.pack(
            "<IiiHHIIiiII",
            40,
            width,
            -height,
            1,
            24,
            0,
            len(pixels),
            0,
            0,
            0,
            0,
        )
        header = struct.pack("<2sIHHI", b"BM", 14 + len(info) + len(pixels), 0, 0, 14 + len(info))
        path.write_bytes(header + info + pixels)

    @staticmethod
    def _window_title(user32: Any, hwnd: int) -> str:
        length = int(user32.GetWindowTextLengthW(hwnd))
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return str(buffer.value)

    @staticmethod
    def _window_class(user32: Any, hwnd: int) -> str:
        buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buffer, 256)
        return str(buffer.value or "unknown")

    @staticmethod
    def _classify_title(title: str, window_class: str) -> str:
        lowered = title.casefold()
        if not title:
            return "unknown"
        if any(marker in lowered for marker in ("password", "sign in", "login", "credential")):
            return "secure-dialog"
        if "#32770" in window_class or "dialog" in window_class.casefold():
            return "dialog"
        return "document"

    def _cleanup_debug(self, retention_seconds: int) -> None:
        cutoff = datetime.now(UTC).timestamp() - retention_seconds
        for path in self.debug_dir.glob("*.bmp"):
            with suppress(OSError):
                if path.stat().st_mtime < cutoff:
                    path.unlink()


@dataclass(frozen=True)
class CapturedFrame:
    path: str
    application: str
    window_class: str
    mode: FrameCaptureMode
    width: int
    height: int
    temporary: bool
    fingerprint: str


class LocalVisionProvider:
    name = "local.ocr-uia"

    def __init__(self) -> None:
        self.uia = WindowsUIAutomationAdapter(use_native=True)
        self.pytesseract = self._optional_module("pytesseract")
        self.available = self.uia.capability().available or self.pytesseract is not None

    async def inspect(self, frame: WindowFrameLike, request: VisionRequest) -> VisionProviderResult:
        elements: list[VisualElement] = []
        confidence = 0.0
        if self.uia.capability().available:
            metadata = self.uia.focused_metadata()
            if metadata and not metadata.get("secure", False):
                label = str(
                    metadata.get("name") or metadata.get("automation_id") or "focused control"
                )
                elements.append(
                    VisualElement(
                        role=str(metadata.get("control_type") or "control"),
                        semantic_name=label,
                        confidence=0.95,
                    )
                )
                confidence = 0.95
        if self.pytesseract is not None:
            elements.extend(self._ocr(frame.path))
            if elements:
                confidence = max(confidence, 0.7)
        text = " ".join(element.semantic_name.casefold() for element in elements)
        return VisionProviderResult(
            provider=self.name,
            elements=elements[:256],
            confidence=confidence,
            error_visible="error" in text or "failed" in text,
            loading_visible="loading" in text or "please wait" in text,
            dialog_visible="dialog" in text,
            unsupported_reason=None
            if self.available
            else "local OCR and UI Automation unavailable",
        )

    def _ocr(self, path: str) -> list[VisualElement]:
        pytesseract = self.pytesseract
        if pytesseract is None:
            return []
        try:
            output = pytesseract.image_to_data(path, output_type=pytesseract.Output.DICT)
        except Exception:
            return []
        results: list[VisualElement] = []
        for index, raw in enumerate(output.get("text", [])):
            label = str(raw).strip()
            if not label or any(
                marker in label.casefold() for marker in ("password", "token", "cookie", "secret")
            ):
                continue
            try:
                confidence = max(0.0, min(1.0, float(output["conf"][index]) / 100.0))
                bounds = (
                    float(output["left"][index]),
                    float(output["top"][index]),
                    float(output["width"][index]),
                    float(output["height"][index]),
                )
            except (KeyError, TypeError, ValueError, IndexError):
                confidence, bounds = None, None
            results.append(
                VisualElement(
                    role="text", semantic_name=label, bounds=bounds, confidence=confidence
                )
            )
        return results

    @staticmethod
    def _optional_module(name: str) -> Any | None:
        try:
            return import_module(name)
        except ImportError:
            return None


class LocalVisionRuntime:
    def __init__(
        self,
        data_dir: Path,
        privacy: PrivacyService,
        visual: LocalVisualVerificationService,
        *,
        provider: VisionProvider | None = None,
    ) -> None:
        self.privacy = privacy
        self.visual = visual
        self.capture = WindowsFrameCapture(data_dir)
        self.provider = provider or LocalVisionProvider()

    async def inspect(self, request: VisionRequest) -> VisionInspectionResult:
        context = self.capture.context()
        permission = self.privacy.capture(
            CaptureRequest(
                category=CaptureCategory.TEMPORARY_VISION,
                payload={"application": context.application, "visual_state": "frame_requested"},
                context=CaptureContext(
                    application=context.application,
                    executable_path=context.executable_path,
                    window_title=context.title_classification,
                    secure_control=(
                        SensitiveControlClassification.SECURE
                        if context.secure
                        else SensitiveControlClassification.NONE
                    ),
                    adapter="windows.vision",
                ),
            ),
            idempotency_key=f"vision-capture:{new_id()}",
        )
        if not permission.accepted:
            raise PermissionError(f"Vision capture rejected: {permission.decision.reason}")
        frame, context = self.capture.capture(request, context)
        try:
            result = await self.provider.inspect(frame, request)
            observation = LocalVisualObservation(
                application=context.application,
                window_class=context.window_class,
                capture_mode=request.mode,
                elements=result.elements,
                provider=result.provider,
                confidence=result.confidence,
                error_visible=result.error_visible,
                loading_visible=result.loading_visible,
                dialog_visible=result.dialog_visible,
                unsupported_reason=result.unsupported_reason,
                frame_deleted=frame.temporary,
            )
            recorded = self.visual.observe(observation)
            verification = (
                self.visual.verify(
                    VisualVerificationRequest(
                        observation=recorded,
                        expected=request.expected,
                        mode=request.match_mode,
                    )
                )
                if request.expected
                else None
            )
            return VisionInspectionResult(observation=recorded, verification=verification)
        finally:
            if frame.temporary:
                with suppress(OSError):
                    Path(frame.path).unlink()
