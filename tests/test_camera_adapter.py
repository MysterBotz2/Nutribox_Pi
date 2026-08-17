import os
from pathlib import Path

import pytest

from nutribox_pi.adapters import camera_base
from nutribox_pi.adapters.simulated_camera import SimulatedCamera, synthetic_jpeg
from nutribox_pi.camera_validation import (
    CameraValidationError,
    inspect_jpeg,
)
from nutribox_pi.config import CameraConfigurationError, CameraSettings
from nutribox_pi.models import CameraCode


def test_camera_settings_are_independent_of_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NUTRIBOX_API_BASE_URL", raising=False)
    monkeypatch.setenv("NUTRIBOX_CAMERA_ADAPTER", "simulated")
    assert CameraSettings.from_env().adapter == "simulated"


@pytest.mark.parametrize("value", [None, "", "other", "PICAMERA2"])
def test_camera_settings_have_no_default(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv("NUTRIBOX_CAMERA_ADAPTER", raising=False)
    else:
        monkeypatch.setenv("NUTRIBOX_CAMERA_ADAPTER", value)
    with pytest.raises(CameraConfigurationError):
        CameraSettings.from_env()


def test_simulated_camera_is_deterministic_and_publishes_private_jpeg(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpeg"
    camera = SimulatedCamera()

    first_result = camera.capture(first)
    camera.capture(second)

    assert first_result.ok is True
    assert first_result.published is True
    assert first_result.output_path == first.absolute()
    assert first_result.format == "jpeg"
    assert (first_result.width, first_result.height) == (1920, 1080)
    assert first.read_bytes() == second.read_bytes() == synthetic_jpeg()
    assert inspect_jpeg(first).byte_size == first_result.byte_size
    if os.name == "posix":
        assert first.stat().st_mode & 0o777 == 0o600


def test_no_clobber_preserves_existing_file(tmp_path: Path) -> None:
    output = tmp_path / "meal.jpg"
    output.write_bytes(b"original")

    result = SimulatedCamera().capture(output)

    assert result.code is CameraCode.OUTPUT_EXISTS
    assert result.published is False
    assert output.read_bytes() == b"original"


def test_overwrite_atomically_replaces_regular_file(tmp_path: Path) -> None:
    output = tmp_path / "meal.jpg"
    output.write_bytes(b"original")

    result = SimulatedCamera().capture(output, overwrite=True)

    assert result.ok is True
    assert output.read_bytes() == synthetic_jpeg()


@pytest.mark.parametrize(
    "name", ["bad\nname.jpg", "bad\x1bname.jpg", "bad\u202ename.jpg"]
)
def test_output_rejects_control_and_format_characters(
    tmp_path: Path, name: str
) -> None:
    result = SimulatedCamera().capture(tmp_path / name)
    assert result.code is CameraCode.INVALID_OUTPUT


def test_output_rejects_symlink_parent(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    actual.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(actual, target_is_directory=True)

    result = SimulatedCamera().capture(linked / "meal.jpg")

    assert result.code is CameraCode.INVALID_OUTPUT
    assert not (actual / "meal.jpg").exists()


def test_jpeg_inspector_rejects_wrong_dimensions(tmp_path: Path) -> None:
    image = tmp_path / "wrong.jpg"
    image.write_bytes(synthetic_jpeg().replace(b"\x04\x38", b"\x04\x37", 1))
    with pytest.raises(CameraValidationError):
        inspect_jpeg(image)


def test_jpeg_inspector_rejects_missing_eoi(tmp_path: Path) -> None:
    image = tmp_path / "truncated.jpg"
    image.write_bytes(synthetic_jpeg()[:-2])
    with pytest.raises(CameraValidationError):
        inspect_jpeg(image)


def test_staging_creation_failure_is_normalized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: object, **kwargs: object) -> tuple[int, str]:
        raise OSError("secret staging path")

    monkeypatch.setattr(camera_base.tempfile, "mkstemp", fail)
    result = SimulatedCamera().capture(tmp_path / "meal.jpg")
    assert result.code is CameraCode.CAPTURE_FAILED
    assert result.message == "Camera capture failed."
    assert "secret" not in result.message


def test_staging_descriptor_close_failure_prevents_publication_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cleanup_paths: list[Path] = []
    close_attempts = 0
    original_unlink_twice = camera_base.SafeCameraAdapter._unlink_twice

    def fail_close(descriptor: int) -> None:
        nonlocal close_attempts
        close_attempts += 1
        if close_attempts == 1:
            raise OSError("secret descriptor failure")
        os.close(descriptor)

    def record_cleanup(path: Path) -> bool:
        cleanup_paths.append(path)
        return original_unlink_twice(path)

    monkeypatch.setattr(
        camera_base.SafeCameraAdapter,
        "_close_staging_descriptor",
        staticmethod(fail_close),
    )
    monkeypatch.setattr(
        camera_base.SafeCameraAdapter,
        "_unlink_twice",
        staticmethod(record_cleanup),
    )
    destination = tmp_path / "meal.jpg"

    result = SimulatedCamera().capture(destination)

    assert result.code is CameraCode.PUBLICATION_FAILED
    assert result.message == "Image publication failed."
    assert result.published is False
    assert not destination.exists()
    assert close_attempts == 2
    assert len(cleanup_paths) == 1
    assert not cleanup_paths[0].exists()
