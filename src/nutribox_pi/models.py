"""Domain values shared across PI-0 boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Any


class AnalysisStatus(StrEnum):
    CALCULATED = "calculated"
    FOOD_NOT_RECOGNIZED = "food_not_recognized"
    REQUIRES_FOOD_SELECTION = "requires_food_selection"
    NUTRITION_REFERENCE_NOT_FOUND = "nutrition_reference_not_found"
    REQUIRES_INGREDIENT_VERIFICATION = "requires_ingredient_verification"
    REQUIRES_RECIPE_CONFIRMATION = "requires_recipe_confirmation"


@dataclass(frozen=True, slots=True)
class HealthResult:
    healthy: bool
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """Legacy status/payload result retained for compatible test doubles."""

    status: AnalysisStatus
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class NutritionValues:
    """Nutrition values retained exactly as backend decimal strings or null."""

    calories: str | None
    protein: str | None
    carbohydrates: str | None
    fat: str | None
    fiber: str | None
    values: dict[str, str | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for value in (
            self.calories,
            self.protein,
            self.carbohydrates,
            self.fat,
            self.fiber,
            *self.values.values(),
        ):
            if value is not None:
                _validate_decimal_string(value)


def _validate_decimal_string(value: str) -> None:
    if not isinstance(value, str):
        raise ValueError("nutrition value must be a decimal string or null")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("nutrition value must be a decimal string or null") from exc
    if not parsed.is_finite():
        raise ValueError("nutrition value must be a decimal string or null")


class RecognitionSource(StrEnum):
    SIMULATED = "simulated"
    GEMINI = "gemini"


class PairingStatus(StrEnum):
    PENDING = "pending"
    EXPIRED = "expired"
    PAIRED = "paired"


@dataclass(frozen=True, slots=True)
class PairingSession:
    session_id: str
    pairing_code: str
    device_token: str
    expires_at: str


@dataclass(frozen=True, slots=True)
class PairingStatusResponse:
    status: PairingStatus
    device_id: int | None


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    id: int
    name: str
    device_type: str
    paired_at: str
    last_seen_at: str | None
    owner_first_name: str = ""


@dataclass(frozen=True, slots=True)
class RecognizedFood:
    name: str


@dataclass(frozen=True, slots=True)
class FoodRecognitionResult:
    foods: tuple[RecognizedFood, ...]
    source: RecognitionSource


@dataclass(frozen=True, slots=True)
class MealAnalysisResponse:
    """Fields that every successful meal-analysis response contains."""

    status: AnalysisStatus
    recognized_foods: tuple[RecognizedFood, ...]
    recognition_source: RecognitionSource
    measured_weight_grams: float | None = None
    analysis_session_id: str | None = None
    analysis_session_expires_at: str | None = None


@dataclass(frozen=True, slots=True)
class FoodNotRecognizedResponse(MealAnalysisResponse):
    pass


@dataclass(frozen=True, slots=True)
class RequiresFoodSelectionResponse(MealAnalysisResponse):
    pass


@dataclass(frozen=True, slots=True)
class NutritionReferenceNotFoundResponse(MealAnalysisResponse):
    pass


@dataclass(frozen=True, slots=True)
class CalculatedResponse(MealAnalysisResponse):
    nutrition: NutritionValues = field(kw_only=True)


class CameraCode(StrEnum):
    OK = "ok"
    SKIPPED = "skipped"
    INVALID_CONFIGURATION = "invalid_configuration"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    CAMERA_UNAVAILABLE = "camera_unavailable"
    CAMERA_BUSY = "camera_busy"
    CAMERA_INITIALIZATION_FAILED = "camera_initialization_failed"
    AUTOFOCUS_FAILED = "autofocus_failed"
    AUTOFOCUS_TIMEOUT = "autofocus_timeout"
    INVALID_OUTPUT = "invalid_output"
    OUTPUT_EXISTS = "output_exists"
    CAPTURE_FAILED = "capture_failed"
    INVALID_IMAGE = "invalid_image"
    PUBLICATION_FAILED = "publication_failed"
    CLEANUP_FAILED = "cleanup_failed"


CAMERA_MESSAGES: dict[CameraCode, str] = {
    CameraCode.INVALID_CONFIGURATION: "Camera configuration is invalid.",
    CameraCode.DEPENDENCY_UNAVAILABLE: "Required camera support is unavailable.",
    CameraCode.CAMERA_UNAVAILABLE: "Camera is unavailable.",
    CameraCode.CAMERA_BUSY: "Camera is busy.",
    CameraCode.CAMERA_INITIALIZATION_FAILED: "Camera initialization failed.",
    CameraCode.AUTOFOCUS_FAILED: "Camera autofocus failed.",
    CameraCode.AUTOFOCUS_TIMEOUT: "Camera autofocus timed out.",
    CameraCode.INVALID_OUTPUT: "Capture output is invalid.",
    CameraCode.OUTPUT_EXISTS: "Capture output already exists.",
    CameraCode.CAPTURE_FAILED: "Camera capture failed.",
    CameraCode.INVALID_IMAGE: "Captured image is invalid.",
    CameraCode.PUBLICATION_FAILED: "Image publication failed.",
}


@dataclass(frozen=True, slots=True)
class CameraAvailability:
    available: bool
    code: CameraCode
    message: str
    picamera2_version: str
    libcamera_version: str


@dataclass(frozen=True, slots=True)
class CaptureResult:
    ok: bool
    code: CameraCode
    message: str
    published: bool
    output_path: Path | None
    format: str | None
    width: int | None
    height: int | None
    byte_size: int | None


@dataclass(frozen=True, slots=True)
class PreviewFrame:
    """An immutable RGB camera frame with no hardware-library types."""

    width: int
    height: int
    rgb_bytes: bytes
