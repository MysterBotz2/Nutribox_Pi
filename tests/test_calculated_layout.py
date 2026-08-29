from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

from nutribox_pi.adapters import pygame_device_ui
from nutribox_pi.device_ui import (
    CALCULATED_ACTIONS,
    CALCULATED_HEADER,
    CALCULATED_LEFT_PANEL,
    CALCULATED_PAGINATION,
    CALCULATED_RIGHT_PANEL,
    CALCULATED_ROWS,
    CALCULATED_TAB_RECTS,
    CALCULATED_THUMBNAIL,
    DISPLAY_SIZE,
    MealCaptureWorkflow,
    NutritionTab,
    NutritionView,
    UIAction,
    UIScreen,
    buttons_for,
)
from nutribox_pi.models import (
    AnalysisStatus,
    CalculatedResponse,
    NutritionValues,
    RecognitionSource,
    RecognizedFood,
)
from nutribox_pi.ui_preferences import Language


def _response(*, nullable: bool = False) -> CalculatedResponse:
    values = {
        "calories": "123456789.123",
        "protein_g": "20.000",
        "carbohydrates_g": "30.000",
        "fat_g": "4.000",
        "fiber_g": "5.000",
        "energy_kj": "516132716.444",
        "saturated_fat_g": "1.000",
        "sugars_g": "2.000",
        "sodium_mg": "3.000",
        "cholesterol_mg": "4.000",
        "omega_3_g": "5.000",
        "omega_6_g": "6.000",
        "calcium_mg": "7.000",
        "iron_mg": "8.000",
        "potassium_mg": "9.000",
        "magnesium_mg": "10.000",
        "zinc_mg": "11.000",
        "phosphorus_mg": "12.000",
        "vitamin_a_mcg_rae": "13.000",
        "vitamin_b6_mg": "14.000",
        "vitamin_c_mg": "15.000",
        "vitamin_b12_mcg": "16.000",
        "folate_mcg_dfe": "17.000",
        "vitamin_d_mcg": "18.000",
        "niacin_mg": "19.000",
    }
    if nullable:
        for key in tuple(values):
            if key not in {
                "calories",
                "protein_g",
                "carbohydrates_g",
                "fat_g",
                "fiber_g",
            }:
                values[key] = None
    return CalculatedResponse(
        status=AnalysisStatus.CALCULATED,
        recognized_foods=(RecognizedFood(("long meal " * 12).strip()),),
        recognition_source=RecognitionSource.SIMULATED,
        nutrition=NutritionValues(
            values["calories"],
            values["protein_g"],
            values["carbohydrates_g"],
            values["fat_g"],
            values["fiber_g"],
            values=values,
        ),
        weight_grams="999999999.999",
    )


def _overlap(first: object, second: object) -> bool:
    a = first
    b = second
    return (
        a.x < b.x + b.width
        and b.x < a.x + a.width
        and a.y < b.y + b.height
        and b.y < a.y + a.height
    )


def _workflow(response: CalculatedResponse, language: Language) -> object:
    return SimpleNamespace(
        analysis_response=response,
        language=language,
        nutrition_view=NutritionView(),
        simulated_weight=False,
        screen=UIScreen.CALCULATED,
        pairing=None,
    )


def test_calculated_layout_regions_and_actions_are_contained_and_non_overlapping() -> (
    None
):
    assert not _overlap(CALCULATED_HEADER, CALCULATED_LEFT_PANEL)
    assert not _overlap(CALCULATED_HEADER, CALCULATED_RIGHT_PANEL)
    assert not _overlap(CALCULATED_LEFT_PANEL, CALCULATED_RIGHT_PANEL)
    assert not _overlap(CALCULATED_LEFT_PANEL, CALCULATED_ACTIONS)
    assert not _overlap(CALCULATED_RIGHT_PANEL, CALCULATED_ACTIONS)
    for rectangle in (
        CALCULATED_HEADER,
        CALCULATED_LEFT_PANEL,
        CALCULATED_RIGHT_PANEL,
        CALCULATED_ROWS,
        CALCULATED_PAGINATION,
        *CALCULATED_TAB_RECTS,
    ):
        assert rectangle.x >= 0 and rectangle.y >= 0
        assert rectangle.x + rectangle.width <= 800
        assert rectangle.y + rectangle.height <= 480
    assert not _overlap(CALCULATED_ROWS, CALCULATED_PAGINATION)
    assert all(
        not _overlap(first, second)
        for index, first in enumerate(CALCULATED_TAB_RECTS)
        for second in CALCULATED_TAB_RECTS[index + 1 :]
    )
    for view in (
        NutritionView(tab, page)
        for tab in NutritionTab
        for page in range(NutritionView(tab).page_count)
    ):
        buttons = buttons_for(UIScreen.CALCULATED, nutrition_view=view)
        for button in buttons:
            rectangle = button.rectangle
            assert rectangle.x >= 0 and rectangle.y >= 0
            assert rectangle.x + rectangle.width <= 800
            assert rectangle.y + rectangle.height <= 480
            assert rectangle.width >= 44 and rectangle.height >= 44
        assert all(
            not _overlap(first.rectangle, second.rectangle)
            for index, first in enumerate(buttons)
            for second in buttons[index + 1 :]
        )


