"""Local-only PI-1B camera diagnostics and output formatting."""

from __future__ import annotations

import json
import os
import string
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from nutribox_pi.camera_validation import CameraValidationError, inspect_jpeg
from nutribox_pi.models import (
    CAMERA_MESSAGES,
    CameraAvailability,
    CameraCode,
    CaptureResult,
)
from nutribox_pi.ports import Camera

CheckStatus = Literal["pass", "fail", "skipped"]
_SAFE_VERSION_CHARACTERS = frozenset(
    string.ascii_letters + string.digits + ".+_-~:"
)


@dataclass(frozen=True, slots=True)
class CameraCheck:
    name: str
    status: CheckStatus
    code: CameraCode
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status,
            "code": self.code.value,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class CameraCheckReport:
    availability: CameraAvailability
    checks: tuple[CameraCheck, CameraCheck, CameraCheck]

    @property
    def ok(self) -> bool:
        return all(check.status == "pass" for check in self.checks)

    def as_dict(self) -> dict[str, Any]:
        return {
            "command": "camera-check",
            "ok": self.ok,
            "camera_stack": {
                "picamera2_version": self.availability.picamera2_version,
                "libcamera_version": self.availability.libcamera_version,
            },
            "checks": [check.as_dict() for check in self.checks],
        }


class CameraDiagnosticsService:
    def __init__(self, camera: Camera) -> None:
        self._camera = camera

    def run(self) -> CameraCheckReport:
        availability = self._safe_availability()
        if not availability.available:
            return CameraCheckReport(
                availability,
                (
                    CameraCheck(
                        "availability",
                        "fail",
                        availability.code,
                        availability.message,
                    ),
                    CameraCheck(
                        "capture",
                        "skipped",
                        CameraCode.SKIPPED,
                        "Capture skipped because camera availability failed.",
                    ),
                    CameraCheck(
                        "cleanup",
                        "skipped",
                        CameraCode.SKIPPED,
                        "Cleanup skipped because no temporary resources were created.",
                    ),
                ),
            )

        availability_check = CameraCheck(
            "availability", "pass", CameraCode.OK, "Camera is available."
        )
        try:
            directory = Path(tempfile.mkdtemp(prefix="nutribox-camera-check-"))
        except OSError:
            return CameraCheckReport(
                availability,
                (
                    availability_check,
                    CameraCheck(
                        "capture",
                        "fail",
                        CameraCode.CAPTURE_FAILED,
                        "Camera capture failed.",
                    ),
                    CameraCheck(
                        "cleanup",
                        "skipped",
                        CameraCode.SKIPPED,
                        "Cleanup skipped because no temporary resources were created.",
                    ),
                ),
            )

        if os.name == "posix":
            try:
                os.chmod(directory, 0o700)
            except OSError:
                return CameraCheckReport(
                    availability,
                    (
                        availability_check,
                        CameraCheck(
                            "capture",
                            "fail",
                            CameraCode.CAPTURE_FAILED,
                            "Camera capture failed.",
                        ),
                        self._cleanup(directory / "capture.jpg", directory),
                    ),
                )

        output = directory / "capture.jpg"
        try:
            result = self._safe_capture(output)
            capture_check = self._capture_check(result, output)
        finally:
            cleanup_check = self._cleanup(output, directory)
        return CameraCheckReport(
            availability,
            (availability_check, capture_check, cleanup_check),
        )

    def _safe_availability(self) -> CameraAvailability:
        try:
            availability = self._camera.availability()
        except Exception:
            return CameraAvailability(
                False,
                CameraCode.CAMERA_INITIALIZATION_FAILED,
                "Camera initialization failed.",
                "unknown",
                "unknown",
            )
        try:
            code = CameraCode(availability.code)
            available = bool(availability.available)
            if (available and code is not CameraCode.OK) or (
                not available and code is CameraCode.OK
            ):
                raise ValueError
            return CameraAvailability(
                available,
                code,
                "Camera is available." if available else CAMERA_MESSAGES[code],
                _safe_stack_version(availability.picamera2_version),
                _safe_stack_version(availability.libcamera_version),
            )
        except (AttributeError, TypeError, ValueError, KeyError):
            return CameraAvailability(
                False,
                CameraCode.CAMERA_INITIALIZATION_FAILED,
                "Camera initialization failed.",
                "unknown",
                "unknown",
            )

    def _safe_capture(self, output: Path) -> CaptureResult:
        try:
            return self._camera.capture(output, overwrite=False)
        except Exception:
            return CaptureResult(
                False,
                CameraCode.CAPTURE_FAILED,
                "Camera capture failed.",
                False,
                None,
                None,
                None,
                None,
                None,
            )

    @staticmethod
    def _capture_check(result: CaptureResult, output: Path) -> CameraCheck:
        if result.ok:
            try:
                inspect_jpeg(output)
            except CameraValidationError:
                return CameraCheck(
                    "capture",
                    "fail",
                    CameraCode.INVALID_IMAGE,
                    "Captured image is invalid.",
                )
            return CameraCheck(
                "capture", "pass", CameraCode.OK, "Camera capture passed."
            )
        try:
            code = CameraCode(result.code)
        except ValueError:
            code = CameraCode.CAPTURE_FAILED
        return CameraCheck("capture", "fail", code, _safe_capture_message(code, result))

    @staticmethod
    def _cleanup(output: Path, directory: Path) -> CameraCheck:
        failed = False
        try:
            output.unlink(missing_ok=True)
        except OSError:
            failed = True
        try:
            directory.rmdir()
        except OSError:
            failed = True
        if failed:
            return CameraCheck(
                "cleanup",
                "fail",
                CameraCode.CLEANUP_FAILED,
                "Temporary image cleanup failed.",
            )
        return CameraCheck(
            "cleanup",
            "pass",
            CameraCode.OK,
            "Temporary image cleanup passed.",
        )


