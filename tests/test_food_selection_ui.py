from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path

import pytest

from nutribox_pi.adapters.mock_hardware import (
    SimulatedTemperatureSensor,
    SimulatedWeightSensor,
)
from nutribox_pi.adapters.simulated_camera import SimulatedCamera
from nutribox_pi.continuation import MealAnalysisContinuationWorkflow
from nutribox_pi.controller import NutriBoxController
from nutribox_pi.device_ui import (
    FOOD_SELECTION_PAGE_SIZE,
    FoodSelectionView,
    MealCaptureWorkflow,
    TemporaryCaptureStore,
    UIAction,
    UIScreen,
    buttons_for,
)
from nutribox_pi.models import (
    AnalysisStatus,
    MealAnalysisCandidate,
    MealAnalysisComponent,
    MealAnalysisResponse,
    RecognitionSource,
    RecognizedFood,
    RequiresFoodSelectionResponse,
)
from nutribox_pi.ports import DeviceAuthenticationFailure, RetryableBackendFailure

COMPONENT_ID = "123e4567-e89b-12d3-a456-426614174000"


class InlineExecutor:
    def submit(
        self, action: Callable[[], MealAnalysisResponse]
    ) -> Future[MealAnalysisResponse]:
        future: Future[MealAnalysisResponse] = Future()
        try:
            future.set_result(action())
        except BaseException as exc:
            future.set_exception(exc)
        return future

    def shutdown(self, **_: object) -> None:
        return None


class Backend:
    def __init__(self, response: MealAnalysisResponse) -> None:
        self.response = response
        self.calls: list[tuple[object, ...]] = []
        self.failure: Exception | None = None

    def select_food_component(
        self, *values: object, **kwargs: object
    ) -> MealAnalysisResponse:
        self.calls.append(values)
        if self.failure is not None:
            raise self.failure
        return self.response

    def health(self) -> object:
        raise AssertionError

    def analyze_meal(self, *_: object, **__: object) -> MealAnalysisResponse:
        return self.response


def selection_response(count: int = 5) -> RequiresFoodSelectionResponse:
    candidates = tuple(
        MealAnalysisCandidate(
            f"candidate {index} " + "very long name " * 8,
            f"123e4567-e89b-12d3-a456-426614174{index:03d}",
        )
        for index in range(count)
    )
    component = MealAnalysisComponent(
        component_id=COMPONENT_ID,
        recognized_name="meal",
        raw_estimated_proportion="1",
        normalized_proportion="1",
        estimated_weight_grams="250",
        weight_source="manual",
        resolution_status="pending",
        nutrition_source=None,
        resolved_reference=None,
        candidates=candidates,
        nutrition=None,
    )
    return RequiresFoodSelectionResponse(
        status=AnalysisStatus.REQUIRES_FOOD_SELECTION,
        recognized_foods=(RecognizedFood("meal"),),
        recognition_source=RecognitionSource.SIMULATED,
        analysis_session_id=42,
        components=(component,),
    )


def workflow(tmp_path: Path, count: int = 5) -> tuple[MealCaptureWorkflow, Backend]:
    response = selection_response(count)
    backend = Backend(response)
    controller = NutriBoxController(
        backend,
        SimulatedWeightSensor(),
        SimulatedTemperatureSensor(),
    )
    store = TemporaryCaptureStore(lambda **_: str(tmp_path / "capture"))
    flow = MealCaptureWorkflow(SimulatedCamera(), controller, store)
    flow.continuation.close()
    flow.continuation = MealAnalysisContinuationWorkflow(controller, InlineExecutor)
    flow.continuation.accept_initial_response(response)
    flow._show_analysis_response(response)
    return flow, backend


def test_selection_opens_without_an_automatic_choice(tmp_path: Path) -> None:
    flow, _ = workflow(tmp_path)
    assert flow.screen is UIScreen.FOOD_SELECTION
    assert flow.food_selection.selected_index is None
    continue_button = next(
        button
        for button in buttons_for(
            UIScreen.FOOD_SELECTION, food_selection=flow.food_selection
        )
        if button.action is UIAction.FOOD_CONTINUE
    )
    assert not continue_button.enabled


