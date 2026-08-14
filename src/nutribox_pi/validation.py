"""Validation shared by configuration, adapters, and application boundaries."""

from __future__ import annotations

import math
from urllib.parse import urlsplit


def validate_api_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("API base URL must have an HTTP(S) scheme and host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("API base URL must not contain credentials")
    return value.rstrip("/")


def validate_timeout(value: float) -> float:
    if not math.isfinite(value) or value <= 0:
        raise ValueError("HTTP timeout must be finite and greater than zero")
    return value


def validate_weight(value: float) -> float:
    if not math.isfinite(value) or not 0 <= value <= 5000:
        raise ValueError("weight must be finite and between 0 and 5000 grams")
    return value


def validate_temperature(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("temperature must be finite")
    return value
