"""Shared safe capture, validation, and publication behavior."""

from __future__ import annotations

import errno
import os
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from nutribox_pi.camera_validation import (
    CameraValidationError,
    JpegInformation,
    inspect_jpeg,
    validate_output_path,
)
from nutribox_pi.models import CAMERA_MESSAGES, CameraCode, CaptureResult

PRIVATE_CLEANUP = "Private temporary cleanup failed."
PUBLISHED_CLEANUP = "Image was published, but private temporary cleanup failed."
CAMERA_CLEANUP = "Camera resource cleanup failed."
COMBINED_CLEANUP = "Camera and private temporary cleanup failed."


class CaptureFailure(Exception):
    def __init__(self, code: CameraCode, message: str | None = None) -> None:
        self.code = code
        self.safe_message = message or CAMERA_MESSAGES[code]
        super().__init__(self.safe_message)


class SafeCameraAdapter(ABC):
    @abstractmethod
    def _capture_to_staging(self, staging: Path) -> None:
        """Write, sync, close, and release camera resources."""

    def capture(self, output_path: Path, overwrite: bool = False) -> CaptureResult:
        return self.capture_using(
            output_path,
            overwrite=overwrite,
            staging_writer=self._capture_to_staging,
        )

    def capture_using(
        self,
        output_path: Path,
        *,
        overwrite: bool,
        staging_writer: Callable[[Path], None],
    ) -> CaptureResult:
        """Publish one capture written by an adapter-owned camera session."""
        try:
            destination = validate_output_path(Path(output_path), overwrite)
        except FileExistsError:
            return self._failure(CameraCode.OUTPUT_EXISTS)
        except (CameraValidationError, TypeError, ValueError):
            return self._failure(CameraCode.INVALID_OUTPUT)

        staging: Path | None = None
        published = False
        information: JpegInformation | None = None
        primary: CaptureFailure | None = None
        try:
            try:
                descriptor, staging_name = tempfile.mkstemp(
                    prefix=".nutribox-camera-",
                    suffix=".tmp",
                    dir=destination.parent,
                )
                staging = Path(staging_name)
                try:
                    self._close_staging_descriptor(descriptor)
                except OSError as exc:
                    primary = CaptureFailure(CameraCode.PUBLICATION_FAILED)
                    primary.__cause__ = exc
                    with suppress(OSError):
                        self._close_staging_descriptor(descriptor)
                if os.name == "posix":
                    os.chmod(staging, 0o600)
            except OSError as exc:
                primary = CaptureFailure(CameraCode.CAPTURE_FAILED)
                primary.__cause__ = exc

            if primary is None and staging is not None:
                try:
                    staging_writer(staging)
                except CaptureFailure as exc:
                    primary = exc
                except Exception as exc:
                    primary = CaptureFailure(CameraCode.CAPTURE_FAILED)
                    primary.__cause__ = exc

            if primary is None:
                try:
                    information = inspect_jpeg(staging)
                except CameraValidationError:
                    primary = CaptureFailure(CameraCode.INVALID_IMAGE)

            if primary is None:
                try:
                    if overwrite:
                        os.replace(staging, destination)
                        staging = None
                    else:
                        os.link(staging, destination, follow_symlinks=False)
                        published = True
                        cleanup_failed = not self._unlink_twice(staging)
                        staging = None
                        if cleanup_failed:
                            return self._published_cleanup_failure(
                                destination, information
                            )
                    published = True
                except FileExistsError:
                    primary = CaptureFailure(CameraCode.OUTPUT_EXISTS)
                except OSError as exc:
                    code = (
                        CameraCode.OUTPUT_EXISTS
                        if exc.errno == errno.EEXIST
                        else CameraCode.PUBLICATION_FAILED
                    )
                    primary = CaptureFailure(code)

            if primary is None and information is not None:
                return CaptureResult(
                    ok=True,
                    code=CameraCode.OK,
                    message="Image captured.",
                    published=True,
                    output_path=destination,
                    format="jpeg",
                    width=information.width,
                    height=information.height,
                    byte_size=information.byte_size,
                )
        finally:
            if staging is not None:
                cleanup_ok = self._unlink_twice(staging)
                if not cleanup_ok and not published:
                    message = (
                        COMBINED_CLEANUP
                        if primary is not None
                        and primary.safe_message == CAMERA_CLEANUP
                        else PRIVATE_CLEANUP
                    )
                    primary = CaptureFailure(CameraCode.CLEANUP_FAILED, message)

        return self._failure(
            primary.code if primary else CameraCode.CAPTURE_FAILED,
            primary.safe_message if primary else None,
        )

    @staticmethod
    def _close_staging_descriptor(descriptor: int) -> None:
        os.close(descriptor)

    @staticmethod
    def _unlink_twice(path: Path) -> bool:
        for _ in range(2):
            try:
                path.unlink()
                return True
            except FileNotFoundError:
                return True
            except OSError:
                continue
        return False

    @staticmethod
    def _failure(code: CameraCode, message: str | None = None) -> CaptureResult:
        return CaptureResult(
            False,
            code,
            message or CAMERA_MESSAGES[code],
            False,
            None,
            None,
            None,
            None,
            None,
        )

    @staticmethod
    def _published_cleanup_failure(
        destination: Path, information: JpegInformation | None
    ) -> CaptureResult:
        assert information is not None
        return CaptureResult(
            False,
            CameraCode.CLEANUP_FAILED,
            PUBLISHED_CLEANUP,
            True,
            destination,
            "jpeg",
            information.width,
            information.height,
            information.byte_size,
        )
