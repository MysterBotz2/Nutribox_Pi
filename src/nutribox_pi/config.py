"""Environment-backed PI-0 configuration."""

from __future__ import annotations

import math
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


class WeightConfigurationError(ValueError):
    """Raised when weight-only configuration is invalid."""


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
class WeightSettings:
    """Weight source selection independent of backend configuration."""

    adapter: str
    simulated_grams: float = 250.0
    data_pin: int | None = None
    clock_pin: int | None = None
    sample_count: int = 5
    stability_tolerance_grams: float = 2.0
    negative_noise_clamp_grams: float = 2.0

    def __post_init__(self) -> None:
        if self.adapter not in {"simulated", "hx711"}:
            raise WeightConfigurationError("weight adapter is invalid")
        try:
            validate_weight(self.simulated_grams)
        except ValueError as exc:
            raise WeightConfigurationError(str(exc)) from exc
        if self.adapter == "hx711":
            if (
                self.data_pin is None
                or self.clock_pin is None
                or not 0 <= self.data_pin <= 27
                or not 0 <= self.clock_pin <= 27
                or self.data_pin == self.clock_pin
            ):
                raise WeightConfigurationError("HX711 BCM pins are invalid")
            if not 1 <= self.sample_count <= 50:
                raise WeightConfigurationError("HX711 sample count is invalid")
            if (
                not math.isfinite(self.stability_tolerance_grams)
                or not math.isfinite(self.negative_noise_clamp_grams)
                or self.stability_tolerance_grams < 0
                or self.negative_noise_clamp_grams < 0
            ):
                raise WeightConfigurationError("HX711 tolerances are invalid")

    @classmethod
    def from_env(cls) -> WeightSettings:
        adapter = os.getenv("NUTRIBOX_WEIGHT_ADAPTER")
        if not adapter:
            raise WeightConfigurationError("NUTRIBOX_WEIGHT_ADAPTER is required")
        values: dict[str, object] = {
            "adapter": adapter,
            "simulated_grams": _float_env("NUTRIBOX_SIMULATED_WEIGHT_GRAMS", 250.0),
        }
        if adapter == "hx711":
            values.update(
                data_pin=_int_env("NUTRIBOX_HX711_DATA_BCM"),
                clock_pin=_int_env("NUTRIBOX_HX711_CLOCK_BCM"),
                sample_count=_int_env("NUTRIBOX_HX711_SAMPLE_COUNT", 5),
                stability_tolerance_grams=_float_env(
                    "NUTRIBOX_HX711_STABILITY_TOLERANCE_GRAMS", 2.0
                ),
                negative_noise_clamp_grams=_float_env(
                    "NUTRIBOX_HX711_NEGATIVE_NOISE_CLAMP_GRAMS", 2.0
                ),
            )
        return cls(**values)  # type: ignore[arg-type]


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
            http_timeout_seconds=_float_env("NUTRIBOX_HTTP_TIMEOUT_SECONDS", 10.0),
            simulated_weight_grams=_float_env("NUTRIBOX_SIMULATED_WEIGHT_GRAMS", 250.0),
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


def _int_env(name: str, default: int | None = None) -> int | None:
    raw = os.getenv(name)
    if raw is None:
        if default is None:
            raise WeightConfigurationError(f"{name} is required")
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise WeightConfigurationError(f"{name} must be an integer") from exc
