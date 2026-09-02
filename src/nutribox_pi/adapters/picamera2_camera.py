"""Lazy Raspberry Pi Camera Module 3 adapter."""

from __future__ import annotations

import errno
import importlib
import importlib.metadata
import os
import re
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from nutribox_pi.adapters.camera_base import (
    CAMERA_CLEANUP,
    CaptureFailure,
    SafeCameraAdapter,
)
from nutribox_pi.models import (
    CAMERA_MESSAGES,
    CameraAvailability,
    CameraCode,
    CaptureResult,
    PreviewFrame,
)

_SAFE_VERSION = re.compile(r"[A-Za-z0-9._+\-~:]{1,64}\Z", re.ASCII)
_REQUIRED_METHODS = (
    "global_camera_info",
    "create_still_configuration",
    "configure",
    "start",
    "autofocus_cycle",
    "wait",
    "cancel_all_and_flush",
    "capture_file",
    "stop",
    "close",
)
_PREVIEW_METHODS = (
    "create_preview_configuration",
    "capture_array",
    "switch_mode_and_capture_file",
)


def sanitize_version(value: object) -> str:
    if not isinstance(value, str) or not _SAFE_VERSION.fullmatch(value):
        return "unknown"
    return value


class Picamera2Camera(SafeCameraAdapter):
    def __init__(
        self,
        *,
        monotonic: Any = time.monotonic,
    ) -> None:
        self._monotonic = monotonic

    def availability(self) -> CameraAvailability:
        loaded = self._load_stack()
        if isinstance(loaded, CameraAvailability):
            return loaded
        picamera_class, _libcamera, versions = loaded
        if not self._has_required_api(picamera_class):
            return self._unavailable(CameraCode.DEPENDENCY_UNAVAILABLE, versions)
        try:
            cameras = picamera_class.global_camera_info()
        except Exception:
            return self._unavailable(CameraCode.CAMERA_INITIALIZATION_FAILED, versions)
        if self._compatible_index(cameras) is None:
            return self._unavailable(CameraCode.CAMERA_UNAVAILABLE, versions)
        return CameraAvailability(
            True,
            CameraCode.OK,
            "Camera is available.",
            versions[0],
            versions[1],
        )

    def open_preview_session(self) -> Picamera2PreviewSession | None:
        session = Picamera2PreviewSession(self)
        return session if session.start() else None

    def _capture_to_staging(self, staging: Path) -> None:
        loaded = self._load_stack()
        if isinstance(loaded, CameraAvailability):
            raise CaptureFailure(loaded.code, loaded.message)
        picamera_class, _libcamera, _versions = loaded
        if not self._has_required_api(picamera_class):
            raise CaptureFailure(CameraCode.DEPENDENCY_UNAVAILABLE)

        camera: Any | None = None
        start_attempted = False
        operation_error: BaseException | None = None
        try:
            try:
                try:
                    cameras = picamera_class.global_camera_info()
                except Exception as exc:
                    raise CaptureFailure(
                        CameraCode.CAMERA_INITIALIZATION_FAILED
                    ) from exc
                camera_index = self._compatible_index(cameras)
                if camera_index is None:
                    raise CaptureFailure(CameraCode.CAMERA_UNAVAILABLE)
                camera = picamera_class(camera_index)
                configuration = camera.create_still_configuration(
                    main={"size": (1920, 1080)}
                )
                camera.configure(configuration)
                start_attempted = True
                camera.start()
            except OSError as exc:
                code = (
                    CameraCode.CAMERA_BUSY
                    if exc.errno == errno.EBUSY
                    else CameraCode.CAMERA_INITIALIZATION_FAILED
                )
                raise CaptureFailure(code) from exc
            except CaptureFailure:
                raise
            except Exception as exc:
                raise CaptureFailure(CameraCode.CAMERA_INITIALIZATION_FAILED) from exc

            self._autofocus(camera)
            try:
                camera.capture_file(str(staging), format="jpeg")
            except Exception as exc:
                raise CaptureFailure(CameraCode.CAPTURE_FAILED) from exc
        except BaseException as exc:
            operation_error = exc

        cleanup_failed = False
        cleanup_cancellation: BaseException | None = None
        if camera is not None:
            try:
                if start_attempted:
                    try:
                        camera.stop()
                    except BaseException as exc:
                        if isinstance(exc, Exception):
                            cleanup_failed = True
                        else:
                            cleanup_cancellation = exc
            finally:
                try:
                    camera.close()
                except BaseException as exc:
                    if isinstance(exc, Exception):
                        cleanup_failed = True
                    elif cleanup_cancellation is None:
                        cleanup_cancellation = exc

        if operation_error is not None and not isinstance(operation_error, Exception):
            raise operation_error
        if cleanup_cancellation is not None:
            raise cleanup_cancellation
        if cleanup_failed:
            raise CaptureFailure(CameraCode.CLEANUP_FAILED, CAMERA_CLEANUP)
        if operation_error is not None:
            raise operation_error
        self._sync_path_capture(staging)

    def _autofocus(self, camera: Any) -> None:
        deadline = self._monotonic() + 5.0
        cancel_attempted = False
        try:
            job = camera.autofocus_cycle(wait=False)
            remaining_seconds = deadline - self._monotonic()
            if remaining_seconds <= 0:
                cancel_attempted = True
                self._cancel_or_raise(camera)
                raise CaptureFailure(CameraCode.AUTOFOCUS_TIMEOUT)
            try:
                result = camera.wait(job, timeout=remaining_seconds)
            except TimeoutError as exc:
                cancel_attempted = True
                self._cancel_or_raise(camera)
                raise CaptureFailure(CameraCode.AUTOFOCUS_TIMEOUT) from exc
            if self._monotonic() >= deadline:
                cancel_attempted = True
                self._cancel_or_raise(camera)
                raise CaptureFailure(CameraCode.AUTOFOCUS_TIMEOUT)
            if result is True:
                return
            raise CaptureFailure(CameraCode.AUTOFOCUS_FAILED)
        except CaptureFailure:
            raise
        except BaseException as exc:
            cancel_error = None
            if not cancel_attempted:
                cancel_error = self._cancel(camera)
            if not isinstance(exc, Exception):
                raise exc
            self._raise_cancel_error(cancel_error)
            raise CaptureFailure(CameraCode.AUTOFOCUS_FAILED) from exc

    @staticmethod
    def _cancel(camera: Any) -> BaseException | None:
        try:
            camera.cancel_all_and_flush()
        except BaseException as exc:
            return exc
        return None

    @classmethod
    def _cancel_or_raise(cls, camera: Any) -> None:
        cls._raise_cancel_error(cls._cancel(camera))

    @staticmethod
    def _raise_cancel_error(error: BaseException | None) -> None:
        if error is None:
            return
        if not isinstance(error, Exception):
            raise error
        raise CaptureFailure(CameraCode.CLEANUP_FAILED, CAMERA_CLEANUP) from error

    @staticmethod
    def _sync_path_capture(staging: Path) -> None:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor: int | None = None
        try:
            descriptor = os.open(staging, flags)
            os.fsync(descriptor)
        except OSError as exc:
            raise CaptureFailure(CameraCode.PUBLICATION_FAILED) from exc
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError as exc:
                    raise CaptureFailure(CameraCode.PUBLICATION_FAILED) from exc

    @staticmethod
    def _has_required_api(picamera_class: Any) -> bool:
        return all(hasattr(picamera_class, name) for name in _REQUIRED_METHODS)

    @staticmethod
    def _compatible_index(cameras: object) -> int | None:
        if not isinstance(cameras, (list, tuple)):
            return None
        for index, information in enumerate(cameras):
            if isinstance(information, dict) and any(
                "imx708" in str(value).lower() for value in information.values()
            ):
                return index
        return None

    @staticmethod
    def _load_stack() -> tuple[Any, Any, tuple[str, str]] | CameraAvailability:
        try:
            module = importlib.import_module("picamera2")
            libcamera = importlib.import_module("libcamera")
            picamera_class = module.Picamera2
        except Exception:
            return CameraAvailability(
                False,
                CameraCode.DEPENDENCY_UNAVAILABLE,
                CAMERA_MESSAGES[CameraCode.DEPENDENCY_UNAVAILABLE],
                "unknown",
                "unknown",
            )
        try:
            package_version: object = importlib.metadata.version("picamera2")
        except Exception:
            package_version = getattr(module, "__version__", None)
        versions = (
            sanitize_version(package_version),
            sanitize_version(getattr(libcamera, "__version__", None)),
        )
        return picamera_class, libcamera, versions

    @staticmethod
    def _unavailable(code: CameraCode, versions: tuple[str, str]) -> CameraAvailability:
        return CameraAvailability(
            False,
            code,
            CAMERA_MESSAGES[code],
            versions[0],
            versions[1],
        )


