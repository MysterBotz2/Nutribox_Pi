"""Environment-backed PI-0 configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass

from nutribox_pi.validation import (
    validate_api_base_url,
    validate_temperature,
    validate_timeout,
    validate_weight,
)


class ConfigurationError(ValueError):
    """Raised when PI-0 configuration is invalid."""


class CameraConfigurationError(ValueError):
    """Raised when camera-only configuration is invalid."""


@dataclass(frozen=True, slots=True)
class CameraSettings:
    adapter: str

    def __post_init__(self) -> None:
        if self.adapter not in {"simulated", "picamera2"}:
            raise CameraConfigurationError("camera adapter is invalid")

    @classmethod
    def from_env(cls) -> CameraSettings:
        adapter = os.getenv("NUTRIBOX_CAMERA_ADAPTER")
        if not adapter:
            raise CameraConfigurationError("camera adapter is required")
        return cls(adapter=adapter)


@dataclass(frozen=True, slots=True)
class Settings:
    api_base_url: str
    http_timeout_seconds: float = 10.0
    simulated_weight_grams: float = 250.0
    simulated_temperature_c: float = 25.0

    def __post_init__(self) -> None:
        try:
            normalized_url = validate_api_base_url(self.api_base_url)
            object.__setattr__(self, "api_base_url", normalized_url)
            validate_timeout(self.http_timeout_seconds)
            validate_weight(self.simulated_weight_grams)
            validate_temperature(self.simulated_temperature_c)
        except ValueError as exc:
            raise ConfigurationError(str(exc)) from exc

    @classmethod
    def from_env(cls) -> Settings:
        api_base_url = os.getenv("NUTRIBOX_API_BASE_URL")
        if not api_base_url:
            raise ConfigurationError("NUTRIBOX_API_BASE_URL is required")
        return cls(
            api_base_url=api_base_url,
            http_timeout_seconds=_float_env(
                "NUTRIBOX_HTTP_TIMEOUT_SECONDS", 10.0
            ),
            simulated_weight_grams=_float_env(
                "NUTRIBOX_SIMULATED_WEIGHT_GRAMS", 250.0
            ),
            simulated_temperature_c=_float_env(
                "NUTRIBOX_SIMULATED_TEMPERATURE_C", 25.0
            ),
        )


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be numeric") from exc