def test_all_authoritative_nutrients_are_reachable_with_exact_units() -> None:
    response = _response()
    macro = pygame_device_ui._nutrition_rows(
        response, NutritionTab.MACROS, Language.ENGLISH
    )
    micro = pygame_device_ui._nutrition_rows(
        response, NutritionTab.MICROS, Language.ENGLISH
    )
    assert [unit for _, _, unit, _ in macro] == [
        "kJ",
        "kcal",
        "g",
        "g",
        "g",
        "g",
        "g",
        "g",
    ]
    assert [unit for _, _, unit, _ in micro] == [
        "mg",
        "mg",
        "g",
        "g",
        "mg",
        "mg",
        "mg",
        "mg",
        "mg",
        "mg",
        "mcg RAE",
        "mg",
        "mg",
        "mcg",
        "mcg DFE",
        "mcg",
        "mg",
    ]
    assert len(macro) == 8
    assert len(micro) == 17
    assert len({label for label, _, _, _ in macro + micro}) == 25
    assert {value for _, value, _, _ in macro + micro} >= {"516132716.444", "19.000"}


def test_nullable_values_are_never_rendered_as_zero() -> None:
    rows = pygame_device_ui._nutrition_rows(
        _response(nullable=True), NutritionTab.MICROS, Language.ENGLISH
    )
    assert all(value is None for _, value, _, _ in rows)
    assert all(
        pygame_device_ui._format_nutrition(value, unit, Language.ENGLISH)
        == "Not available"
        for _, value, unit, _ in rows
    )


def test_tab_and_page_transitions_are_bounded_and_do_not_invoke_analysis() -> None:
    flow = MealCaptureWorkflow.__new__(MealCaptureWorkflow)
    flow.screen = UIScreen.CALCULATED
    flow._nutrition_view = NutritionView()
    flow.select_nutrition_tab(NutritionTab.MICROS)
    for _ in range(20):
        flow.next_nutrition_page()
    assert flow.nutrition_view == NutritionView(NutritionTab.MICROS, 4)
    for _ in range(20):
        flow.previous_nutrition_page()
    assert flow.nutrition_view == NutritionView(NutritionTab.MICROS, 0)
    flow.select_nutrition_tab(NutritionTab.MACROS)
    assert flow.nutrition_view == NutritionView(NutritionTab.MACROS, 0)


def test_sdl_dummy_calculated_pages_fit_viewport() -> None:
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame = pytest.importorskip("pygame")
    pygame.init()
    try:
        surface = pygame.display.set_mode(DISPLAY_SIZE)
        fonts = pygame_device_ui._Fonts(
            heading=pygame.font.Font(None, 48),
            subheading=pygame.font.Font(None, 34),
            body=pygame.font.Font(None, 28),
            small=pygame.font.Font(None, 20),
            button=pygame.font.Font(None, 32),
        )
        for language in (Language.ENGLISH, Language.TAGALOG):
            workflow = _workflow(_response(nullable=True), language)
            for tab in NutritionTab:
                for page in range(NutritionView(tab).page_count):
                    workflow.nutrition_view = NutritionView(tab, page)
                    cache = pygame_device_ui._UiImageCache()
                    cache.thumbnail = pygame.Surface((180, 102))
                    cache.thumbnail.fill((12, 34, 56))
                    surface.fill((255, 255, 255))
                    pygame_device_ui._render(
                        pygame, surface, fonts, workflow, None, image_cache=cache
                    )
                    bounds = surface.get_bounding_rect(min_alpha=1)
                    assert bounds.left >= 0 and bounds.top >= 0
                    assert bounds.right <= 800 and bounds.bottom <= 480
    finally:
        pygame.quit()
        for module in tuple(sys.modules):
            if module == "pygame" or module.startswith("pygame."):
                sys.modules.pop(module, None)