def _safe_stack_version(value: object) -> str:
    if value == "not-applicable":
        return value
    if not isinstance(value, str) or not value or len(value) > 64:
        return "unknown"
    if any(character not in _SAFE_VERSION_CHARACTERS for character in value):
        return "unknown"
    return value


def _safe_capture_message(code: CameraCode, result: CaptureResult) -> str:
    if code is CameraCode.CLEANUP_FAILED:
        permitted = {
            "Camera resource cleanup failed.",
            "Camera and private temporary cleanup failed.",
            "Private temporary cleanup failed.",
            "Image was published, but private temporary cleanup failed.",
        }
        return (
            result.message
            if result.message in permitted
            else PRIVATE_CLEANUP_MESSAGE
        )
    return CAMERA_MESSAGES.get(code, "Camera capture failed.")


PRIVATE_CLEANUP_MESSAGE = "Private temporary cleanup failed."


def format_camera_check(report: CameraCheckReport) -> str:
    lines = [
        "Nutri-Box camera check",
        "Camera stack:",
        (
            "- picamera2_version: "
            + json.dumps(report.availability.picamera2_version, ensure_ascii=True)
        ),
        (
            "- libcamera_version: "
            + json.dumps(report.availability.libcamera_version, ensure_ascii=True)
        ),
        "Checks:",
    ]
    for check in report.checks:
        lines.append(
            f"- {check.name}: {check.status.upper()} "
            f"[{check.code.value}] - {check.message}"
        )
    lines.append(f"Overall: {'PASS' if report.ok else 'FAIL'}")
    return "\n".join(lines)


def capture_as_dict(result: CaptureResult) -> dict[str, Any]:
    if not result.ok:
        return {
            "command": "camera-capture",
            "ok": False,
            "code": result.code.value,
            "message": result.message,
        }
    assert result.output_path is not None
    return {
        "command": "camera-capture",
        "ok": True,
        "code": "ok",
        "message": "Image captured.",
        "file_name": result.output_path.name,
        "format": "jpeg",
        "width": 1920,
        "height": 1080,
    }


def format_camera_capture(result: CaptureResult) -> str:
    if not result.ok:
        return "\n".join(
            (
                "Nutri-Box camera capture",
                "Status: FAIL",
                f"Code: {result.code.value}",
                f"Message: {result.message}",
            )
        )
    assert result.output_path is not None
    return "\n".join(
        (
            "Nutri-Box camera capture",
            "Status: PASS",
            "Code: ok",
            "Message: Image captured.",
            f"File: {json.dumps(result.output_path.name, ensure_ascii=True)}",
            "Format: jpeg",
            "Dimensions: 1920x1080",
        )
    )
