"""HTTP adapter for the two known v1 backend endpoints."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID

import requests

from nutribox_pi.models import (
    AnalysisResult,
    AnalysisStatus,
    CalculatedFoodReference,
    CalculatedResponse,
    FoodNotRecognizedResponse,
    HealthResult,
    IngredientCandidateSelection,
    IngredientVerification,
    MealAnalysisCandidate,
    MealAnalysisComponent,
    MealAnalysisResponse,
    MealAnalysisSelection,
    NutritionReferenceNotFoundResponse,
    NutritionValues,
    PersonalRecipeMatch,
    PersonalRecipeSelection,
    RecognitionSource,
    RecognizedFood,
    RequiresFoodSelectionResponse,
    RequiresIngredientVerificationResponse,
    RequiresRecipeConfirmationResponse,
    SuggestedIngredient,
)
from nutribox_pi.ports import DeviceAuthenticationFailure, RetryableBackendFailure
from nutribox_pi.validation import (
    validate_api_base_url,
    validate_timeout,
    validate_weight,
)


class BackendError(RuntimeError):
    """Raised when the v1 backend cannot provide a valid response."""


class RetryableBackendError(BackendError, RetryableBackendFailure):
    pass


class DeviceAuthenticationError(BackendError, DeviceAuthenticationFailure):
    pass


class AnalysisSessionError(BackendError):
    """The analysis session is missing, expired, consumed, or unusable."""


class ValidationConflictError(BackendError):
    """The continuation request conflicts with the backend contract or state."""


class MalformedBackendResponseError(BackendError):
    """A successful response did not match the authoritative schema."""


class V1BackendClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 10.0,
        session: requests.Session | None = None,
    ) -> None:
        try:
            self._base_url = validate_api_base_url(base_url)
            self._timeout = validate_timeout(timeout_seconds)
        except ValueError as exc:
            raise BackendError(str(exc)) from exc
        self._session = session or requests.Session()

    def health(self) -> HealthResult:
        self._request("GET", "/api/health")
        return HealthResult(healthy=True, payload={})

    def analyze_meal(
        self, image_path: Path, weight_grams: float, device_token: str | None = None
    ) -> MealAnalysisResponse | AnalysisResult:
        try:
            weight_grams = validate_weight(weight_grams)
        except ValueError as exc:
            raise BackendError(str(exc)) from exc

        filename = image_path.name
        if "\r" in filename or "\n" in filename:
            raise BackendError("image filename must not contain CR or LF characters")

        try:
            with image_path.open("rb") as image:
                request_options: dict[str, Any] = {}
                if device_token:
                    request_options["headers"] = {"X-Device-Token": device_token}
                response = self._request(
                    "POST",
                    "/api/meals/analyze",
                    files={"file": ("meal.jpg", image, "image/jpeg")},
                    data={"weight_grams": f"{weight_grams:g}"},
                    **request_options,
                )
        except OSError as exc:
            raise BackendError("cannot read image file") from exc

        payload = self._json_object(response)
        return self._analysis_response(payload)

    def select_food_component(
        self,
        analysis_session_id: int,
        selection: MealAnalysisSelection,
        device_token: str | None = None,
    ) -> MealAnalysisResponse:
        return self._continue(
            "POST",
            self._continuation_path(analysis_session_id, "selections"),
            selection.to_payload(),
            device_token,
        )

    def update_ingredients(
        self,
        analysis_session_id: int,
        component_id: str,
        update: IngredientVerification,
        device_token: str | None = None,
    ) -> MealAnalysisResponse:
        return self._continue(
            "PUT",
            self._component_path(analysis_session_id, component_id, "ingredients"),
            update.to_payload(),
            device_token,
        )

    def select_ingredient_candidate(
        self,
        analysis_session_id: int,
        component_id: str,
        selection: IngredientCandidateSelection,
        device_token: str | None = None,
    ) -> MealAnalysisResponse:
        return self._continue(
            "POST",
            self._component_path(
                analysis_session_id, component_id, "ingredients/selections"
            ),
            selection.to_payload(),
            device_token,
        )

    def use_recipe(
        self,
        analysis_session_id: int,
        component_id: str,
        selection: PersonalRecipeSelection,
        device_token: str | None = None,
    ) -> MealAnalysisResponse:
        return self._continue(
            "POST",
            self._component_path(analysis_session_id, component_id, "use-recipe"),
            selection.to_payload(),
            device_token,
        )

    def review_recipe(
        self,
        analysis_session_id: int,
        component_id: str,
        selection: PersonalRecipeSelection,
        device_token: str | None = None,
    ) -> MealAnalysisResponse:
        return self._continue(
            "POST",
            self._component_path(analysis_session_id, component_id, "review-recipe"),
            selection.to_payload(),
            device_token,
        )

    def analyze_component_as_new(
        self,
        analysis_session_id: int,
        component_id: str,
        device_token: str | None = None,
    ) -> MealAnalysisResponse:
        return self._continue(
            "POST",
            self._component_path(analysis_session_id, component_id, "analyze-as-new"),
            None,
            device_token,
        )

    def _continue(
        self,
        method: str,
        path: str,
        body: dict[str, object] | None,
        device_token: str | None,
    ) -> MealAnalysisResponse:
        options: dict[str, Any] = {}
        if body is not None:
            options["json"] = body
        if device_token:
            options["headers"] = {"X-Device-Token": device_token}
        response = self._request(method, path, **options)
        return self._analysis_response(self._json_object(response))

    @staticmethod
    def _continuation_path(analysis_session_id: int, suffix: str) -> str:
        if (
            isinstance(analysis_session_id, bool)
            or not isinstance(analysis_session_id, int)
            or analysis_session_id <= 0
        ):
            raise BackendError("analysis session identifier is invalid")
        return f"/api/meals/analysis-sessions/{analysis_session_id}/{suffix}"

    @classmethod
    def _component_path(
        cls, analysis_session_id: int, component_id: str, suffix: str
    ) -> str:
        base = cls._continuation_path(analysis_session_id, "components")
        try:
            valid = (
                isinstance(component_id, str)
                and str(UUID(component_id)) == component_id.lower()
            )
        except (ValueError, AttributeError):
            valid = False
        if not valid:
            raise BackendError("component identifier is invalid")
        return f"{base}/{quote(component_id, safe='')}/{suffix}"

    @staticmethod
    def _analysis_response(payload: dict[str, Any]) -> MealAnalysisResponse:
        try:
            status = AnalysisStatus(payload["status"])
            recognition_source = RecognitionSource(payload["recognition_source"])
            foods_payload = payload["recognized_foods"]
        except (KeyError, ValueError, TypeError) as exc:
            raise MalformedBackendResponseError(
                "backend returned an invalid analysis response"
            ) from exc
        if not isinstance(foods_payload, list):
            raise MalformedBackendResponseError(
                "backend returned an invalid analysis response"
            )
        try:
            allowed = {
                "status",
                "recognized_foods",
                "recognition_source",
                "measured_weight_grams",
                "analysis_session_id",
                "analysis_session_expires_at",
                "components",
            }
            if status is AnalysisStatus.CALCULATED:
                allowed |= {"nutrition", "weight_grams", "weight_source", "food"}
            if payload.keys() - allowed:
                raise ValueError("unknown analysis fields")
            foods = tuple(_recognized_food(item) for item in foods_payload)
            measured_weight = _optional_decimal(payload, "measured_weight_grams")
            session_id = _optional_positive_int(payload, "analysis_session_id")
            expires_at = _optional_expiry(payload, "analysis_session_expires_at")
            components = _optional_components(payload)
            common: dict[str, Any] = {
                "status": status,
                "recognized_foods": foods,
                "recognition_source": recognition_source,
                "measured_weight_grams": measured_weight,
                "analysis_session_id": session_id,
                "analysis_session_expires_at": expires_at,
                "components": components,
            }
            calculated_fields = {"nutrition", "weight_grams", "weight_source", "food"}
            if (
                status is not AnalysisStatus.CALCULATED
                and calculated_fields & payload.keys()
            ):
                raise ValueError("contradictory analysis fields")
            response_types = {
                AnalysisStatus.FOOD_NOT_RECOGNIZED: FoodNotRecognizedResponse,
                AnalysisStatus.REQUIRES_FOOD_SELECTION: RequiresFoodSelectionResponse,
                AnalysisStatus.NUTRITION_REFERENCE_NOT_FOUND: (
                    NutritionReferenceNotFoundResponse
                ),
                AnalysisStatus.REQUIRES_INGREDIENT_VERIFICATION: (
                    RequiresIngredientVerificationResponse
                ),
                AnalysisStatus.REQUIRES_RECIPE_CONFIRMATION: (
                    RequiresRecipeConfirmationResponse
                ),
            }
            if status is not AnalysisStatus.CALCULATED:
                return response_types[status](**common)
            nutrition = _nutrition(payload["nutrition"])
            weight_grams = _required_decimal(payload, "weight_grams")
            weight_source = payload.get("weight_source")
            if weight_source is not None and weight_source not in {
                "manual",
                "ai_estimate",
            }:
                raise ValueError("weight source is invalid")
            food = _calculated_food(payload.get("food"))
            return CalculatedResponse(
                **common,
                nutrition=nutrition,
                weight_grams=weight_grams,
                weight_source=weight_source,
                food=food,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MalformedBackendResponseError(
                "backend returned an invalid analysis response"
            ) from exc

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        try:
            response = self._session.request(
                method,
                f"{self._base_url}{path}",
                timeout=self._timeout,
                **kwargs,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise RetryableBackendError("backend request failed") from exc
        except requests.RequestException as exc:
            raise BackendError("backend request failed") from exc
        if response.status_code == 401:
            raise DeviceAuthenticationError("device authentication failed")
        if response.status_code in {503, 504}:
            raise RetryableBackendError("backend request failed")
        if response.status_code in {404, 409, 410}:
            raise AnalysisSessionError("analysis session is unavailable")
        if response.status_code == 422:
            raise ValidationConflictError("continuation request was rejected")
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise BackendError("backend request failed") from exc
        if not 200 <= response.status_code < 300:
            raise BackendError(f"backend returned HTTP {response.status_code}")
        return response

    @staticmethod
    def _json_object(response: requests.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except requests.exceptions.JSONDecodeError as exc:
            raise MalformedBackendResponseError(
                "backend returned invalid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise MalformedBackendResponseError(
                "backend JSON response must be an object"
            )
        return payload


_NUTRIENT_FIELDS = {
    "calories",
    "protein_g",
    "carbohydrates_g",
    "fat_g",
    "fiber_g",
    "energy_kj",
    "saturated_fat_g",
    "sugars_g",
    "sodium_mg",
    "cholesterol_mg",
    "omega_3_g",
    "omega_6_g",
    "calcium_mg",
    "iron_mg",
    "potassium_mg",
    "magnesium_mg",
    "zinc_mg",
    "phosphorus_mg",
    "vitamin_a_mcg_rae",
    "vitamin_b6_mg",
    "vitamin_c_mg",
    "vitamin_d_mcg",
    "vitamin_b12_mcg",
    "folate_mcg_dfe",
    "niacin_mg",
}


def _recognized_food(value: object) -> RecognizedFood:
    if not isinstance(value, dict) or set(value) != {"name"}:
        raise ValueError("recognized food is invalid")
    return RecognizedFood(value["name"])


def _required_decimal(payload: dict[str, Any], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str):
        raise ValueError("decimal value is invalid")
    parsed = Decimal(value)
    if not parsed.is_finite() or parsed < 0:
        raise ValueError("decimal value is invalid")
    return value


def _optional_decimal(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    return _required_decimal(payload, key)


def _optional_positive_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("identifier is invalid")
    return value


def _optional_expiry(payload: dict[str, Any], key: str) -> datetime | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("expiry is invalid")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("expiry is invalid")
    return parsed


def _nutrition(value: object) -> NutritionValues:
    if not isinstance(value, dict):
        raise ValueError("nutrition is invalid")
    required = {"calories", "protein_g", "carbohydrates_g", "fat_g", "fiber_g"}
    if not required <= value.keys() or value.keys() - _NUTRIENT_FIELDS:
        raise ValueError("nutrition is invalid")
    for key, item in value.items():
        if item is not None and not isinstance(item, str):
            raise ValueError("nutrition is invalid")
        if key in required and item is None:
            raise ValueError("nutrition is invalid")
    return NutritionValues(
        calories=value["calories"],
        protein=value["protein_g"],
        carbohydrates=value["carbohydrates_g"],
        fat=value["fat_g"],
        fiber=value["fiber_g"],
        values=dict(value),
    )


def _candidate(value: object) -> MealAnalysisCandidate:
    if not isinstance(value, dict) or not {"name"} <= value.keys():
        raise ValueError("candidate is invalid")
    if value.keys() - {"name", "candidate_id"}:
        raise ValueError("candidate is invalid")
    return MealAnalysisCandidate(value["name"], value.get("candidate_id"))


def _suggested_ingredient(value: object) -> SuggestedIngredient:
    if not isinstance(value, dict):
        raise ValueError("ingredient is invalid")
    required = {
        "ingredient_id",
        "name",
        "suggested_proportion",
        "ingredient_source",
        "included",
        "weight_source",
        "resolution_status",
    }
    optional = {
        "weight_grams",
        "nutrition_source",
        "resolved_reference",
        "candidates",
        "recipe_derived",
    }
    if not required <= value.keys() or value.keys() - required - optional:
        raise ValueError("ingredient is invalid")
    candidates = value.get("candidates", [])
    if not isinstance(candidates, list):
        raise ValueError("ingredient candidates are invalid")
    return SuggestedIngredient(
        ingredient_id=value["ingredient_id"],
        name=value["name"],
        suggested_proportion=value["suggested_proportion"],
        ingredient_source=value["ingredient_source"],
        included=value["included"],
        weight_source=value["weight_source"],
        resolution_status=value["resolution_status"],
        weight_grams=value.get("weight_grams"),
        nutrition_source=value.get("nutrition_source"),
        resolved_reference=value.get("resolved_reference"),
        candidates=tuple(_candidate(item) for item in candidates),
        recipe_derived=value.get("recipe_derived", False),
    )


def _recipe(value: object) -> PersonalRecipeMatch:
    if not isinstance(value, dict) or set(value) != {"recipe_id", "name", "source"}:
        raise ValueError("recipe is invalid")
    return PersonalRecipeMatch(value["recipe_id"], value["name"], value["source"])


def _component(value: object) -> MealAnalysisComponent:
    if not isinstance(value, dict):
        raise ValueError("component is invalid")
    required = {
        "component_id",
        "recognized_name",
        "raw_estimated_proportion",
        "normalized_proportion",
        "estimated_weight_grams",
        "weight_source",
        "resolution_status",
        "nutrition_source",
        "resolved_reference",
        "candidates",
        "nutrition",
    }
    optional = {"suggested_ingredients", "recipe_matches", "composite_estimation"}
    if not required <= value.keys() or value.keys() - required - optional:
        raise ValueError("component is invalid")
    candidates = value["candidates"]
    ingredients = value.get("suggested_ingredients", [])
    recipes = value.get("recipe_matches", [])
    if not all(isinstance(items, list) for items in (candidates, ingredients, recipes)):
        raise ValueError("component collection is invalid")
    return MealAnalysisComponent(
        component_id=value["component_id"],
        recognized_name=value["recognized_name"],
        raw_estimated_proportion=value["raw_estimated_proportion"],
        normalized_proportion=value["normalized_proportion"],
        estimated_weight_grams=value["estimated_weight_grams"],
        weight_source=value["weight_source"],
        resolution_status=value["resolution_status"],
        nutrition_source=value["nutrition_source"],
        resolved_reference=value["resolved_reference"],
        candidates=tuple(_candidate(item) for item in candidates),
        nutrition=(
            None if value["nutrition"] is None else _nutrition(value["nutrition"])
        ),
        suggested_ingredients=tuple(
            _suggested_ingredient(item) for item in ingredients
        ),
        recipe_matches=tuple(_recipe(item) for item in recipes),
        composite_estimation=value.get("composite_estimation", False),
    )


def _optional_components(
    payload: dict[str, Any],
) -> tuple[MealAnalysisComponent, ...] | None:
    value = payload.get("components")
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("components are invalid")
    return tuple(_component(item) for item in value)


def _calculated_food(value: object) -> CalculatedFoodReference | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"id", "name"}:
        raise ValueError("calculated food is invalid")
    return CalculatedFoodReference(value["id"], value["name"])
