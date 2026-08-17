import json
from pathlib import Path

import pytest

from nutribox_pi.adapters.simulated_camera import SimulatedCamera
from nutribox_pi.camera_diagnostics import (
    CameraDiagnosticsService,
    capture_as_dict,
    format_camera_capture,
    format_camera_check,
)
from nutribox_pi.models import CameraAvailability, CameraCode, CaptureResult


class UnavailableCamera:
    def availability(self) -> CameraAvailability:
        return CameraAvailability(
            False,
            CameraCode.CAMERA_UNAVAILABLE,
            "Camera is unavailable.",
            "unknown",
            "unknown",
        )

    def capture(
        self, output_path: Path, overwrite: bool = False
    ) -> CaptureResult:
        raise AssertionError("capture must be skipped")


def test_camera_check_success_schema_and_human_output() -> None:
    report = CameraDiagnosticsService(SimulatedCamera()).run()

    assert report.ok is True
    assert set(report.as_dict()) == {"command", "ok", "camera_stack", "checks"}
    assert report.as_dict()["camera_stack"] == {
        "picamera2_version": "not-applicable",
        "libcamera_version": "not-applicable",
    }
    assert [item["status"] for item in report.as_dict()["checks"]] == [
        "pass",
        "pass",
        "pass",
    ]
    assert format_camera_check(report) == (
        "Nutri-Box camera check\n"
        "Camera stack:\n"
        '- picamera2_version: "not-applicable"\n'
        '- libcamera_version: "not-applicable"\n'
        "Checks:\n"
        "- availability: PASS [ok] - Camera is available.\n"
        "- capture: PASS [ok] - Camera capture passed.\n"
        "- cleanup: PASS [ok] - Temporary image cleanup passed.\n"
        "Overall: PASS"
    )


def test_camera_check_unavailable_transitions_are_exact() -> None:
    report = CameraDiagnosticsService(UnavailableCamera()).run()
    payload = report.as_dict()
    assert report.ok is False
    assert [item["status"] for item in payload["checks"]] == [
        "fail",
        "skipped",
        "skipped",
    ]
    assert [item["code"] for item in payload["checks"]] == [
        "camera_unavailable",
        "skipped",
        "skipped",
    ]


def test_capture_serializers_omit_path_and_metadata_on_failure() -> None:
    result = CaptureResult(
        False,
        CameraCode.CLEANUP_FAILED,
        "Image was published, but private temporary cleanup failed.",
        True,
        Path("/secret/meal.jpg"),
        "jpeg",
        1920,
        1080,
        100,
    )
    payload = capture_as_dict(result)
    assert set(payload) == {"command", "ok", "code", "message"}
    assert "/secret" not in json.dumps(payload)
    assert "File:" not in format_camera_capture(result)


def test_capture_success_human_output_escapes_basename() -> None:
    result = CaptureResult(
        True,
        CameraCode.OK,
        "Image captured.",
        True,
        Path('quote"name.jpg'),
        "jpeg",
        1920,
        1080,
        10,
    )
    assert 'File: "quote\\\"name.jpg"' in format_camera_capture(result)


def test_diagnostics_redacts_adapter_messages_and_stack_metadata() -> None:
    class UnsafeCamera(UnavailableCamera):
        def availability(self) -> CameraAvailability:
            return CameraAvailability(
                False,
                CameraCode.CAMERA_UNAVAILABLE,
                "/secret/raw exception",
                "/secret/picamera",
                "version with newline\nsecret",
            )

    report = CameraDiagnosticsService(UnsafeCamera()).run()
    payload = json.dumps(report.as_dict())
    assert report.availability.message == "Camera is unavailable."
    assert report.availability.picamera2_version == "unknown"
    assert report.availability.libcamera_version == "unknown"
    assert "/secret" not in payload


def test_diagnostics_rejects_non_ascii_stack_metadata() -> None:
    class NonAsciiCamera(UnavailableCamera):
        def availability(self) -> CameraAvailability:
            return CameraAvailability(
                False,
                CameraCode.CAMERA_UNAVAILABLE,
                "Camera is unavailable.",
                "v\u00e9rsion",
                "\uff11.2.3",
            )

    report = CameraDiagnosticsService(NonAsciiCamera()).run()

    assert report.availability.picamera2_version == "unknown"
    assert report.availability.libcamera_version == "unknown"


def test_diagnostic_cancellation_is_reraised_after_cleanup() -> None:
    class CancellingCamera:
        output: Path | None = None

        def availability(self) -> CameraAvailability:
            return CameraAvailability(
                True,
                CameraCode.OK,
                "Camera is available.",
                "not-applicable",
                "not-applicable",
            )

        def capture(
            self, output_path: Path, overwrite: bool = False
        ) -> CaptureResult:
            self.output = output_path
            output_path.write_bytes(b"private image")
            raise KeyboardInterrupt

    camera = CancellingCamera()

    with pytest.raises(KeyboardInterrupt):
        CameraDiagnosticsService(camera).run()

    assert camera.output is not None
    assert not camera.output.exists()
    assert not camera.output.parent.exists()
