"""Replaceable hardware and network boundaries."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from nutribox_pi.models import (
    AnalysisResult,
    CameraAvailability,
    CaptureResult,
    DeviceIdentity,
    FoodRecognitionResult,
    HealthResult,
    IngredientCandidateSelection,
    IngredientVerification,
    MealAnalysisResponse,
    MealAnalysisSelection,
    PairingSession,
    PairingStatusResponse,
    PersonalRecipeSelection,
    PreviewFrame,
)


class RetryableBackendFailure(RuntimeError):
    """A request may be retried only after another explicit user action."""


class DeviceAuthenticationFailure(RuntimeError):
    """The backend confirmed that the stored device credential is invalid."""


class WeightSensor(Protocol):
    def read_grams(self) -> float: ...


class TemperatureSensor(Protocol):
    def read_celsius(self) -> float: ...


class Backend(Protocol):
    def health(self) -> HealthResult: ...

    def analyze_meal(
        self, image_path: Path, weight_grams: float, device_token: str | None = None
    ) -> MealAnalysisResponse | AnalysisResult: ...

    def select_food_component(
        self,
        analysis_session_id: int,
        selection: MealAnalysisSelection,
        device_token: str | None = None,
    ) -> MealAnalysisResponse: ...

    def update_ingredients(
        self,
        analysis_session_id: int,
        component_id: str,
        update: IngredientVerification,
        device_token: str | None = None,
    ) -> MealAnalysisResponse: ...

    def select_ingredient_candidate(
        self,
        analysis_session_id: int,
        component_id: str,
        selection: IngredientCandidateSelection,
        device_token: str | None = None,
    ) -> MealAnalysisResponse: ...

    def use_recipe(
        self,
        analysis_session_id: int,
        component_id: str,
        selection: PersonalRecipeSelection,
        device_token: str | None = None,
    ) -> MealAnalysisResponse: ...

    def review_recipe(
        self,
        analysis_session_id: int,
        component_id: str,
        selection: PersonalRecipeSelection,
        device_token: str | None = None,
    ) -> MealAnalysisResponse: ...

    def analyze_component_as_new(
        self,
        analysis_session_id: int,
        component_id: str,
        device_token: str | None = None,
    ) -> MealAnalysisResponse: ...


class VerifiedDeviceCredentialProvider(Protocol):
    def get_verified_device_token(self) -> str | None: ...


class FoodRecognizer(Protocol):
    def recognize_food(self, image_path: Path) -> FoodRecognitionResult: ...


class DevicePairing(Protocol):
    def start(self, device_name: str) -> PairingSession: ...

    def status(self, session_id: str, device_token: str) -> PairingStatusResponse: ...

    def device_me(self, device_token: str) -> DeviceIdentity: ...


class Camera(Protocol):
    def availability(self) -> CameraAvailability: ...

    def capture(self, output_path: Path, overwrite: bool = False) -> CaptureResult: ...


class PreviewSession(Protocol):
    def read_frame(self) -> PreviewFrame | None: ...

    def capture(self, output_path: Path, overwrite: bool = False) -> CaptureResult: ...

    def close(self) -> bool: ...


class PreviewCamera(Camera, Protocol):
    def open_preview_session(self) -> PreviewSession | None: ...
