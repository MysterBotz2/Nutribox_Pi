"""Application orchestration independent of concrete adapters."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from nutribox_pi.models import (
    AnalysisResult,
    HealthResult,
    IngredientCandidateSelection,
    IngredientVerification,
    LeftoverScanResponse,
    MealAnalysisResponse,
    MealAnalysisSelection,
    PersonalRecipeSelection,
    SavedMealPage,
)
from nutribox_pi.ports import (
    Backend,
    DeviceAuthenticationFailure,
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

    def captured_weight_grams(self) -> float:
        """Read and validate the one weight snapshot associated with a capture."""
        return validate_weight(self._weight_sensor.read_grams())

    def analyze_meal(
        self, image_path: Path, weight_grams: float | None = None
    ) -> MealAnalysisResponse | AnalysisResult:
        weight_grams = validate_weight(
            self._weight_sensor.read_grams() if weight_grams is None else weight_grams
        )
        token = (
            self._credential_provider.get_verified_device_token()
            if self._credential_provider
            else None
        )
        try:
            if token is None:
                result = self._backend.analyze_meal(
                    image_path=image_path, weight_grams=weight_grams
                )
            else:
                result = self._backend.analyze_meal(
                    image_path=image_path, weight_grams=weight_grams, device_token=token
                )
        except DeviceAuthenticationFailure:
            revoke = getattr(self._credential_provider, "confirm_revocation", None)
            if callable(revoke):
                revoke()
            raise
        if isinstance(result, MealAnalysisResponse):
            return replace(result, measured_weight_grams=weight_grams)
        return result

    def select_food_component(
        self, analysis_session_id: int, selection: MealAnalysisSelection
    ) -> MealAnalysisResponse:
        """Submit a validated food/component choice for the active session."""
        return self._continuation(
            "select_food_component", analysis_session_id, selection
        )

    def update_ingredients(
        self,
        analysis_session_id: int,
        component_id: str,
        update: IngredientVerification,
    ) -> MealAnalysisResponse:
        return self._continuation(
            "update_ingredients", analysis_session_id, component_id, update
        )

    def select_ingredient_candidate(
        self,
        analysis_session_id: int,
        component_id: str,
        selection: IngredientCandidateSelection,
    ) -> MealAnalysisResponse:
        return self._continuation(
            "select_ingredient_candidate", analysis_session_id, component_id, selection
        )

    def use_recipe(
        self,
        analysis_session_id: int,
        component_id: str,
        selection: PersonalRecipeSelection,
    ) -> MealAnalysisResponse:
        return self._continuation(
            "use_recipe", analysis_session_id, component_id, selection
        )

    def review_recipe(
        self,
        analysis_session_id: int,
        component_id: str,
        selection: PersonalRecipeSelection,
    ) -> MealAnalysisResponse:
        return self._continuation(
            "review_recipe", analysis_session_id, component_id, selection
        )

    def analyze_component_as_new(
        self, analysis_session_id: int, component_id: str
    ) -> MealAnalysisResponse:
        return self._continuation(
            "analyze_component_as_new", analysis_session_id, component_id
        )

    def save_meal(self, analysis_session_id: int) -> object:
        """Save only a backend-owned completed analysis session."""
        return self._continuation("save_meal", analysis_session_id)

    def list_saved_meals(self, limit: int, offset: int) -> SavedMealPage:
        return self._paired_operation("list_saved_meals", limit, offset)

    def get_saved_meal(self, meal_id: int) -> object:
        return self._paired_operation("get_saved_meal", meal_id)

    def create_leftover_scan(
        self, meal_id: int, analysis_session_id: int
    ) -> LeftoverScanResponse:
        return self._paired_operation(
            "create_leftover_scan", meal_id, analysis_session_id
        )

    def _paired_operation(self, operation: str, *values: object) -> object:
        token = (
            self._credential_provider.get_verified_device_token()
            if self._credential_provider
            else None
        )
        if token is None:
            raise DeviceAuthenticationFailure("device authentication failed")
        backend_operation = getattr(self._backend, operation)
        try:
            return backend_operation(*values, device_token=token)
        except DeviceAuthenticationFailure:
            revoke = getattr(self._credential_provider, "confirm_revocation", None)
            if callable(revoke):
                revoke()
            raise

    def _continuation(self, operation: str, *values: object) -> MealAnalysisResponse:
        """Invoke an adapter continuation with a freshly verified credential.

        The analysis-session identifier is supplied only by the in-memory
        continuation workflow.  Keeping it out of this controller prevents it
        becoming another state owner.
        """
        if not values or not isinstance(values[0], int):
            raise ValueError("analysis session identifier is invalid")
        session_id, *request_values = values
        token = (
            self._credential_provider.get_verified_device_token()
            if self._credential_provider
            else None
        )
        backend_operation = getattr(self._backend, operation)
        try:
            if token is None:
                return backend_operation(session_id, *request_values)
            return backend_operation(session_id, *request_values, device_token=token)
        except DeviceAuthenticationFailure:
            revoke = getattr(self._credential_provider, "confirm_revocation", None)
            if callable(revoke):
                revoke()
            raise

    def current_temperature_c(self) -> float:
        return validate_temperature(self._temperature_sensor.read_celsius())
