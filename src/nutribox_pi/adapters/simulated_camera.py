"""Deterministic camera adapter for PC and CI."""

from __future__ import annotations

import os
from pathlib import Path

from nutribox_pi.adapters.camera_base import CaptureFailure, SafeCameraAdapter
from nutribox_pi.models import (
    CameraAvailability,
    CameraCode,
    CaptureResult,
    PreviewFrame,
)


def synthetic_jpeg() -> bytes:
    sof = (
        b"\xff\xc0\x00\x11\x08"
        + (1080).to_bytes(2, "big")
        + (1920).to_bytes(2, "big")
        + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
    )
    return b"\xff\xd8" + sof + b"\xff\xd9"


class SimulatedCamera(SafeCameraAdapter):
    is_simulated = True

    def availability(self) -> CameraAvailability:
        return CameraAvailability(
            True,
            CameraCode.OK,
            "Camera is available.",
            "not-applicable",
            "not-applicable",
        )

    def open_preview_session(self) -> SimulatedPreviewSession:
        return SimulatedPreviewSession(self)

    def _capture_to_staging(self, staging: Path) -> None:
        try:
            output = staging.open("wb")
        except OSError as exc:
            raise CaptureFailure(CameraCode.PUBLICATION_FAILED) from exc
        failure: CaptureFailure | None = None
        try:
            try:
                output.write(synthetic_jpeg())
            except OSError as exc:
                failure = CaptureFailure(CameraCode.CAPTURE_FAILED)
                failure.__cause__ = exc
            if failure is None:
                try:
                    output.flush()
                    os.fsync(output.fileno())
                except OSError as exc:
                    failure = CaptureFailure(CameraCode.PUBLICATION_FAILED)
                    failure.__cause__ = exc
        finally:
            try:
                output.close()
            except OSError as exc:
                failure = CaptureFailure(CameraCode.PUBLICATION_FAILED)
                failure.__cause__ = exc
        if failure is not None:
            raise failure


class SimulatedPreviewSession:
    def __init__(self, camera: SimulatedCamera) -> None:
        self._camera = camera
        self._closed = False

    def read_frame(self) -> PreviewFrame | None:
        if self._closed:
            return None
        return PreviewFrame(640, 360, bytes((61, 179, 90)) * (640 * 360))

    def capture(self, output_path: Path, overwrite: bool = False) -> CaptureResult:
        if self._closed:
            return self._camera._failure(CameraCode.CAMERA_UNAVAILABLE)
        return self._camera.capture(output_path, overwrite)

    def close(self) -> bool:
        self._closed = True
        return True