def test_calculated_actions_are_dispatched_without_backend_or_identifier_output() -> (
    None
):
    class Flow:
        screen = UIScreen.CALCULATED

        def __init__(self) -> None:
            self.tabs: list[NutritionTab] = []
            self.calls: list[str] = []

        def select_nutrition_tab(self, tab: NutritionTab) -> None:
            self.tabs.append(tab)

        def next_nutrition_page(self) -> None:
            self.calls.append("next")

        def previous_nutrition_page(self) -> None:
            self.calls.append("previous")

    flow = Flow()
    pygame_device_ui._apply_action(
        object(), object(), object(), flow, UIAction.NUTRITION_MICROS
    )
    pygame_device_ui._apply_action(
        object(), object(), object(), flow, UIAction.NUTRITION_NEXT
    )
    pygame_device_ui._apply_action(
        object(), object(), object(), flow, UIAction.NUTRITION_PREVIOUS
    )
    assert flow.tabs == [NutritionTab.MICROS]
    assert flow.calls == ["next", "previous"]


def test_thumbnail_aspect_fit_stays_inside_the_meal_summary_panel() -> None:
    for source in ((1920, 1080), (1080, 1920), (1000, 1000)):
        width, height = pygame_device_ui.scaled_image_size(
            source,
            (CALCULATED_THUMBNAIL.width, CALCULATED_THUMBNAIL.height),
        )
        assert width <= CALCULATED_THUMBNAIL.width
        assert height <= CALCULATED_THUMBNAIL.height
        assert (
            width * source[1] == height * source[0]
            or abs(width / height - source[0] / source[1]) < 0.02
        )
    assert not _overlap(CALCULATED_THUMBNAIL, CALCULATED_ROWS)
    assert CALCULATED_LEFT_PANEL.x <= CALCULATED_THUMBNAIL.x
    assert CALCULATED_THUMBNAIL.x + CALCULATED_THUMBNAIL.width <= (
        CALCULATED_LEFT_PANEL.x + CALCULATED_LEFT_PANEL.width
    )
    assert CALCULATED_LEFT_PANEL.y <= CALCULATED_THUMBNAIL.y
    assert CALCULATED_THUMBNAIL.y + CALCULATED_THUMBNAIL.height <= (
        CALCULATED_LEFT_PANEL.y + CALCULATED_LEFT_PANEL.height
    )


def test_detached_thumbnail_survives_confirmed_image_cleanup_without_disk_copy(
    tmp_path,
) -> None:
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame = pytest.importorskip("pygame")
    pygame.init()
    image_path = tmp_path / "meal.jpg"
    try:
        original = pygame.Surface((1920, 1080))
        original.fill((12, 34, 56))
        pygame.image.save(original, image_path)
        cache = pygame_device_ui._UiImageCache()

        cache.capture_review_image(pygame, image_path, meal_generation=7)

        assert cache.thumbnail is not None
        assert cache.thumbnail.get_size()[0] <= CALCULATED_THUMBNAIL.width
        image_path.unlink()
        assert cache.thumbnail.get_size()[0] > 0
        assert list(tmp_path.iterdir()) == []
        cache.clear_review()
        assert cache.thumbnail is not None
        cache.clear()
        assert cache.thumbnail is None
    finally:
        pygame.quit()
        for module in tuple(sys.modules):
            if module == "pygame" or module.startswith("pygame."):
                sys.modules.pop(module, None)


@pytest.mark.parametrize("action", [UIAction.HOME, UIAction.RETAKE, UIAction.EXIT])
def test_terminal_navigation_clears_renderer_thumbnail(action: UIAction) -> None:
    class Flow:
        screen = UIScreen.CALCULATED

        def home(self) -> None:
            self.screen = UIScreen.HOME

        def retake(self) -> None:
            self.screen = UIScreen.CAPTURE

    cache = pygame_device_ui._UiImageCache()
    cache.thumbnail = object()

    pygame_device_ui._apply_action(
        object(), object(), object(), Flow(), action, image_cache=cache
    )

    assert cache.thumbnail is None


def test_generation_signal_clears_thumbnail_without_rendering_home() -> None:
    cache = pygame_device_ui._UiImageCache()
    cache.thumbnail = object()
    cache._meal_generation = 7

    cache.discard_if_stale(8)

    assert cache.thumbnail is None


def test_retryable_same_meal_generation_retains_thumbnail() -> None:
    cache = pygame_device_ui._UiImageCache()
    cache.thumbnail = object()
    cache._meal_generation = 7

    cache.discard_if_stale(7)

    assert cache.thumbnail is not None
