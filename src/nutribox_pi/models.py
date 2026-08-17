"""Domain values shared across PI-0 boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class AnalysisStatus(StrEnum):
    CALCULATED = "calculated"
    FOOD_NOT_RECOGNIZED = "food_not_recognized"
    REQUIRES_FOOD_SELECTION = "requires_food_selection"
    NUTRITION_REFERENCE_NOT_FOUND = "nutrition_reference_not_found"


@dataclass(frozen=True, slots=True)
class HealthResult:
    healthy: bool
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    status: AnalysisStatus
    payload: dict[str, Any]


class CameraCode(StrEnum):
    OK = "ok"
    SKIPPED = "skipped"
    INVALID_CONFIGURATION = "invalid_configuration"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    CAMERA_UNAVAILABLE = "camera_unavailable"
    CAMERA_BUSY = "camera_busy"
    CAMERA_INITIALIZATION_FAILED = "camera_initialization_failed"
    AUTOFOCUS_FAILED = "autofocus_failed"
    AUTOFOCUS_TIMEOUT = "autofocus_timeout"
    INVALID_OUTPUT = "invalid_output"
    OUTPUT_EXISTS = "output_exists"
    CAPTURE_FAILED = "capture_failed"
    INVALID_IMAGE = "invalid_image"
    PUBLICATION_FAILED = "publication_failed"
    CLEANUP_FAILED = "cleanup_failed"


CAMERA_MESSAGES: dict[CameraCode, str] = {
    CameraCode.INVALID_CONFIGURATION: "Camera configuration is invalid.",
    CameraCode.DEPENDENCY_UNAVAILABLE: "Required camera support is unavailable.",
    CameraCode.CAMERA_UNAVAILABLE: "Camera is unavailable.",
    CameraCode.CAMERA_BUSY: "Camera is busy.",
    CameraCode.CAMERA_INITIALIZATION_FAILED: "Camera initialization failed.",
    CameraCode.AUTOFOCUS_FAILED: "Camera autofocus failed.",
    CameraCode.AUTOFOCUS_TIMEOUT: "Camera autofocus timed out.",
    CameraCode.INVALID_OUTPUT: "Capture output is invalid.",
    CameraCode.OUTPUT_EXISTS: "Capture output already exists.",
    CameraCode.CAPTURE_FAILED: "Camera capture failed.",
    CameraCode.INVALID_IMAGE: "Captured image is invalid.",
    CameraCode.PUBLICATION_FAILED: "Image publication failed.",
}


@dataclass(frozen=True, slots=True)
class CameraAvailability:
    available: bool
    code: CameraCode
    message: str
    picamera2_version: str
    libcamera_version: str


@dataclass(frozen=True, slots=True)
class CaptureResult:
    ok: bool
    code: CameraCode
    message: str
    published: bool
    output_path: Path | None
    format: str | None
    width: int | None
    height: int | None
    byte_size: int | None
