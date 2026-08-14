"""Domain values shared across PI-0 boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class AnalysisStatus(StrEnum):
    CALCULATED = "calculated"
    FOOD_NOT_RECOGNIZED = "food_not_recognized"
    REQUIRES_FOOD_SELECTION = "requires_food_selection"
    NUTRITION_REFERENCE_NOT_FOUND = "nutrition_reference_not_found"


@dataclass(frozen=True, slots=True)
class HealthResult:
    healthy: bool
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    status: AnalysisStatus
    payload: dict[str, Any]

