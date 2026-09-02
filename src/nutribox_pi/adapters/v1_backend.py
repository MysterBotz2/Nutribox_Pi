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
    AdditionalNutrientValues,
    AnalysisResult,
    AnalysisStatus,
    CalculatedFoodReference,
    CalculatedResponse,
    FoodNotRecognizedResponse,
    HealthResult,
    IngredientCandidateSelection,
    IngredientVerification,
    LeftoverScanResponse,
    LeftoverScanWarning,
    MealAnalysisCandidate,
    MealAnalysisComponent,
    MealAnalysisResponse,
    MealAnalysisSelection,
    MealItemNutritionSource,
    MealItemResponse,
    MealResponse,
    MealTotals,
    NutritionReferenceNotFoundResponse,
    NutritionValues,
    PersonalRecipeMatch,
    PersonalRecipeSelection,
    RecognitionSource,
    RecognizedFood,
    RequiresFoodSelectionResponse,
    RequiresIngredientVerificationResponse,
    RequiresRecipeConfirmationResponse,
    SavedMealFood,
    SavedMealListItem,
    SavedMealPage,
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

    def save_meal(
        self, analysis_session_id: int, device_token: str | None = None
    ) -> MealResponse:
        if not device_token:
            raise BackendError("verified device credential is required")
        options: dict[str, Any] = {"json": {"analysis_session_id": analysis_session_id}}
        if device_token:
            options["headers"] = {"X-Device-Token": device_token}
        response = self._request(
            "POST",
            "/api/meals",
            **options,
        )
        return _meal_response(self._json_object(response))

    def list_saved_meals(
        self, limit: int, offset: int, device_token: str | None = None
    ) -> SavedMealPage:
        if not device_token:
            raise BackendError("verified device credential is required")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
            or isinstance(offset, bool)
            or not isinstance(offset, int)
            or offset < 0
        ):
            raise BackendError("saved meal page is invalid")
        response = self._request(
            "GET",
            "/api/meals",
            params={"limit": limit, "offset": offset},
            headers={"X-Device-Token": device_token},
        )
        return _saved_meal_page(self._json_object(response))

    def get_saved_meal(
        self, meal_id: int, device_token: str | None = None
    ) -> MealResponse:
        if not device_token:
            raise BackendError("verified device credential is required")
        return _meal_response(
            self._json_object(
                self._request(
                    "GET",
                    f"/api/meals/{_saved_id(meal_id)}",
                    headers={"X-Device-Token": device_token},
                )
            )
        )

    def create_leftover_scan(
        self,
        meal_id: int,
        analysis_session_id: int,
        device_token: str | None = None,
    ) -> LeftoverScanResponse:
        if not device_token:
            raise BackendError("verified device credential is required")
        meal_id = _saved_id(meal_id)
        analysis_session_id = _saved_id(analysis_session_id)
        response = self._request(
            "POST",
            f"/api/meals/{meal_id}/leftover-scans",
            json={"analysis_session_id": analysis_session_id},
            headers={"X-Device-Token": device_token},
        )
        return _leftover_scan_response(self._json_object(response))

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

_SAVED_EXTRA = {
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
}


def _meal_response(payload: object) -> MealResponse:
    try:
        if not isinstance(payload, dict) or set(payload) != {
            "id",
            "recorded_at",
            "items",
            "totals",
            "additional_totals",
        }:
            raise ValueError
        recorded = _optional_expiry(payload, "recorded_at")
        if recorded is None or not isinstance(payload["items"], list):
            raise ValueError
        totals = _meal_totals(payload["totals"])
        additional = _additional(payload["additional_totals"])
        return MealResponse(
            _saved_id(payload["id"]),
            recorded,
            tuple(_meal_item(item) for item in payload["items"]),
            totals,
            additional,
        )
    except Exception as exc:
        raise MalformedBackendResponseError(
            "backend returned an invalid saved meal"
        ) from exc


def _saved_meal_page(payload: object) -> SavedMealPage:
    """Parse the deliberately compact, paginated saved-meal list schema."""
    try:
        if not isinstance(payload, dict) or set(payload) != {
            "meals",
            "limit",
            "offset",
        }:
            raise ValueError
        meals = payload["meals"]
        if not isinstance(meals, list):
            raise ValueError
        return SavedMealPage(
            tuple(_saved_meal_list_item(item) for item in meals),
            payload["limit"],
            payload["offset"],
        )
    except (TypeError, ValueError, KeyError) as exc:
        raise MalformedBackendResponseError(
            "backend returned an invalid saved meal list"
        ) from exc