def test_safe_ordinal_selection_changes_and_submits_once(tmp_path: Path) -> None:
    flow, backend = workflow(tmp_path)
    flow.select_food_candidate(0)
    flow.select_food_candidate(1)
    assert flow.food_selection.selected_index == 1
    flow.continue_food_selection()
    flow.continue_food_selection()
    assert flow.food_selection.request_in_progress
    assert len(backend.calls) == 1
    flow.tick_continuation()
    assert flow.screen is UIScreen.FOOD_SELECTION
    assert backend.calls[0][0] == 42
    assert all(
        identifier not in repr(flow.food_selection) for identifier in (COMPONENT_ID,)
    )


def test_candidate_pagination_is_bounded_and_preserves_safe_index(
    tmp_path: Path,
) -> None:
    flow, _ = workflow(tmp_path, FOOD_SELECTION_PAGE_SIZE + 2)
    flow.next_food_selection_page()
    assert flow.food_selection.page == 1
    flow.next_food_selection_page()
    assert flow.food_selection.page == 1
    flow.select_food_candidate(1)
    assert flow.food_selection.selected_index == FOOD_SELECTION_PAGE_SIZE + 1
    flow.previous_food_selection_page()
    assert flow.food_selection.page == 0
    for button in buttons_for(
        UIScreen.FOOD_SELECTION, food_selection=flow.food_selection
    ):
        rectangle = button.rectangle
        assert rectangle.x >= 0 and rectangle.y >= 0
        assert (
            rectangle.x + rectangle.width <= 800
            and rectangle.y + rectangle.height <= 480
        )


def test_repeated_selection_response_replaces_candidates_and_selection(
    tmp_path: Path,
) -> None:
    flow, _ = workflow(tmp_path, 5)
    flow.select_food_candidate(0)
    replacement = selection_response(1)
    flow.continuation.accept_initial_response(replacement)
    flow._show_analysis_response(replacement)
    assert flow.food_selection.names == flow.continuation.food_candidate_names
    assert len(flow.food_selection.names) == 1
    assert flow.food_selection.selected_index is None


def test_retryable_failure_retains_selection_until_explicit_retry(
    tmp_path: Path,
) -> None:
    flow, backend = workflow(tmp_path)
    flow.select_food_candidate(0)
    backend.failure = RetryableBackendFailure()
    flow.continue_food_selection()
    flow.tick_continuation()
    assert flow.food_selection.retry_available
    assert flow.food_selection.selected_index == 0
    assert len(backend.calls) == 1
    backend.failure = None
    flow.retry_food_selection()
    flow.retry_food_selection()
    assert len(backend.calls) == 2


@pytest.mark.parametrize("method", ["back", "home", "retake"])
def test_navigation_clears_selection_without_submission(
    tmp_path: Path, method: str
) -> None:
    flow, backend = workflow(tmp_path)
    flow.select_food_candidate(0)
    if method == "retake":
        flow._start_preview = lambda: setattr(flow, "screen", UIScreen.HOME)  # type: ignore[method-assign]
    getattr(flow, method)()
    assert flow.food_selection == FoodSelectionView((), 0, None, False, False)
    assert backend.calls == []


@pytest.mark.parametrize(
    "status",
    (
        AnalysisStatus.CALCULATED,
        AnalysisStatus.FOOD_NOT_RECOGNIZED,
        AnalysisStatus.NUTRITION_REFERENCE_NOT_FOUND,
        AnalysisStatus.REQUIRES_INGREDIENT_VERIFICATION,
        AnalysisStatus.REQUIRES_RECIPE_CONFIRMATION,
    ),
)
def test_continuation_response_uses_its_exact_outcome_screen(
    tmp_path: Path, status: AnalysisStatus
) -> None:
    flow, backend = workflow(tmp_path)
    backend.response = MealAnalysisResponse(
        status=status,
        recognized_foods=(RecognizedFood("meal"),),
        recognition_source=RecognitionSource.SIMULATED,
    )
    flow.select_food_candidate(0)
    flow.continue_food_selection()
    flow.tick_continuation()
    assert flow.screen.value == status.value


def test_device_authentication_failure_clears_candidates_and_returns_home(
    tmp_path: Path,
) -> None:
    flow, backend = workflow(tmp_path)
    backend.failure = DeviceAuthenticationFailure()
    flow.select_food_candidate(0)
    flow.continue_food_selection()
    flow.tick_continuation()
    assert flow.screen is UIScreen.HOME
    assert flow.food_selection == FoodSelectionView((), 0, None, False, False)
