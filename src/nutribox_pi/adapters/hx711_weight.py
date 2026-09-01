"""Lazy, replaceable HX711 weight adapter with private calibration storage."""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nutribox_pi.validation import validate_weight

CALIBRATION_SCHEMA_VERSION = 2
UNAVAILABLE_MESSAGE = "Weight sensor unavailable."


class WeightSensorUnavailable(RuntimeError):
    """A normalized weight-source failure safe for terminal and UI output."""

    def __init__(self) -> None:
        super().__init__(UNAVAILABLE_MESSAGE)


@dataclass(frozen=True, slots=True)
class WeightCalibration:
    offset: float
    factor: float | None
    schema_version: int = CALIBRATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            self.schema_version != CALIBRATION_SCHEMA_VERSION
            or not math.isfinite(self.offset)
            or (
                self.factor is not None
                and (not math.isfinite(self.factor) or self.factor == 0)
            )
        ):
            raise ValueError("weight calibration is invalid")


class WeightCalibrationStore:
    """Stores only HX711 calibration values using private atomic publication."""

    def __init__(self, root: Path | None = None) -> None:
        base = root or Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
        self._directory = base / "nutribox-pi"
        self._path = self._directory / "weight-calibration.json"

    def load(self) -> WeightCalibration | None:
        try:
            if not self._path.exists():
                return None
            if self._path.is_symlink() or not self._path.is_file():
                raise OSError
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            if set(payload) != {"schema_version", "offset", "factor"}:
                raise ValueError
            schema_version = payload["schema_version"]
            if schema_version not in {1, CALIBRATION_SCHEMA_VERSION}:
                raise ValueError
            factor = payload["factor"]
            if schema_version == 1 and factor is None:
                raise ValueError
            return WeightCalibration(
                schema_version=CALIBRATION_SCHEMA_VERSION,
                offset=float(payload["offset"]),
                factor=None if factor is None else float(factor),
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise WeightSensorUnavailable() from exc

    def save(self, calibration: WeightCalibration) -> None:
        try:
            self._directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            if self._directory.is_symlink() or not self._directory.is_dir():
                raise OSError
            if os.name == "posix":
                os.chmod(self._directory, 0o700)
            descriptor, temporary = tempfile.mkstemp(
                prefix=".weight-calibration-", dir=self._directory
            )
            try:
                if os.name == "posix":
                    os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump(
                        {
                            "schema_version": calibration.schema_version,
                            "offset": calibration.offset,
                            "factor": calibration.factor,
                        },
                        stream,
                    )
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self._path)
            finally:
                Path(temporary).unlink(missing_ok=True)
        except OSError as exc:
            raise WeightSensorUnavailable() from exc


class HX711WeightSensor:
    """Reads a bounded stable HX711 sample; GPIO is imported only on first use."""

    is_simulated = False

    def __init__(
        self,
        data_pin: int,
        clock_pin: int,
        *,
        calibration_store: WeightCalibrationStore | None = None,
        sample_count: int = 5,
        stability_tolerance_grams: float = 2.0,
        negative_noise_clamp_grams: float = 2.0,
        driver_factory: Callable[[int, int], Any] | None = None,
    ) -> None:
        if (
            not 0 <= data_pin <= 27
            or not 0 <= clock_pin <= 27
            or data_pin == clock_pin
            or not 1 <= sample_count <= 50
            or stability_tolerance_grams < 0
            or negative_noise_clamp_grams < 0
        ):
            raise ValueError("HX711 configuration is invalid")
        self._data_pin = data_pin
        self._clock_pin = clock_pin
        self._store = calibration_store or WeightCalibrationStore()
        self._sample_count = sample_count
        self._stability_tolerance = stability_tolerance_grams
        self._negative_noise_clamp = negative_noise_clamp_grams
        self._driver_factory = driver_factory
        self._driver: Any | None = None

    def read_grams(self) -> float:
        calibration = self._store.load()
        if calibration is None or calibration.factor is None:
            raise WeightSensorUnavailable()
        try:
            driver = self._driver_instance()
            driver.set_offset(calibration.offset)
            driver.set_scale(calibration.factor)
            samples = tuple(
                self._single_sample(driver) for _ in range(self._sample_count)
            )
            if max(samples) - min(samples) > self._stability_tolerance:
                raise WeightSensorUnavailable()
            grams = sum(samples) / len(samples)
            if -self._negative_noise_clamp <= grams < 0:
                grams = 0.0
            return validate_weight(grams)
        except WeightSensorUnavailable:
            raise
        except (ArithmeticError, AttributeError, OSError, TypeError, ValueError) as exc:
            raise WeightSensorUnavailable() from exc

    def tare(self) -> None:
        try:
            driver = self._driver_instance()
            driver.tare()
            offset = float(driver.get_offset())
            if not math.isfinite(offset):
                raise ValueError
            existing = self._store.load()
            self._store.save(
                WeightCalibration(offset, existing.factor if existing else None)
            )
        except WeightSensorUnavailable:
            raise
        except (AttributeError, OSError, TypeError, ValueError) as exc:
            raise WeightSensorUnavailable() from exc

    def calibrate(self, known_grams: float) -> None:
        if (
            isinstance(known_grams, bool)
            or not isinstance(known_grams, (int, float))
            or not math.isfinite(known_grams)
            or not 0 < known_grams <= 5000
        ):
            raise WeightSensorUnavailable()
        try:
            driver = self._driver_instance()
            existing = self._store.load()
            if existing is None:
                raise WeightSensorUnavailable()
            offset = existing.offset
            driver.set_offset(offset)
            raw = float(driver.get_raw_data_mean(readings=self._sample_count))
            factor = (raw - offset) / known_grams
            calibration = WeightCalibration(offset, factor)
            driver.set_scale(calibration.factor)
            self._store.save(calibration)
        except WeightSensorUnavailable:
            raise
        except (AttributeError, OSError, TypeError, ValueError) as exc:
            raise WeightSensorUnavailable() from exc

    def close(self) -> None:
        driver = self._driver
        if driver is None:
            return
        self._driver = None
        try:
            close = getattr(driver, "close", None)
            if callable(close):
                close()
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            raise WeightSensorUnavailable() from exc

    def _driver_instance(self) -> Any:
        if self._driver is None:
            factory = self._driver_factory or _load_driver
            self._driver = factory(self._data_pin, self._clock_pin)
        return self._driver

    @staticmethod
    def _single_sample(driver: Any) -> float:
        value = float(driver.get_weight_mean(readings=1))
        if not math.isfinite(value):
            raise WeightSensorUnavailable()
        return value


