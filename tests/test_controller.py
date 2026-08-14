import math
from pathlib import Path

import pytest

from nutribox_pi.adapters.mock_hardware import (
    SimulatedTemperatureSensor,
    SimulatedWeightSensor,
)
from nutribox_pi.controller import NutriBoxController
from nutribox_pi.models import AnalysisResult, AnalysisStatus, HealthResult


class RecordingBackend:
    def __init__(self) -> None:
        self.analysis_call: tuple[Path, float] | None = None

    def health(self) -> HealthResult:
        return HealthResult(healthy=True, payload={})

    def analyze_meal(self, image_path: Path, weight_grams: float) -> AnalysisResult:
        self.analysis_call = image_path, weight_grams
        return AnalysisResult(AnalysisStatus.CALCULATED, {"status": "calculated"})


class ArbitraryWeightSensor:
    def __init__(self, value: float) -> None:
        self.value = value

    def read_grams(self) -> float:
        return self.value


class ArbitraryTemperatureSensor:
    def __init__(self, value: float) -> None:
        self.value = value

    def read_celsius(self) -> float:
        return self.value


def test_controller_uses_simulated_measurements() -> None:
    backend = RecordingBackend()
    controller = NutriBoxController(
        backend,
        SimulatedWeightSensor(321.5),
        SimulatedTemperatureSensor(26.25),
    )

    result = controller.analyze_meal(Path("meal.jpg"))

    assert result.status is AnalysisStatus.CALCULATED
    assert backend.analysis_call == (Path("meal.jpg"), 321.5)
    assert controller.current_temperature_c() == 26.25


@pytest.mark.parametrize("weight", [-1, 5001, math.inf, math.nan])
def test_controller_rejects_invalid_weight_from_any_adapter(weight: float) -> None:
    controller = NutriBoxController(
        RecordingBackend(),
        ArbitraryWeightSensor(weight),
        ArbitraryTemperatureSensor(25),
    )

    with pytest.raises(ValueError, match="weight"):
        controller.analyze_meal(Path("meal.jpg"))


@pytest.mark.parametrize("temperature", [math.inf, -math.inf, math.nan])
def test_controller_rejects_nonfinite_temperature_from_any_adapter(
    temperature: float,
) -> None:
    controller = NutriBoxController(
        RecordingBackend(),
        ArbitraryWeightSensor(100),
        ArbitraryTemperatureSensor(temperature),
    )

    with pytest.raises(ValueError, match="temperature"):
        controller.current_temperature_c()
