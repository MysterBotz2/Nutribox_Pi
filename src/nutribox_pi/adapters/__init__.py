"""PI-0 adapter implementations."""

from nutribox_pi.adapters.device_pairing import DevicePairingClient, PairingError
from nutribox_pi.adapters.food_recognizer import (
    FoodRecognitionError,
    HttpFoodRecognizer,
)
from nutribox_pi.adapters.hx711_weight import (
    HX711WeightSensor,
    WeightCalibration,
    WeightCalibrationStore,
    WeightSensorUnavailable,
)
from nutribox_pi.adapters.mock_hardware import (
    SimulatedTemperatureSensor,
    SimulatedWeightSensor,
)
from nutribox_pi.adapters.v1_backend import BackendError, V1BackendClient

__all__ = [
    "BackendError",
    "DevicePairingClient",
    "FoodRecognitionError",
    "HttpFoodRecognizer",
    "PairingError",
    "SimulatedTemperatureSensor",
    "SimulatedWeightSensor",
    "HX711WeightSensor",
    "WeightCalibration",
    "WeightCalibrationStore",
    "WeightSensorUnavailable",
    "V1BackendClient",
]
