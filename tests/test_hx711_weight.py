"""Deterministic HX711 behavior without GPIO, hardware, or time delays."""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

import pytest

from nutribox_pi import cli
from nutribox_pi.adapters.hx711_weight import (
    HX711WeightSensor,
    WeightCalibration,
    WeightCalibrationStore,
    WeightSensorUnavailable,
)
from nutribox_pi.adapters.mock_hardware import SimulatedTemperatureSensor
from nutribox_pi.adapters.simulated_camera import SimulatedCamera
from nutribox_pi.config import WeightConfigurationError, WeightSettings
from nutribox_pi.controller import NutriBoxController
from nutribox_pi.device_ui import MealCaptureWorkflow, TemporaryCaptureStore
from nutribox_pi.weight_factory import weight_from_env


class _Driver:
    def __init__(self, weights: list[float], *, offset: float = 10, raw: float = 210):
        self.weights = iter(weights)
        self.offset = offset
        self.raw = raw
        self.tared = False
        self.scale: float | None = None

    def set_offset(self, offset: float) -> None:
        self.offset = offset

    def set_scale(self, factor: float) -> None:
        self.scale = factor

    def get_weight_mean(self, *, readings: int) -> float:
        assert readings == 1
        return next(self.weights)

    def tare(self) -> None:
        self.tared = True
        self.offset = 25

    def get_offset(self) -> float:
        return self.offset

    def get_raw_data_mean(self, *, readings: int) -> float:
        assert readings == 5
        return self.raw


def _sensor(
    tmp_path: Path, weights: list[float], *, store: WeightCalibrationStore | None = None
) -> tuple[HX711WeightSensor, _Driver, WeightCalibrationStore]:
    calibration_store = store or WeightCalibrationStore(tmp_path)
    calibration_store.save(WeightCalibration(10, 2))
    driver = _Driver(weights)
    return (
        HX711WeightSensor(
            5,
            6,
            calibration_store=calibration_store,
            driver_factory=lambda *_: driver,
        ),
        driver,
        calibration_store,
    )


def test_hx711_reads_bounded_stable_measurement(tmp_path: Path) -> None:
    sensor, driver, _ = _sensor(tmp_path, [250, 251, 249, 250, 250])

    assert sensor.read_grams() == 250
    assert driver.scale == 2


@pytest.mark.parametrize(
    "weights", [[250, 255, 250, 250, 250], [5001] * 5, [math.nan] * 5]
)
def test_hx711_rejects_unstable_invalid_or_out_of_range_measurement(
    tmp_path: Path, weights: list[float]
) -> None:
    sensor, _, _ = _sensor(tmp_path, weights)

    with pytest.raises(WeightSensorUnavailable, match="Weight sensor unavailable"):
        sensor.read_grams()


def test_hx711_clamps_small_negative_noise_only(tmp_path: Path) -> None:
    sensor, _, _ = _sensor(tmp_path, [-1] * 5)
    assert sensor.read_grams() == 0

    sensor, _, _ = _sensor(tmp_path, [-3] * 5)
    with pytest.raises(WeightSensorUnavailable):
        sensor.read_grams()


def test_capture_freezes_the_stable_hx711_measurement(tmp_path: Path) -> None:
    sensor, _, _ = _sensor(tmp_path, [321, 320, 321, 320, 321])
    directory = tmp_path / "capture"
    store = TemporaryCaptureStore(
        directory_factory=lambda **_: str(directory.mkdir(mode=0o700) or directory)
    )
    controller = NutriBoxController(
        backend=object(),  # Capture freezes weight without constructing a request.
        weight_sensor=sensor,
        temperature_sensor=SimulatedTemperatureSensor(),
    )
    workflow = MealCaptureWorkflow(SimulatedCamera(), controller, store)

    workflow.analyze()
    workflow.begin_capture()
    workflow.perform_capture()

    assert workflow.captured_weight_grams == 320.6