class Picamera2PreviewSession:
    """One preview-owned Picamera2 instance that also captures the still."""

    def __init__(self, adapter: Picamera2Camera) -> None:
        self._adapter = adapter
        self._camera: Any | None = None
        self._start_attempted = False

    def start(self) -> bool:
        loaded = self._adapter._load_stack()
        if isinstance(loaded, CameraAvailability):
            return False
        picamera_class, _libcamera, _versions = loaded
        if not self._adapter._has_required_api(picamera_class) or not all(
            hasattr(picamera_class, name) for name in _PREVIEW_METHODS
        ):
            return False
        try:
            cameras = picamera_class.global_camera_info()
            camera_index = self._adapter._compatible_index(cameras)
            if camera_index is None:
                return False
            camera = picamera_class(camera_index)
            self._camera = camera
            configuration = camera.create_preview_configuration(
                main={"size": (640, 360), "format": "BGR888"},
                buffer_count=4,
                queue=False,
                display=None,
                encode=None,
            )
            camera.configure(configuration)
            self._start_attempted = True
            camera.start()
            return True
        except BaseException as exc:
            with suppress(BaseException):
                self.close()
            if not isinstance(exc, Exception):
                raise
            return False

    def read_frame(self) -> PreviewFrame | None:
        camera = self._camera
        if camera is None:
            return None
        try:
            frame = camera.capture_array("main")
            return self._frame_from_array(frame)
        except BaseException as exc:
            with suppress(BaseException):
                self.close()
            if not isinstance(exc, Exception):
                raise
            return None

    def capture(self, output_path: Path, overwrite: bool = False) -> CaptureResult:
        if self._camera is None:
            return self._adapter._failure(CameraCode.CAMERA_UNAVAILABLE)
        result = self._adapter.capture_using(
            output_path,
            overwrite=overwrite,
            staging_writer=self._capture_still,
        )
        return result

    def _capture_still(self, staging: Path) -> None:
        camera = self._camera
        if camera is None:
            raise CaptureFailure(CameraCode.CAMERA_UNAVAILABLE)
        self._adapter._autofocus(camera)
        try:
            configuration = camera.create_still_configuration(
                main={"size": (1920, 1080)}
            )
            camera.switch_mode_and_capture_file(
                configuration,
                str(staging),
                format="jpeg",
            )
        except Exception as exc:
            raise CaptureFailure(CameraCode.CAPTURE_FAILED) from exc
        self._adapter._sync_path_capture(staging)

    def close(self) -> bool:
        camera = self._camera
        self._camera = None
        if camera is None:
            return True
        failed = False
        cancellation: BaseException | None = None
        try:
            if self._start_attempted:
                try:
                    camera.stop()
                except BaseException as exc:
                    if isinstance(exc, Exception):
                        failed = True
                    else:
                        cancellation = exc
        finally:
            try:
                camera.close()
            except BaseException as exc:
                if isinstance(exc, Exception):
                    failed = True
                elif cancellation is None:
                    cancellation = exc
        self._start_attempted = False
        if cancellation is not None:
            raise cancellation
        return not failed

    @staticmethod
    def _frame_from_array(frame: Any) -> PreviewFrame | None:
        if (
            getattr(frame, "shape", None) != (360, 640, 3)
            or str(getattr(frame, "dtype", "")) != "uint8"
        ):
            return None
        try:
            rgb_bytes = bytes(frame.tobytes())
        except Exception:
            return None
        if len(rgb_bytes) != 640 * 360 * 3:
            return None
        # Picamera2 BGR888 is already byte-ordered for the RGB display contract.
        return PreviewFrame(640, 360, rgb_bytes)
