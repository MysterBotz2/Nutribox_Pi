import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from nutribox_pi.adapters.camera_base import CaptureFailure
from nutribox_pi.adapters.picamera2_camera import (
    Picamera2Camera,
    sanitize_version,
)
from nutribox_pi.adapters.simulated_camera import synthetic_jpeg
from nutribox_pi.models import CameraCode


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1.2.3-1~deb13:arm64", "1.2.3-1~deb13:arm64"),
        ("", "unknown"),
        ("bad value", "unknown"),
        ("x" * 65, "unknown"),
        (RuntimeError("secret"), "unknown"),
    ],
)
def test_version_sanitization(value: object, expected: str) -> None:
    assert sanitize_version(value) == expected


def test_missing_picamera2_is_normalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = importlib.import_module

    def missing(name: str, package: str | None = None) -> object:
        if name in {"picamera2", "libcamera"}:
            raise ImportError("secret path")
        return original(name, package)

    monkeypatch.setattr(importlib, "import_module", missing)
    availability = Picamera2Camera().availability()
    assert availability.code is CameraCode.DEPENDENCY_UNAVAILABLE
    assert "secret" not in availability.message


class FocusCamera:
    def __init__(
        self,
        result: bool = True,
        *,
        wait_error: BaseException | None = None,
    ) -> None:
        self.result = result
        self.wait_error = wait_error
        self.job = object()
        self.autofocus_wait_values: list[object] = []
        self.wait_calls: list[tuple[object, float]] = []
        self.cancelled = False

    def autofocus_cycle(self, wait: bool | None = None) -> object:
        self.autofocus_wait_values.append(wait)
        return self.job

    def wait(self, job: object, timeout: float | None = None) -> bool:
        assert timeout is not None
        self.wait_calls.append((job, timeout))
        if self.wait_error is not None:
            raise self.wait_error
        return self.result

    def cancel_all_and_flush(self) -> None:
        self.cancelled = True


LIBCAMERA = SimpleNamespace()


def test_autofocus_uses_bounded_job_wait_and_timely_true_succeeds() -> None:
    camera = FocusCamera(result=True)
    clock = iter([10.0, 10.25, 14.0])
    adapter = Picamera2Camera(monotonic=lambda: next(clock))

    adapter._autofocus(camera)

    assert camera.autofocus_wait_values == [False]
    assert camera.wait_calls == [(camera.job, 4.75)]
    assert 0 < camera.wait_calls[0][1] <= 5.0
    assert camera.cancelled is False


def test_autofocus_timeout_error_cancels_and_maps_to_timeout() -> None:
    camera = FocusCamera(wait_error=TimeoutError())
    clock = iter([0.0, 0.0])
    adapter = Picamera2Camera(monotonic=lambda: next(clock))

    with pytest.raises(CaptureFailure) as failure:
        adapter._autofocus(camera)

    assert failure.value.code is CameraCode.AUTOFOCUS_TIMEOUT
    assert camera.cancelled is True


def test_autofocus_true_after_deadline_cancels_and_times_out() -> None:
    camera = FocusCamera(result=True)
    clock = iter([0.0, 0.0, 5.0])
    adapter = Picamera2Camera(monotonic=lambda: next(clock))

    with pytest.raises(CaptureFailure) as failure:
        adapter._autofocus(camera)

    assert failure.value.code is CameraCode.AUTOFOCUS_TIMEOUT
    assert camera.cancelled is True


def test_autofocus_timely_false_fails() -> None:
    camera = FocusCamera(result=False)
    clock = iter([0.0, 0.0, 4.9])
    adapter = Picamera2Camera(monotonic=lambda: next(clock))

    with pytest.raises(CaptureFailure) as failure:
        adapter._autofocus(camera)

    assert failure.value.code is CameraCode.AUTOFOCUS_FAILED


def test_importing_package_does_not_import_pi_libraries() -> None:
    assert "picamera2" not in sys.modules
    assert "libcamera" not in sys.modules


class StubPicamera:
    close_fails = False

    def __init__(self, camera_index: int = 0) -> None:
        self.camera_index = camera_index

    @staticmethod
    def global_camera_info() -> list[dict[str, str]]:
        return [{"Model": "imx708"}]

    def create_still_configuration(self, **kwargs: object) -> object:
        return kwargs

    def configure(self, configuration: object) -> None:
        pass

    def start(self) -> None:
        pass

    def autofocus_cycle(self, wait: bool | None = None) -> object:
        return object()

    def wait(self, job: object, timeout: float | None = None) -> bool:
        return True

    def cancel_all_and_flush(self) -> None:
        pass

    def capture_file(self, path: str) -> None:
        Path(path).write_bytes(synthetic_jpeg())

    def stop(self) -> None:
        pass

    def close(self) -> None:
        if self.close_fails:
            raise RuntimeError("secret cleanup")


def test_enumeration_exception_has_exact_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EnumerationFailure(StubPicamera):
        @staticmethod
        def global_camera_info() -> list[dict[str, str]]:
            raise RuntimeError("secret enumeration")

    adapter = Picamera2Camera()
    monkeypatch.setattr(
        adapter,
        "_load_stack",
        lambda: (EnumerationFailure, LIBCAMERA, ("1.0", "2.0")),
    )
    availability = adapter.availability()
    assert availability.code is CameraCode.CAMERA_INITIALIZATION_FAILED
    assert availability.message == "Camera initialization failed."


