"""Weight-source construction independent of backend and Pygame imports."""

from __future__ import annotations

from nutribox_pi.adapters.hx711_weight import HX711WeightSensor, WeightSensorUnavailable
from nutribox_pi.adapters.mock_hardware import SimulatedWeightSensor
from nutribox_pi.config import WeightConfigurationError, WeightSettings
from nutribox_pi.ports import WeightSensor


class UnavailableWeightSensor:
    is_simulated = False

    def read_grams(self) -> float:
        raise WeightSensorUnavailable()


def weight_from_env() -> WeightSensor:
    try:
        settings = WeightSettings.from_env()
    except WeightConfigurationError:
        return UnavailableWeightSensor()
    if settings.adapter == "simulated":
        return SimulatedWeightSensor(settings.simulated_grams)
    assert settings.data_pin is not None and settings.clock_pin is not None
    return HX711WeightSensor(
        settings.data_pin,
        settings.clock_pin,
        sample_count=settings.sample_count,
        stability_tolerance_grams=settings.stability_tolerance_grams,
        negative_noise_clamp_grams=settings.negative_noise_clamp_grams,
    )
