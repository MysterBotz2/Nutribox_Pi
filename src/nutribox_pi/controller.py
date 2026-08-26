"""Application orchestration independent of concrete adapters."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from nutribox_pi.models import AnalysisResult, HealthResult, MealAnalysisResponse
from nutribox_pi.ports import (
    Backend,
    TemperatureSensor,
    VerifiedDeviceCredentialProvider,
    WeightSensor,
)
from nutribox_pi.validation import validate_temperature, validate_weight


class NutriBoxController:
    def __init__(
        self,
        backend: Backend,
        weight_sensor: WeightSensor,
        temperature_sensor: TemperatureSensor,
        credential_provider: VerifiedDeviceCredentialProvider | None = None,
    ) -> None:
        self._backend = backend
        self._weight_sensor = weight_sensor
        self._temperature_sensor = temperature_sensor
        self._credential_provider = credential_provider

    def check_backend(self) -> HealthResult:
        return self._backend.health()

    def analyze_meal(self, image_path: Path) -> MealAnalysisResponse | AnalysisResult:
        weight_grams = validate_weight(self._weight_sensor.read_grams())
        token = (
            self._credential_provider.get_verified_device_token()
            if self._credential_provider
            else None
        )
        if token is None:
            result = self._backend.analyze_meal(
                image_path=image_path, weight_grams=weight_grams
            )
        else:
            result = self._backend.analyze_meal(
                image_path=image_path, weight_grams=weight_grams, device_token=token
            )
        if isinstance(result, MealAnalysisResponse):
            return replace(result, measured_weight_grams=weight_grams)
        return result

    def current_temperature_c(self) -> float:
        return validate_temperature(self._temperature_sensor.read_celsius())
