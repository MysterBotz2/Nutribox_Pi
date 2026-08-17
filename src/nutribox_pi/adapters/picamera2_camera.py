"""Lazy Raspberry Pi Camera Module 3 adapter."""

from __future__ import annotations

import errno
import importlib
import importlib.metadata
import os
import re
import time
from pathlib import Path
from typing import Any

from nutribox_pi.adapters.camera_base import (
    CAMERA_CLEANUP,
    CaptureFailure,
    SafeCameraAdapter,
)
from nutribox_pi.models import CAMERA_MESSAGES, CameraAvailability, CameraCode

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
            return self._unavailable(
                CameraCode.CAMERA_INITIALIZATION_FAILED, versions
            )
        if self._compatible_index(cameras) is None:
            return self._unavailable(CameraCode.CAMERA_UNAVAILABLE, versions)
        return CameraAvailability(
            True,
            CameraCode.OK,
            "Camera is available.",
            versions[0],
            versions[1],
        )

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
                raise CaptureFailure(
                    CameraCode.CAMERA_INITIALIZATION_FAILED
                ) from exc

            self._autofocus(camera)
            try:
                camera.capture_file(str(staging))
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
    def _load_stack() -> (
        tuple[Any, Any, tuple[str, str]] | CameraAvailability
    ):
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
    def _unavailable(
        code: CameraCode, versions: tuple[str, str]
    ) -> CameraAvailability:
        return CameraAvailability(
            False,
            code,
            CAMERA_MESSAGES[code],
            versions[0],
            versions[1],
        )