def _saved_meal_list_item(value: object) -> SavedMealListItem:
    if not isinstance(value, dict) or set(value) != {
        "id",
        "recorded_at",
        "items",
        "totals",
    }:
        raise ValueError
    recorded = _optional_expiry(value, "recorded_at")
    items = value["items"]
    if recorded is None or not isinstance(items, list) or not items:
        raise ValueError
    names: list[str] = []
    weights: list[str] = []
    for item in items:
        if not isinstance(item, dict) or set(item) != {
            "id",
            "food",
            "weight_grams",
            "nutrition",
        }:
            raise ValueError
        food = item["food"]
        if not isinstance(food, dict) or set(food) != {"id", "name"}:
            raise ValueError
        _saved_id(item["id"])
        _saved_id(food["id"]) if food["id"] is not None else None
        if not isinstance(food["name"], str):
            raise ValueError
        names.append(food["name"])
        weights.append(_decimal(item["weight_grams"]))
        _nutrition(item["nutrition"])
    _nutrition(value["totals"])
    # The Pi only presents a safe first-item weight; all IDs remain internal.
    return SavedMealListItem(_saved_id(value["id"]), recorded, tuple(names), weights[0])


def _leftover_scan_response(payload: object) -> LeftoverScanResponse:
    fields = {
        "id",
        "meal_id",
        "analysis_session_id",
        "original_weight_grams",
        "remaining_weight_grams",
        "consumed_weight_grams",
        "consumed_portion_percentage",
        "remaining_nutrition",
        "estimated_consumed_nutrition",
        "comparison_warnings",
        "created_at",
    }
    try:
        if not isinstance(payload, dict) or set(payload) != fields:
            raise ValueError
        warnings = payload["comparison_warnings"]
        created = _optional_expiry(payload, "created_at")
        if created is None or not isinstance(warnings, list):
            raise ValueError
        return LeftoverScanResponse(
            _saved_id(payload["id"]),
            _saved_id(payload["meal_id"]),
            _saved_id(payload["analysis_session_id"]),
            _decimal(payload["original_weight_grams"]),
            _decimal(payload["remaining_weight_grams"]),
            _decimal(payload["consumed_weight_grams"]),
            _decimal(payload["consumed_portion_percentage"]),
            _nutrition(payload["remaining_nutrition"]),
            _nutrition(payload["estimated_consumed_nutrition"]),
            tuple(_leftover_warning(item) for item in warnings),
            created,
        )
    except (TypeError, ValueError, KeyError) as exc:
        raise MalformedBackendResponseError(
            "backend returned an invalid leftover scan"
        ) from exc


def _leftover_warning(value: object) -> LeftoverScanWarning:
    if not isinstance(value, dict) or set(value) != {"nutrient", "code"}:
        raise ValueError
    return LeftoverScanWarning(value["nutrient"], value["code"])


def _saved_id(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError
    return value


def _additional(value: object) -> AdditionalNutrientValues:
    if not isinstance(value, dict) or set(value) != _SAVED_EXTRA:
        raise ValueError
    return AdditionalNutrientValues(
        {key: _nullable_decimal(value[key]) for key in _SAVED_EXTRA}
    )


def _nullable_decimal(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError
    _validate_saved_decimal(value)
    return value


def _meal_totals(value: object) -> MealTotals:
    if not isinstance(value, dict) or set(value) != {
        "calories",
        "protein_g",
        "carbohydrates_g",
        "fat_g",
        "fiber_g",
        *_SAVED_EXTRA,
    }:
        raise ValueError
    return MealTotals(
        *(
            _decimal(value[key])
            for key in ("calories", "protein_g", "carbohydrates_g", "fat_g", "fiber_g")
        ),
        _additional({key: value[key] for key in _SAVED_EXTRA}),
    )


def _decimal(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError
    _validate_saved_decimal(value)
    return value


def _validate_saved_decimal(value: str) -> None:
    if not Decimal(value).is_finite() or Decimal(value) < 0:
        raise ValueError


def _meal_item(value: object) -> MealItemResponse:
    if (
        not isinstance(value, dict)
        or set(value)
        - {
            "id",
            "food",
            "weight_grams",
            "nutrition",
            "nutrition_source",
            "composite_estimation",
        }
        or not {"id", "food", "weight_grams", "nutrition"} <= set(value)
    ):
        raise ValueError
    food = value["food"]
    if not isinstance(food, dict) or set(food) != {"id", "name"}:
        raise ValueError
    source = value.get("nutrition_source")
    provenance = (
        None
        if source is None
        else MealItemNutritionSource(
            source["category"],
            source["name"],
            source["reference"],
            source["is_estimated"],
        )
    )
    return MealItemResponse(
        _saved_id(value["id"]),
        SavedMealFood(food["id"], food["name"]),
        _decimal(value["weight_grams"]),
        _meal_totals(value["nutrition"]),
        provenance,
        value.get("composite_estimation", False),
    )


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
