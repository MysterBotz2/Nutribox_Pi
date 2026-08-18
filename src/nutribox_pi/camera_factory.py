"""Camera-only construction independent of backend settings."""

from __future__ import annotations

from pathlib import Path

from nutribox_pi.adapters.camera_base import SafeCameraAdapter
from nutribox_pi.adapters.picamera2_camera import Picamera2Camera
from nutribox_pi.adapters.simulated_camera import SimulatedCamera
from nutribox_pi.config import CameraConfigurationError, CameraSettings
from nutribox_pi.models import (
    CAMERA_MESSAGES,
    CameraAvailability,
    CameraCode,
    CaptureResult,
)


class InvalidConfigurationCamera(SafeCameraAdapter):
    def availability(self) -> CameraAvailability:
        return CameraAvailability(
            False,
            CameraCode.INVALID_CONFIGURATION,
            CAMERA_MESSAGES[CameraCode.INVALID_CONFIGURATION],
            "unknown",
            "unknown",
        )

    def _capture_to_staging(self, staging: Path) -> None:
        raise AssertionError("invalid camera must never capture")

    def capture(self, output_path: Path, overwrite: bool = False) -> CaptureResult:
        return self._failure(CameraCode.INVALID_CONFIGURATION)

    def open_preview_session(self) -> None:
        return None


def camera_from_env() -> SafeCameraAdapter:
    try:
        settings = CameraSettings.from_env()
    except CameraConfigurationError:
        return InvalidConfigurationCamera()
    if settings.adapter == "simulated":
        return SimulatedCamera()
    return Picamera2Camera()
