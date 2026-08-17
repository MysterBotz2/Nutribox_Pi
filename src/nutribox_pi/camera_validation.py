"""Bounded image and output validation for PI-1B camera adapters."""

from __future__ import annotations

import os
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path

MAX_JPEG_BYTES = 20 * 1024 * 1024
MAX_HEADER_BYTES = 1024 * 1024
MAX_MARKERS = 512
JPEG_WIDTH = 1920
JPEG_HEIGHT = 1080
SOF_MARKERS = {
    0xC0,
    0xC1,
    0xC2,
    0xC3,
    0xC5,
    0xC6,
    0xC7,
    0xC9,
    0xCA,
    0xCB,
    0xCD,
    0xCE,
    0xCF,
}


class CameraValidationError(ValueError):
    """A normalized local camera validation failure."""


@dataclass(frozen=True, slots=True)
class JpegInformation:
    width: int
    height: int
    byte_size: int


def validate_output_path(output_path: Path, overwrite: bool) -> Path:
    raw_parts = output_path.parts
    if not raw_parts or any(
        unicodedata.category(char) in {"Cc", "Cf"}
        for part in raw_parts
        for char in part
    ):
        raise CameraValidationError
    if output_path.suffix.lower() not in {".jpg", ".jpeg"}:
        raise CameraValidationError

    absolute = Path(os.path.abspath(output_path))
    parent = absolute.parent
    if not parent.is_dir() or not os.access(parent, os.W_OK):
        raise CameraValidationError

    current = Path(absolute.anchor)
    for part in absolute.parts[1:-1]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise CameraValidationError from exc
        if stat.S_ISLNK(mode):
            raise CameraValidationError

    try:
        destination_mode = absolute.lstat().st_mode
    except FileNotFoundError:
        return absolute
    except OSError as exc:
        raise CameraValidationError from exc
    if stat.S_ISLNK(destination_mode) or not stat.S_ISREG(destination_mode):
        raise CameraValidationError
    if not overwrite:
        raise FileExistsError
    return absolute


def inspect_jpeg(path: Path) -> JpegInformation:
    try:
        size = path.stat().st_size
        if size <= 0 or size > MAX_JPEG_BYTES:
            raise CameraValidationError
        with path.open("rb") as image:
            if image.read(2) != b"\xff\xd8":
                raise CameraValidationError
            marker_count = 0
            scanned = 2
            dimensions: tuple[int, int] | None = None
            while scanned < min(size, MAX_HEADER_BYTES):
                byte = image.read(1)
                scanned += len(byte)
                if not byte:
                    break
                if byte != b"\xff":
                    continue
                while True:
                    marker_raw = image.read(1)
                    scanned += len(marker_raw)
                    if not marker_raw:
                        raise CameraValidationError
                    if marker_raw != b"\xff":
                        break
                marker = marker_raw[0]
                if marker in {0x00, 0x01, 0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
                    continue
                marker_count += 1
                if marker_count > MAX_MARKERS:
                    raise CameraValidationError
                length_raw = image.read(2)
                scanned += len(length_raw)
                if len(length_raw) != 2:
                    raise CameraValidationError
                segment_length = int.from_bytes(length_raw, "big")
                if segment_length < 2 or scanned + segment_length - 2 > size:
                    raise CameraValidationError
                if marker in SOF_MARKERS:
                    payload = image.read(5)
                    scanned += len(payload)
                    if len(payload) != 5 or segment_length < 7:
                        raise CameraValidationError
                    dimensions = (
                        int.from_bytes(payload[3:5], "big"),
                        int.from_bytes(payload[1:3], "big"),
                    )
                    break
                image.seek(segment_length - 2, os.SEEK_CUR)
                scanned += segment_length - 2
            if dimensions != (JPEG_WIDTH, JPEG_HEIGHT):
                raise CameraValidationError
            image.seek(-2, os.SEEK_END)
            if image.read(2) != b"\xff\xd9":
                raise CameraValidationError
    except CameraValidationError:
        raise
    except OSError as exc:
        raise CameraValidationError from exc
    return JpegInformation(JPEG_WIDTH, JPEG_HEIGHT, size)
