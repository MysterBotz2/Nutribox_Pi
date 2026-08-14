"""Replaceable hardware and network boundaries."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from nutribox_pi.models import AnalysisResult, HealthResult


class WeightSensor(Protocol):
    def read_grams(self) -> float: ...


class TemperatureSensor(Protocol):
    def read_celsius(self) -> float: ...


class Backend(Protocol):
    def health(self) -> HealthResult: ...

    def analyze_meal(self, image_path: Path, weight_grams: float) -> AnalysisResult: ...