def _load_driver(data_pin: int, clock_pin: int) -> Any:
    """Create the private RPi.GPIO driver only when HX711 hardware is used."""
    try:
        return _RPiGPIOHX711Driver(data_pin, clock_pin)
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise WeightSensorUnavailable() from exc


class _RPiGPIOHX711Driver:
    """Small HX711 channel-A/gain-128 driver using only its assigned BCM pins."""

    def __init__(
        self, data_pin: int, clock_pin: int, *, ready_timeout_seconds: float = 0.2
    ) -> None:
        import RPi.GPIO as gpio  # type: ignore[import-not-found]

        self._gpio = gpio
        self._data_pin = data_pin
        self._clock_pin = clock_pin
        self._ready_timeout = ready_timeout_seconds
        self._offset = 0.0
        self._scale: float | None = None
        gpio.setmode(gpio.BCM)
        gpio.setup(data_pin, gpio.IN)
        gpio.setup(clock_pin, gpio.OUT, initial=gpio.LOW)
        gpio.output(clock_pin, gpio.LOW)

    def set_offset(self, offset: float) -> None:
        self._offset = float(offset)

    def get_offset(self) -> float:
        return self._offset

    def set_scale(self, factor: float) -> None:
        factor = float(factor)
        if not math.isfinite(factor) or factor == 0:
            raise ValueError
        self._scale = factor

    def get_raw_data_mean(self, *, readings: int) -> float:
        if not 1 <= readings <= 50:
            raise ValueError
        samples = [self._read_raw() for _ in range(readings)]
        return sum(samples) / len(samples)

    def tare(self) -> None:
        self._offset = self.get_raw_data_mean(readings=5)

    def get_weight_mean(self, *, readings: int) -> float:
        if self._scale is None:
            raise ValueError
        return (self.get_raw_data_mean(readings=readings) - self._offset) / self._scale

    def close(self) -> None:
        try:
            self._gpio.output(self._clock_pin, self._gpio.LOW)
            try:
                self._gpio.cleanup((self._data_pin, self._clock_pin))
            except TypeError:
                self._gpio.cleanup(self._data_pin)
                self._gpio.cleanup(self._clock_pin)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise WeightSensorUnavailable() from exc

    def _read_raw(self) -> int:
        deadline = time.monotonic() + self._ready_timeout
        while self._gpio.input(self._data_pin):
            if time.monotonic() >= deadline:
                raise WeightSensorUnavailable()
            time.sleep(0.001)
        value = 0
        for _ in range(24):
            self._gpio.output(self._clock_pin, self._gpio.HIGH)
            value = (value << 1) | int(bool(self._gpio.input(self._data_pin)))
            self._gpio.output(self._clock_pin, self._gpio.LOW)
        # The 25th pulse selects channel A at gain 128 for the next conversion.
        self._gpio.output(self._clock_pin, self._gpio.HIGH)
        self._gpio.output(self._clock_pin, self._gpio.LOW)
        return value - (1 << 24) if value & (1 << 23) else value
