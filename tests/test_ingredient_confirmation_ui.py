from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path

from nutribox_pi.adapters import pygame_device_ui
from nutribox_pi.adapters.mock_hardware import (
    SimulatedTemperatureSensor,
    SimulatedWeightSensor,
)
from nutribox_pi.adapters.simulated_camera import SimulatedCamera
from nutribox_pi.continuation import MealAnalysisContinuationWorkflow
from nutribox_pi.controller import NutriBoxController
from nutribox_pi.device_ui import (
    FOOD_SELECTION_PAGE_SIZE,
    IngredientVerificationView,
    MealCaptureWorkflow,
    TemporaryCaptureStore,
    UIAction,
    UIScreen,
    buttons_for,
)
from nutribox_pi.models import (
    AnalysisStatus,
    MealAnalysisComponent,
    MealAnalysisResponse,
    RecognitionSource,
    RecognizedFood,
    RequiresIngredientVerificationResponse,
    SuggestedIngredient,
)

COMPONENT_A = "123e4567-e89b-12d3-a456-426614174000"
COMPONENT_B = "123e4567-e89b-12d3-a456-426614174001"


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

    def update_ingredients(self, *values: object, **_: object) -> MealAnalysisResponse:
        self.calls.append(values)
        return self.response

    def analyze_meal(self, *_: object, **__: object) -> MealAnalysisResponse:
        return self.response


def _ingredient(index: int, included: bool) -> SuggestedIngredient:
    return SuggestedIngredient(
        ingredient_id=f"123e4567-e89b-12d3-a456-42661417{index:04d}",
        name=f"ingredient {index}",
        suggested_proportion="0.1",
        ingredient_source="suggested",
        included=included,
        weight_source="estimated",
        resolution_status="pending",
        weight_grams="25",
    )


def _component(component_id: str, start: int, count: int) -> MealAnalysisComponent:
    return MealAnalysisComponent(
        component_id=component_id,
        recognized_name=f"meal part {start}",
        raw_estimated_proportion="1",
        normalized_proportion="1",
        estimated_weight_grams="250",
        weight_source="estimated",
        resolution_status="requires_ingredient_verification",
        nutrition_source=None,
        resolved_reference=None,
        candidates=(),
        nutrition=None,
        suggested_ingredients=tuple(
            _ingredient(start + index, index % 2 == 0) for index in range(count)
        ),
    )


def _response(components: int = 1, ingredients: int = 5) -> MealAnalysisResponse:
    component_values = tuple(
        _component(
            COMPONENT_A if index == 0 else COMPONENT_B,
            index * 10,
            ingredients,
        )
        for index in range(components)
    )
    return RequiresIngredientVerificationResponse(
        status=AnalysisStatus.REQUIRES_INGREDIENT_VERIFICATION,
        recognized_foods=(RecognizedFood("meal"),),
        recognition_source=RecognitionSource.SIMULATED,
        analysis_session_id=42,
        components=component_values,
    )


def _workflow(
    tmp_path: Path, components: int = 1, ingredients: int = 5
) -> tuple[MealCaptureWorkflow, Backend]:
    response = _response(components, ingredients)
    backend = Backend(response)
    controller = NutriBoxController(
        backend, SimulatedWeightSensor(), SimulatedTemperatureSensor()
    )
    flow = MealCaptureWorkflow(
        SimulatedCamera(),
        controller,
        TemporaryCaptureStore(lambda **_: str(tmp_path / "capture")),
    )
    flow.continuation.close()
    flow.continuation = MealAnalysisContinuationWorkflow(controller, InlineExecutor)
    flow.continuation.accept_initial_response(response)
    flow._show_analysis_response(response)
    return flow, backend


def test_backend_initial_checkbox_state_and_safe_projection(tmp_path: Path) -> None:
    flow, _ = _workflow(tmp_path)

    assert flow.screen is UIScreen.REQUIRES_INGREDIENT_VERIFICATION
    assert flow.ingredient_verification.included == (True, False, True, False, True)
    rendered = repr(flow.ingredient_verification)
    assert COMPONENT_A not in rendered
    assert "ingredient_id" not in rendered


def test_toggle_and_pagination_use_only_visible_ordinals(tmp_path: Path) -> None:
    flow, _ = _workflow(tmp_path)
    flow.toggle_ingredient(1)
    assert flow.ingredient_verification.included[1] is True
    flow.next_ingredient_page()
    assert flow.ingredient_verification.page == 1
    assert (
        flow.ingredient_verification.names[FOOD_SELECTION_PAGE_SIZE] == "ingredient 4"
    )
    flow.previous_ingredient_page()
    assert flow.ingredient_verification.included[1] is True


def test_component_navigation_preserves_independent_selection(tmp_path: Path) -> None:
    flow, _ = _workflow(tmp_path, components=2, ingredients=2)
    flow.toggle_ingredient(1)
    flow.next_ingredient_component()
    assert flow.ingredient_verification.component_index == 1
    assert flow.ingredient_verification.included == (True, False)
    flow.previous_ingredient_component()
    assert flow.ingredient_verification.included == (True, True)


def test_confirm_submits_all_named_ingredients_once_with_private_ids(
    tmp_path: Path,
) -> None:
    flow, backend = _workflow(tmp_path, ingredients=2)
    flow.confirm_ingredients()
    flow.confirm_ingredients()

    assert flow.ingredient_verification.request_in_progress
    assert len(backend.calls) == 1
    session_id, component_id, update = backend.calls[0]
    assert session_id == 42
    assert component_id == COMPONENT_A
    assert [item.included for item in update.ingredients] == [True, False]
    assert [item.name for item in update.ingredients] == [
        "ingredient 0",
        "ingredient 1",
    ]
    assert "ingredient_id" not in repr(flow.ingredient_verification)


def test_confirm_is_disabled_when_no_ingredient_is_selected(tmp_path: Path) -> None:
    flow, backend = _workflow(tmp_path, ingredients=2)
    flow.toggle_ingredient(0)
    assert not any(flow.ingredient_verification.included)
    confirm = next(
        button
        for button in buttons_for(
            UIScreen.REQUIRES_INGREDIENT_VERIFICATION,
            ingredient_verification=flow.ingredient_verification,
        )
        if button.action is UIAction.CONFIRM_INGREDIENTS
    )
    assert not confirm.enabled
    flow.confirm_ingredients()
    assert backend.calls == []


def test_renderer_dispatches_rescan_and_confirmation_without_http_construction() -> (
    None
):
    calls: list[str] = []

    class Workflow:
        screen = UIScreen.REQUIRES_INGREDIENT_VERIFICATION

        def confirm_ingredients(self) -> None:
            calls.append("confirm")

        def retake(self) -> None:
            calls.append("rescan")

    workflow = Workflow()
    pygame_device_ui._apply_action(
        object(), object(), object(), workflow, UIAction.CONFIRM_INGREDIENTS
    )
    pygame_device_ui._apply_action(
        object(), object(), object(), workflow, UIAction.RESCAN
    )
    assert calls == ["confirm", "rescan"]


def test_view_cannot_hold_identifiers() -> None:
    view = IngredientVerificationView(("meal",), ("rice",), (True,), 0, 0, False, False)
    assert view.names == ("rice",)
    assert "id" not in view.__dataclass_fields__
