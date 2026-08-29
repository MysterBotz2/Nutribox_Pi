"""In-memory orchestration for typed meal-analysis continuations.

This module deliberately has no UI, HTTP, hardware, or persistence dependency.
The response held here is the sole owner of backend-issued session and component
identifiers until it is explicitly cleared.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from dataclasses import replace
from enum import StrEnum

from nutribox_pi.adapters.v1_backend import (
    AnalysisSessionError,
    ValidationConflictError,
)
from nutribox_pi.controller import NutriBoxController
from nutribox_pi.models import (
    AnalysisStatus,
    IngredientCandidateSelection,
    IngredientVerification,
    IngredientVerificationItem,
    MealAnalysisCandidate,
    MealAnalysisComponent,
    MealAnalysisResponse,
    MealAnalysisSelection,
    PersonalRecipeSelection,
)
from nutribox_pi.ports import DeviceAuthenticationFailure, RetryableBackendFailure


class ContinuationState(StrEnum):
    IDLE = "idle"
    REQUEST_IN_PROGRESS = "request_in_progress"
    RETRYABLE_ERROR = "retryable_error"
    TERMINAL_ERROR = "terminal_error"
    REVOKED = "revoked"
    CANCELLED = "cancelled"
    CALCULATED = AnalysisStatus.CALCULATED
    FOOD_NOT_RECOGNIZED = AnalysisStatus.FOOD_NOT_RECOGNIZED
    NUTRITION_REFERENCE_NOT_FOUND = AnalysisStatus.NUTRITION_REFERENCE_NOT_FOUND
    REQUIRES_FOOD_SELECTION = AnalysisStatus.REQUIRES_FOOD_SELECTION
    REQUIRES_INGREDIENT_VERIFICATION = AnalysisStatus.REQUIRES_INGREDIENT_VERIFICATION
    REQUIRES_RECIPE_CONFIRMATION = AnalysisStatus.REQUIRES_RECIPE_CONFIRMATION


class ContinuationError(RuntimeError):
    """A safe local rejection of an invalid continuation action."""


RETRYABLE_ERROR_MESSAGE = "Meal analysis is temporarily unavailable."
TERMINAL_ERROR_MESSAGE = "Meal analysis cannot continue."
REVOKED_ERROR_MESSAGE = "Device pairing was revoked."

_STATUS_STATES = {
    AnalysisStatus.CALCULATED: ContinuationState.CALCULATED,
    AnalysisStatus.FOOD_NOT_RECOGNIZED: ContinuationState.FOOD_NOT_RECOGNIZED,
    AnalysisStatus.NUTRITION_REFERENCE_NOT_FOUND: (
        ContinuationState.NUTRITION_REFERENCE_NOT_FOUND
    ),
    AnalysisStatus.REQUIRES_FOOD_SELECTION: ContinuationState.REQUIRES_FOOD_SELECTION,
    AnalysisStatus.REQUIRES_INGREDIENT_VERIFICATION: (
        ContinuationState.REQUIRES_INGREDIENT_VERIFICATION
    ),
    AnalysisStatus.REQUIRES_RECIPE_CONFIRMATION: (
        ContinuationState.REQUIRES_RECIPE_CONFIRMATION
    ),
}


class MealAnalysisContinuationWorkflow:
    """Own one active typed analysis response and its continuation lifecycle."""

    def __init__(
        self,
        controller: NutriBoxController,
        executor_factory: Callable[[], Executor] | None = None,
    ) -> None:
        self._controller = controller
        self._executor = (
            executor_factory()
            if executor_factory is not None
            else ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="nutribox-analysis"
            )
        )
        self._response: MealAnalysisResponse | None = None
        self._state = ContinuationState.IDLE
        self._error_message: str | None = None
        self._future: Future[MealAnalysisResponse] | None = None
        self._pending_generation: int | None = None
        self._generation = 0
        self._retry: Callable[[], MealAnalysisResponse] | None = None
        self._closed = False

    @property
    def state(self) -> ContinuationState:
        return self._state

    @property
    def response(self) -> MealAnalysisResponse | None:
        return self._response

    @property
    def error_message(self) -> str | None:
        return self._error_message

    @property
    def retry_available(self) -> bool:
        return (
            self._state is ContinuationState.RETRYABLE_ERROR and self._retry is not None
        )

    @property
    def food_candidate_names(self) -> tuple[str, ...]:
        """Safe presentation names for the current food-selection response."""
        return tuple(candidate.name for _, candidate in self._food_candidates())

    def select_food_candidate(self, index: int) -> bool:
        """Resolve a renderer-provided ordinal without exposing backend IDs."""
        if isinstance(index, bool) or not isinstance(index, int):
            raise ContinuationError("meal analysis selection is unavailable")
        choices = self._food_candidates()
        if not 0 <= index < len(choices):
            raise ContinuationError("meal analysis selection is unavailable")
        component, candidate = choices[index]
        assert candidate.candidate_id is not None
        return self.select_food_component(
            MealAnalysisSelection(component.component_id, candidate.candidate_id)
        )

    def accept_initial_response(self, response: MealAnalysisResponse) -> None:
        """Atomically replace previous session data after initial analysis."""
        if not isinstance(response, MealAnalysisResponse):
            raise ContinuationError("analysis response is invalid")
        self._clear(increment=True)
        self._replace_response(response)

    def select_food_component(self, selection: MealAnalysisSelection) -> bool:
        self._require_state(ContinuationState.REQUIRES_FOOD_SELECTION)
        component = self._component(selection.component_id)
        if selection.candidate_id is None or selection.candidate_id not in {
            candidate.candidate_id for candidate in component.candidates
        }:
            raise ContinuationError("meal analysis selection is unavailable")
        session_id = self._session_id()
        return self._submit(
            lambda: self._controller.select_food_component(session_id, selection)
        )

    def update_ingredients(
        self, component_id: str, update: IngredientVerification
    ) -> bool:
        self._require_state(ContinuationState.REQUIRES_INGREDIENT_VERIFICATION)
        component = self._component(component_id)
        allowed = {
            ingredient.ingredient_id for ingredient in component.suggested_ingredients
        }
        if any(
            item.ingredient_id is not None and item.ingredient_id not in allowed
            for item in update.ingredients
        ):
            raise ContinuationError("meal analysis ingredient is unavailable")
        session_id = self._session_id()
        return self._submit(
            lambda: self._controller.update_ingredients(
                session_id, component_id, update
            )
        )

    @property
    def ingredient_component_names(self) -> tuple[str, ...]:
        """Safe labels for ingredient-confirmation component navigation."""
        return tuple(component.recognized_name for component in self._ingredients())

    def ingredient_names(self, component_index: int) -> tuple[str, ...]:
        """Return presentation-only ingredient names for one component."""
        return tuple(
            ingredient.name
            for ingredient in self._ingredient_component(
                component_index
            ).suggested_ingredients
        )

    def ingredient_initial_inclusions(self, component_index: int) -> tuple[bool, ...]:
        """Return the authoritative backend-supplied initial checkbox state."""
        return tuple(
            ingredient.included
            for ingredient in self._ingredient_component(
                component_index
            ).suggested_ingredients
        )

    def confirm_ingredient_ordinals(
        self, component_index: int, inclusions: tuple[bool, ...]
    ) -> bool:
        """Submit a renderer ordinal projection without disclosing identifiers."""
        component = self._ingredient_component(component_index)
        ingredients = component.suggested_ingredients
        if len(inclusions) != len(ingredients) or not any(inclusions):
            raise ContinuationError("meal analysis ingredient is unavailable")
        if any(not isinstance(included, bool) for included in inclusions):
            raise ContinuationError("meal analysis ingredient is unavailable")
        update = IngredientVerification(
            tuple(
                IngredientVerificationItem(
                    ingredient.name,
                    included,
                    ingredient.ingredient_id,
                    ingredient.weight_grams,
                )
                for ingredient, included in zip(ingredients, inclusions, strict=True)
            )
        )
        return self.update_ingredients(component.component_id, update)

    def select_ingredient_candidate(
        self, component_id: str, selection: IngredientCandidateSelection
    ) -> bool:
        self._require_state(ContinuationState.REQUIRES_INGREDIENT_VERIFICATION)
        component = self._component(component_id)
        ingredient = next(
            (
                item
                for item in component.suggested_ingredients
                if item.ingredient_id == selection.ingredient_id
            ),
            None,
        )
        if ingredient is None or selection.candidate_id not in {
            candidate.candidate_id for candidate in ingredient.candidates
        }:
            raise ContinuationError("meal analysis candidate is unavailable")
        session_id = self._session_id()
        return self._submit(
            lambda: self._controller.select_ingredient_candidate(
                session_id, component_id, selection
            )
        )

    def use_recipe(self, component_id: str, selection: PersonalRecipeSelection) -> bool:
        self._require_recipe(component_id, selection)
        session_id = self._session_id()
        return self._submit(
            lambda: self._controller.use_recipe(session_id, component_id, selection)
        )

    def review_recipe(
        self, component_id: str, selection: PersonalRecipeSelection
    ) -> bool:
        self._require_recipe(component_id, selection)
        session_id = self._session_id()
        return self._submit(
            lambda: self._controller.review_recipe(session_id, component_id, selection)
        )

    def analyze_component_as_new(self, component_id: str) -> bool:
        self._require_state(ContinuationState.REQUIRES_RECIPE_CONFIRMATION)
        self._component(component_id)
        session_id = self._session_id()
        return self._submit(
            lambda: self._controller.analyze_component_as_new(session_id, component_id)
        )

    def retry(self) -> bool:
        if self._state is not ContinuationState.RETRYABLE_ERROR or self._retry is None:
            return False
        action = self._retry
        self._retry = None
        return self._submit(action)

    def tick(self) -> None:
        future = self._future
        if future is None or not future.done():
            return
        self._future = None
        generation = self._pending_generation
        self._pending_generation = None
        if generation != self._generation or self._closed:
            return
        try:
            response = future.result()
        except DeviceAuthenticationFailure:
            self._clear(increment=True)
            self._state = ContinuationState.REVOKED
            self._error_message = REVOKED_ERROR_MESSAGE
        except RetryableBackendFailure:
            self._state = ContinuationState.RETRYABLE_ERROR
            self._error_message = RETRYABLE_ERROR_MESSAGE
        except (AnalysisSessionError, ValidationConflictError, Exception):
            self._response = None
            self._clear_retry()
            self._state = ContinuationState.TERMINAL_ERROR
            self._error_message = TERMINAL_ERROR_MESSAGE
        else:
            if not isinstance(response, MealAnalysisResponse):
                self._clear_retry()
                self._state = ContinuationState.TERMINAL_ERROR
                self._error_message = TERMINAL_ERROR_MESSAGE
                return
            self._replace_response(response)

    def home(self) -> None:
        self._clear(increment=True)

    def retake(self) -> None:
        self._clear(increment=True)

    def cancel(self) -> None:
        self._clear(increment=True)
        self._state = ContinuationState.CANCELLED

    def revoke(self) -> None:
        """Discard session state after pairing confirms credential revocation."""
        self._clear(increment=True)
        self._state = ContinuationState.REVOKED
        self._error_message = REVOKED_ERROR_MESSAGE

    def close(self) -> None:
        if self._closed:
            return
        self._clear(increment=True)
        self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _replace_response(self, response: MealAnalysisResponse) -> None:
        state = _STATUS_STATES[response.status]
        if state in {
            ContinuationState.CALCULATED,
            ContinuationState.FOOD_NOT_RECOGNIZED,
            ContinuationState.NUTRITION_REFERENCE_NOT_FOUND,
        }:
            response = replace(
                response,
                analysis_session_id=None,
                analysis_session_expires_at=None,
                components=None,
            )
        self._response = response
        self._retry = None
        self._error_message = None
        self._state = state

    def _submit(self, action: Callable[[], MealAnalysisResponse]) -> bool:
        if self._closed or self._state is ContinuationState.REQUEST_IN_PROGRESS:
            return False
        self._state = ContinuationState.REQUEST_IN_PROGRESS
        self._error_message = None
        self._future = self._executor.submit(action)
        self._pending_generation = self._generation
        self._retry = action
        return True

    def _session_id(self) -> int:
        response = self._response
        if response is None or response.analysis_session_id is None:
            raise ContinuationError("meal analysis session is unavailable")
        return response.analysis_session_id

    def _component(self, component_id: str) -> MealAnalysisComponent:
        response = self._response
        if response is None or response.components is None:
            raise ContinuationError("meal analysis component is unavailable")
        component = next(
            (item for item in response.components if item.component_id == component_id),
            None,
        )
        if component is None:
            raise ContinuationError("meal analysis component is unavailable")
        return component

    def _food_candidates(
        self,
    ) -> tuple[tuple[MealAnalysisComponent, MealAnalysisCandidate], ...]:
        response = self._response
        if (
            self._state is not ContinuationState.REQUIRES_FOOD_SELECTION
            or response is None
            or response.analysis_session_id is None
            or response.components is None
        ):
            return ()
        return tuple(
            (component, candidate)
            for component in response.components
            for candidate in component.candidates
            if candidate.candidate_id is not None
        )

    def _ingredients(self) -> tuple[MealAnalysisComponent, ...]:
        response = self._response
        if (
            self._state is not ContinuationState.REQUIRES_INGREDIENT_VERIFICATION
            or response is None
            or response.analysis_session_id is None
            or response.components is None
        ):
            return ()
        return response.components

    def _ingredient_component(self, index: int) -> MealAnalysisComponent:
        if isinstance(index, bool) or not isinstance(index, int):
            raise ContinuationError("meal analysis ingredient is unavailable")
        components = self._ingredients()
        if not 0 <= index < len(components):
            raise ContinuationError("meal analysis ingredient is unavailable")
        component = components[index]
        if not component.suggested_ingredients:
            raise ContinuationError("meal analysis ingredient is unavailable")
        return component

    def _require_state(self, state: ContinuationState) -> None:
        if self._state is not state:
            raise ContinuationError("meal analysis action is unavailable")
        self._session_id()

    def _require_recipe(
        self, component_id: str, selection: PersonalRecipeSelection
    ) -> None:
        self._require_state(ContinuationState.REQUIRES_RECIPE_CONFIRMATION)
        component = self._component(component_id)
        if selection.recipe_id not in {
            recipe.recipe_id for recipe in component.recipe_matches
        }:
            raise ContinuationError("meal analysis recipe is unavailable")

    def _clear(self, *, increment: bool) -> None:
        if increment:
            self._generation += 1
        future = self._future
        self._future = None
        self._pending_generation = None
        if future is not None:
            future.cancel()
        self._response = None
        self._clear_retry()
        self._error_message = None
        self._state = ContinuationState.IDLE

    def _clear_retry(self) -> None:
        self._retry = None
