"""Domain values shared across PI-0 boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
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


_SAVED_OPTIONAL_NUTRIENTS = (
    "saturated_fat_g",
    "sugars_g",
    "sodium_mg",
    "cholesterol_mg",
    "omega_3_g",
    "omega_6_g",
    "calcium_mg",
    "potassium_mg",
    "zinc_mg",
    "iron_mg",
    "magnesium_mg",
    "energy_kj",
    "phosphorus_mg",
    "vitamin_b6_mg",
    "niacin_mg",
    "vitamin_a_mcg_rae",
    "vitamin_b12_mcg",
    "vitamin_c_mg",
    "vitamin_d_mcg",
    "folate_mcg_dfe",
)


@dataclass(frozen=True, slots=True)
class AdditionalNutrientValues:
    values: dict[str, str | None]

    def __post_init__(self) -> None:
        if set(self.values) != set(_SAVED_OPTIONAL_NUTRIENTS):
            raise ValueError("saved meal nutrients are invalid")
        for value in self.values.values():
            if value is not None:
                _validate_decimal_string(value)


@dataclass(frozen=True, slots=True)
class MealTotals:
    calories: str
    protein_g: str
    carbohydrates_g: str
    fat_g: str
    fiber_g: str
    additional: AdditionalNutrientValues

    def __post_init__(self) -> None:
        for value in (
            self.calories,
            self.protein_g,
            self.carbohydrates_g,
            self.fat_g,
            self.fiber_g,
        ):
            _validate_decimal_string(value)


@dataclass(frozen=True, slots=True)
class MealItemNutritionSource:
    category: str | None
    name: str | None
    reference: str | None
    is_estimated: bool | None

    def __post_init__(self) -> None:
        if self.category not in {
            None,
            "canteen_recipe",
            "local_database",
            "USDA",
            "AI_estimate",
            "ai_recipe_estimate",
        }:
            raise ValueError("saved meal provenance is invalid")
        if self.is_estimated is not None and not isinstance(self.is_estimated, bool):
            raise ValueError("saved meal provenance is invalid")
        for value in (self.name, self.reference):
            if value is not None:
                _validate_text(value)


@dataclass(frozen=True, slots=True)
class SavedMealFood:
    id: int | None
    name: str

    def __post_init__(self) -> None:
        if self.id is not None:
            _validate_positive_id(self.id)
        _validate_text(self.name)


@dataclass(frozen=True, slots=True)
class MealItemResponse:
    id: int
    food: SavedMealFood
    weight_grams: str
    nutrition: MealTotals
    nutrition_source: MealItemNutritionSource | None
    composite_estimation: bool

    def __post_init__(self) -> None:
        _validate_positive_id(self.id)
        _validate_decimal_range(
            self.weight_grams, positive=True, maximum=Decimal("5000")
        )
        if not isinstance(self.composite_estimation, bool):
            raise ValueError("saved meal item is invalid")


@dataclass(frozen=True, slots=True)
class MealResponse:
    id: int
    recorded_at: datetime
    items: tuple[MealItemResponse, ...]
    totals: MealTotals
    additional_totals: AdditionalNutrientValues

    def __post_init__(self) -> None:
        _validate_positive_id(self.id)
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("saved meal timestamp is invalid")


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
    if not parsed.is_finite() or parsed < 0:
        raise ValueError("nutrition value must be a decimal string or null")


def _validate_text(value: str, *, maximum: int = 160) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError("text value is invalid")


def _validate_uuid(value: str) -> None:
    from uuid import UUID

    if not isinstance(value, str) or str(UUID(value)) != value.lower():
        raise ValueError("identifier is invalid")


def _validate_positive_id(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("identifier is invalid")


def _validate_decimal_range(
    value: str, *, positive: bool = False, maximum: Decimal | None = None
) -> None:
    _validate_decimal_string(value)
    parsed = Decimal(value)
    if (positive and parsed <= 0) or (maximum is not None and parsed > maximum):
        raise ValueError("decimal value is outside the contract range")


class RecognitionSource(StrEnum):
    SIMULATED = "simulated"
    GEMINI = "gemini"
    SESSION = "session"


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

    def __post_init__(self) -> None:
        _validate_text(self.name, maximum=120)


@dataclass(frozen=True, slots=True)
class MealAnalysisCandidate:
    name: str
    candidate_id: str | None = None

    def __post_init__(self) -> None:
        _validate_text(self.name)
        if self.candidate_id is not None:
            _validate_uuid(self.candidate_id)


@dataclass(frozen=True, slots=True)
class PersonalRecipeMatch:
    recipe_id: int
    name: str
    source: str

    def __post_init__(self) -> None:
        _validate_positive_id(self.recipe_id)
        _validate_text(self.name)
        if self.source != "personal":
            raise ValueError("recipe source is invalid")


@dataclass(frozen=True, slots=True)
class SuggestedIngredient:
    ingredient_id: str
    name: str
    suggested_proportion: str
    ingredient_source: str
    included: bool
    weight_source: str
    resolution_status: str
    weight_grams: str | None = None
    nutrition_source: str | None = None
    resolved_reference: str | None = None
    candidates: tuple[MealAnalysisCandidate, ...] = ()
    recipe_derived: bool = False

    def __post_init__(self) -> None:
        _validate_uuid(self.ingredient_id)
        _validate_text(self.name)
        _validate_decimal_range(self.suggested_proportion, maximum=Decimal("1"))
        for value in (
            self.ingredient_source,
            self.weight_source,
            self.resolution_status,
        ):
            _validate_text(value)
        if not isinstance(self.included, bool) or not isinstance(
            self.recipe_derived, bool
        ):
            raise ValueError("ingredient flag is invalid")
        if self.weight_grams is not None:
            _validate_decimal_string(self.weight_grams)
        for value in (self.nutrition_source, self.resolved_reference):
            if value is not None:
                _validate_text(value)


@dataclass(frozen=True, slots=True)
class MealAnalysisComponent:
    component_id: str
    recognized_name: str
    raw_estimated_proportion: str
    normalized_proportion: str
    estimated_weight_grams: str
    weight_source: str
    resolution_status: str
    nutrition_source: str | None
    resolved_reference: str | None
    candidates: tuple[MealAnalysisCandidate, ...]
    nutrition: NutritionValues | None
    suggested_ingredients: tuple[SuggestedIngredient, ...] = ()
    recipe_matches: tuple[PersonalRecipeMatch, ...] = ()
    composite_estimation: bool = False

    def __post_init__(self) -> None:
        _validate_uuid(self.component_id)
        _validate_text(self.recognized_name)
        _validate_decimal_range(self.raw_estimated_proportion, maximum=Decimal("1"))
        _validate_decimal_range(self.normalized_proportion, maximum=Decimal("1"))
        _validate_decimal_string(self.estimated_weight_grams)
        _validate_text(self.weight_source)
        _validate_text(self.resolution_status)
        if not isinstance(self.composite_estimation, bool):
            raise ValueError("component flag is invalid")
        for value in (self.nutrition_source, self.resolved_reference):
            if value is not None:
                _validate_text(value)


@dataclass(frozen=True, slots=True)
class CalculatedFoodReference:
    id: int | None
    name: str

    def __post_init__(self) -> None:
        if self.id is not None:
            _validate_positive_id(self.id)
        _validate_text(self.name)


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
    measured_weight_grams: str | float | None = None
    analysis_session_id: int | None = None
    analysis_session_expires_at: datetime | None = None
    components: tuple[MealAnalysisComponent, ...] | None = None

    def __post_init__(self) -> None:
        if self.analysis_session_id is not None:
            _validate_positive_id(self.analysis_session_id)
        if self.analysis_session_expires_at is not None and (
            self.analysis_session_expires_at.tzinfo is None
            or self.analysis_session_expires_at.utcoffset() is None
        ):
            raise ValueError("analysis expiry must include a timezone")
        if isinstance(self.measured_weight_grams, str):
            _validate_decimal_string(self.measured_weight_grams)
        elif self.measured_weight_grams is not None and (
            isinstance(self.measured_weight_grams, bool)
            or not isinstance(self.measured_weight_grams, (int, float))
            or not Decimal(str(self.measured_weight_grams)).is_finite()
            or self.measured_weight_grams < 0
        ):
            raise ValueError("measured weight is invalid")


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
class RequiresIngredientVerificationResponse(MealAnalysisResponse):
    pass


@dataclass(frozen=True, slots=True)
class RequiresRecipeConfirmationResponse(MealAnalysisResponse):
    pass


@dataclass(frozen=True, slots=True)
class CalculatedResponse(MealAnalysisResponse):
    nutrition: NutritionValues = field(kw_only=True)
    weight_grams: str | None = field(default=None, kw_only=True)
    weight_source: str | None = field(default=None, kw_only=True)
    food: CalculatedFoodReference | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        super(CalculatedResponse, self).__post_init__()
        if self.weight_grams is not None:
            _validate_decimal_string(self.weight_grams)
        if self.weight_source is not None:
            _validate_text(self.weight_source)


@dataclass(frozen=True, slots=True)
class MealAnalysisSelection:
    component_id: str
    candidate_id: str | None

    def __post_init__(self) -> None:
        _validate_uuid(self.component_id)
        if self.candidate_id is not None:
            _validate_uuid(self.candidate_id)

    def to_payload(self) -> dict[str, str | None]:
        return {"component_id": self.component_id, "candidate_id": self.candidate_id}


@dataclass(frozen=True, slots=True)
class IngredientVerificationItem:
    name: str
    included: bool
    ingredient_id: str | None = None
    weight_grams: str | float | None = None

    def __post_init__(self) -> None:
        _validate_text(self.name)
        if not isinstance(self.included, bool):
            raise ValueError("ingredient flag is invalid")
        if self.ingredient_id is not None:
            _validate_uuid(self.ingredient_id)
        if self.weight_grams is not None:
            try:
                parsed = Decimal(str(self.weight_grams))
            except InvalidOperation as exc:
                raise ValueError("ingredient weight is invalid") from exc
            if not parsed.is_finite() or parsed <= 0 or parsed > 5000:
                raise ValueError("ingredient weight is invalid")

    def to_payload(self) -> dict[str, str | float | bool | None]:
        payload: dict[str, str | float | bool | None] = {
            "name": self.name,
            "included": self.included,
        }
        if self.ingredient_id is not None:
            payload["ingredient_id"] = self.ingredient_id
        if self.weight_grams is not None:
            payload["weight_grams"] = self.weight_grams
        return payload


@dataclass(frozen=True, slots=True)
class IngredientVerification:
    ingredients: tuple[IngredientVerificationItem, ...]

    def __post_init__(self) -> None:
        if not 1 <= len(self.ingredients) <= 50:
            raise ValueError("ingredient count is invalid")

    def to_payload(self) -> dict[str, list[dict[str, object]]]:
        return {"ingredients": [dict(item.to_payload()) for item in self.ingredients]}


@dataclass(frozen=True, slots=True)
class IngredientCandidateSelection:
    ingredient_id: str
    candidate_id: str

    def __post_init__(self) -> None:
        _validate_uuid(self.ingredient_id)
        _validate_uuid(self.candidate_id)

    def to_payload(self) -> dict[str, str]:
        return {
            "ingredient_id": self.ingredient_id,
            "candidate_id": self.candidate_id,
        }


@dataclass(frozen=True, slots=True)
class PersonalRecipeSelection:
    recipe_id: int

    def __post_init__(self) -> None:
        _validate_positive_id(self.recipe_id)

    def to_payload(self) -> dict[str, int]:
        return {"recipe_id": self.recipe_id}


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