def test_hx711_tare_and_known_weight_calibration_persist_only_calibration(
    tmp_path: Path,
) -> None:
    store = WeightCalibrationStore(tmp_path)
    store.save(WeightCalibration(10, 2))
    driver = _Driver([1] * 5, offset=10, raw=225)
    sensor = HX711WeightSensor(
        5, 6, calibration_store=store, driver_factory=lambda *_: driver
    )

    sensor.tare()
    assert driver.tared
    assert store.load() == WeightCalibration(25, 2)
    sensor.calibrate(100)

    assert store.load() == WeightCalibration(25, 2)
    payload = json.loads(
        (tmp_path / "nutribox-pi" / "weight-calibration.json").read_text()
    )
    assert payload == {"schema_version": 1, "offset": 25.0, "factor": 2.0}


@pytest.mark.skipif(
    os.name != "posix", reason="POSIX permissions are platform-specific"
)
def test_calibration_storage_is_private_and_atomic(tmp_path: Path) -> None:
    store = WeightCalibrationStore(tmp_path)
    store.save(WeightCalibration(10, 2))
    path = tmp_path / "nutribox-pi" / "weight-calibration.json"

    assert (path.parent.stat().st_mode & 0o777) == 0o700
    assert (path.stat().st_mode & 0o777) == 0o600
    assert not list(path.parent.glob(".weight-calibration-*"))


def test_missing_or_invalid_calibration_is_safe(tmp_path: Path) -> None:
    sensor = HX711WeightSensor(5, 6, calibration_store=WeightCalibrationStore(tmp_path))
    with pytest.raises(WeightSensorUnavailable, match="Weight sensor unavailable"):
        sensor.read_grams()


def test_weight_configuration_requires_explicit_adapter_and_hx711_pins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NUTRIBOX_WEIGHT_ADAPTER", raising=False)
    with pytest.raises(WeightConfigurationError, match="required"):
        WeightSettings.from_env()
    monkeypatch.setenv("NUTRIBOX_WEIGHT_ADAPTER", "hx711")
    with pytest.raises(WeightConfigurationError, match="DATA_BCM"):
        WeightSettings.from_env()


def test_simulated_weight_requires_explicit_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NUTRIBOX_WEIGHT_ADAPTER", "simulated")
    monkeypatch.setenv("NUTRIBOX_SIMULATED_WEIGHT_GRAMS", "321.5")
    sensor = weight_from_env()

    assert sensor.read_grams() == 321.5
    assert sensor.is_simulated is True


def test_hx711_module_import_does_not_import_gpio_or_driver() -> None:
    sys.modules.pop("hx711", None)
    sys.modules.pop("RPi.GPIO", None)

    __import__("nutribox_pi.adapters.hx711_weight")

    assert "hx711" not in sys.modules
    assert "RPi.GPIO" not in sys.modules


def test_weight_cli_operations_are_safe_and_do_not_need_backend(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    sensor = _Driver([333] * 5)
    adapter = HX711WeightSensor(
        5,
        6,
        calibration_store=WeightCalibrationStore(tmp_path),
        driver_factory=lambda *_: sensor,
    )
    monkeypatch.setattr(cli, "weight_from_env", lambda: adapter)
    monkeypatch.setattr(adapter._store, "load", lambda: WeightCalibration(10, 2))
    monkeypatch.setattr(adapter._store, "save", lambda _: None)

    assert cli.main(["weight-check"]) == 0
    assert capsys.readouterr().out == "Weight: 333 g\n"
    assert cli.main(["weight-tare"]) == 0
    assert cli.main(["weight-calibrate", "--known-grams", "100"]) == 0


def test_weight_cli_normalizes_unavailable_sensor(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "weight_from_env", lambda: object())

    assert cli.main(["weight-check"]) == 1
    assert capsys.readouterr().err == "Weight sensor unavailable.\n"
