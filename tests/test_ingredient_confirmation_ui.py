from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import replace
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
    normalize_ingredient_name,
)
from nutribox_pi.models import (
    AnalysisStatus,
    MealAnalysisCandidate,
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

    def select_ingredient_candidate(
        self, *values: object, **_: object
    ) -> MealAnalysisResponse:
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


def test_edit_and_add_are_local_until_confirmation(tmp_path: Path) -> None:
    flow, backend = _workflow(tmp_path, ingredients=2)
    flow.edit_ingredient(0)
    assert flow.screen is UIScreen.INGREDIENT_EDITOR
    assert flow.ingredient_editor is not None
    assert flow.ingredient_editor.draft == "ingredient 0"
    flow.editor_clear()
    flow.append_editor_text("  Fresh  ingredient  ")
    flow.apply_ingredient_editor()
    assert flow.ingredient_verification.names[0] == "Fresh ingredient"
    assert flow.ingredient_verification.included[0] is True
    flow.add_ingredient()
    flow.append_editor_text("manual")
    flow.apply_ingredient_editor()
    assert flow.ingredient_verification.names[-1] == "manual"
    assert flow.ingredient_verification.included[-1] is True
    assert backend.calls == []
    flow.confirm_ingredients()
    assert [item.name for item in backend.calls[0][2].ingredients] == [
        "Fresh ingredient",
        "ingredient 1",
        "manual",
    ]


def test_editor_cancel_invalid_and_duplicate_drafts_do_not_change_rows(
    tmp_path: Path,
) -> None:
    flow, _ = _workflow(tmp_path, ingredients=2)
    original = flow.ingredient_verification.names
    flow.edit_ingredient(0)
    flow.editor_clear()
    flow.append_editor_text("ingredient 1")
    flow.apply_ingredient_editor()
    assert flow.screen is UIScreen.INGREDIENT_EDITOR
    assert flow.ingredient_editor is not None and flow.ingredient_editor.error
    flow.cancel_ingredient_editor()
    assert flow.ingredient_verification.names == original
    assert normalize_ingredient_name(" \n ") is None
    assert normalize_ingredient_name("x" * 161) is None
    assert normalize_ingredient_name("Munggo") == "Munggo"


def test_editor_and_checkbox_rectangles_are_separate() -> None:
    view = IngredientVerificationView(("meal",), ("rice",), (True,), 0, 0, False, False)
    buttons = buttons_for(
        UIScreen.REQUIRES_INGREDIENT_VERIFICATION, ingredient_verification=view
    )
    checkbox = next(
        button for button in buttons if button.action is UIAction.TOGGLE_INGREDIENT_0
    )
    edit = next(
        button for button in buttons if button.action is UIAction.EDIT_INGREDIENT_0
    )
    assert checkbox.rectangle.x + checkbox.rectangle.width <= edit.rectangle.x


def test_unresolved_response_opens_safe_candidate_screen_and_submits_once(
    tmp_path: Path,
) -> None:
    flow, backend = _workflow(tmp_path, ingredients=1)
    source = _response(ingredients=1)
    original_component = source.components[0]
    unresolved_ingredient = replace(
        original_component.suggested_ingredients[0],
        resolution_status="requires_food_selection",
        candidates=(
            MealAnalysisCandidate(
                "rice, cooked", "123e4567-e89b-12d3-a456-426614175000"
            ),
            MealAnalysisCandidate("rice, raw", "123e4567-e89b-12d3-a456-426614175001"),
        ),
    )
    response = replace(
        source,
        components=(
            replace(original_component, suggested_ingredients=(unresolved_ingredient,)),
        ),
    )
    flow.continuation.accept_initial_response(response)
    flow._show_analysis_response(response)
    assert flow.screen is UIScreen.INGREDIENT_CANDIDATE_SELECTION
    assert flow.ingredient_candidates.selected_index is None
    assert "175000" not in repr(flow.ingredient_candidates)
    flow.select_ingredient_candidate(1)
    flow.continue_ingredient_candidate()
    flow.continue_ingredient_candidate()
    assert len(backend.calls) == 1
    assert backend.calls[0][0] == 42
    selection = backend.calls[0][2]
    assert selection.candidate_id.endswith("5001")