def test_enumeration_without_camera_module_3_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class OtherCamera(StubPicamera):
        @staticmethod
        def global_camera_info() -> list[dict[str, str]]:
            return [{"Model": "imx219"}]

    adapter = Picamera2Camera()
    monkeypatch.setattr(
        adapter,
        "_load_stack",
        lambda: (OtherCamera, LIBCAMERA, ("1.0", "2.0")),
    )
    availability = adapter.availability()
    assert availability.code is CameraCode.CAMERA_UNAVAILABLE


def test_capture_without_camera_module_3_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class OtherCamera(StubPicamera):
        @staticmethod
        def global_camera_info() -> list[dict[str, str]]:
            return [{"Model": "imx219"}]

    adapter = Picamera2Camera()
    monkeypatch.setattr(
        adapter,
        "_load_stack",
        lambda: (OtherCamera, LIBCAMERA, ("1.0", "2.0")),
    )
    result = adapter.capture(tmp_path / "meal.jpg")
    assert result.code is CameraCode.CAMERA_UNAVAILABLE
    assert result.message == "Camera is unavailable."
    assert result.published is False


def test_camera_close_failure_prevents_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class CloseFailure(StubPicamera):
        close_fails = True

    clock = iter([0.0, 0.0, 1.0])
    adapter = Picamera2Camera(monotonic=lambda: next(clock))
    monkeypatch.setattr(
        adapter,
        "_load_stack",
        lambda: (CloseFailure, LIBCAMERA, ("1.0", "2.0")),
    )
    output = tmp_path / "meal.jpg"
    result = adapter.capture(output)
    assert result.code is CameraCode.CLEANUP_FAILED
    assert result.message == "Camera resource cleanup failed."
    assert result.published is False
    assert not output.exists()


def test_partial_start_failure_attempts_stop_and_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class PartialStartFailure(StubPicamera):
        instance: "PartialStartFailure | None" = None

        def __init__(self, camera_index: int = 0) -> None:
            super().__init__(camera_index)
            self.stopped = False
            self.closed = False
            type(self).instance = self

        def start(self) -> None:
            raise RuntimeError("secret partial start")

        def stop(self) -> None:
            self.stopped = True

        def close(self) -> None:
            self.closed = True

    adapter = Picamera2Camera()
    monkeypatch.setattr(
        adapter,
        "_load_stack",
        lambda: (PartialStartFailure, LIBCAMERA, ("1.0", "2.0")),
    )

    result = adapter.capture(tmp_path / "meal.jpg")

    assert result.code is CameraCode.CAMERA_INITIALIZATION_FAILED
    assert PartialStartFailure.instance is not None
    assert PartialStartFailure.instance.stopped is True
    assert PartialStartFailure.instance.closed is True


def test_stop_cancellation_still_closes_and_is_reraised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class StopCancellation(StubPicamera):
        instance: "StopCancellation | None" = None

        def __init__(self, camera_index: int = 0) -> None:
            super().__init__(camera_index)
            self.closed = False
            type(self).instance = self

        def stop(self) -> None:
            raise KeyboardInterrupt

        def close(self) -> None:
            self.closed = True

    clock = iter([0.0, 0.0, 1.0])
    adapter = Picamera2Camera(monotonic=lambda: next(clock))
    monkeypatch.setattr(
        adapter,
        "_load_stack",
        lambda: (StopCancellation, LIBCAMERA, ("1.0", "2.0")),
    )
    output = tmp_path / "meal.jpg"

    with pytest.raises(KeyboardInterrupt):
        adapter.capture(output)

    assert StopCancellation.instance is not None
    assert StopCancellation.instance.closed is True
    assert not output.exists()
    assert not list(tmp_path.glob(".nutribox-camera-*.tmp"))


def test_autofocus_cancellation_flushes_and_preserves_camera_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class AutofocusCancellation(StubPicamera):
        instance: "AutofocusCancellation | None" = None

        def __init__(self, camera_index: int = 0) -> None:
            super().__init__(camera_index)
            self.cancelled = False
            self.stopped = False
            self.closed = False
            type(self).instance = self

        def autofocus_cycle(self, wait: bool | None = None) -> object:
            raise KeyboardInterrupt

        def cancel_all_and_flush(self) -> None:
            self.cancelled = True

        def stop(self) -> None:
            self.stopped = True

        def close(self) -> None:
            self.closed = True

    adapter = Picamera2Camera(monotonic=lambda: 0.0)
    monkeypatch.setattr(
        adapter,
        "_load_stack",
        lambda: (AutofocusCancellation, LIBCAMERA, ("1.0", "2.0")),
    )
    output = tmp_path / "meal.jpg"

    with pytest.raises(KeyboardInterrupt):
        adapter.capture(output)

    assert AutofocusCancellation.instance is not None
    assert AutofocusCancellation.instance.cancelled is True
    assert AutofocusCancellation.instance.stopped is True
    assert AutofocusCancellation.instance.closed is True
    assert not output.exists()
    assert not list(tmp_path.glob(".nutribox-camera-*.tmp"))
