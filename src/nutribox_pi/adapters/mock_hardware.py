"""Deterministic hardware substitutes used during PI-0."""

from dataclasses import dataclass

from nutribox_pi.validation import validate_temperature, validate_weight


@dataclass(frozen=True, slots=True)
class SimulatedWeightSensor:
    grams: float = 250.0
    is_simulated = True

    def __post_init__(self) -> None:
        validate_weight(self.grams)

    def read_grams(self) -> float:
        return self.grams


@dataclass(frozen=True, slots=True)
class SimulatedTemperatureSensor:
    celsius: float = 25.0

    def __post_init__(self) -> None:
        validate_temperature(self.celsius)

    def read_celsius(self) -> float:
        return self.celsius
