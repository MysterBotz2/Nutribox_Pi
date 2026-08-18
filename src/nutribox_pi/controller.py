"""Application orchestration independent of concrete adapters."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from nutribox_pi.models import AnalysisResult, HealthResult, MealAnalysisResponse
from nutribox_pi.ports import Backend, TemperatureSensor, WeightSensor
from nutribox_pi.validation import validate_temperature, validate_weight


class NutriBoxController:
    def __init__(
        self,
        backend: Backend,
        weight_sensor: WeightSensor,
        temperature_sensor: TemperatureSensor,
    ) -> None:
        self._backend = backend
        self._weight_sensor = weight_sensor
        self._temperature_sensor = temperature_sensor

    def check_backend(self) -> HealthResult:
        return self._backend.health()

    def analyze_meal(
        self, image_path: Path
    ) -> MealAnalysisResponse | AnalysisResult:
        weight_grams = validate_weight(self._weight_sensor.read_grams())
        result = self._backend.analyze_meal(
            image_path=image_path,
            weight_grams=weight_grams,
        )
        if isinstance(result, MealAnalysisResponse):
            return replace(result, measured_weight_grams=weight_grams)
        return result

    def current_temperature_c(self) -> float:
        return validate_temperature(self._temperature_sensor.read_celsius())
