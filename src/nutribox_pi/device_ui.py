"""Hardware-independent PI-1D/PI-2A meal-capture and analysis workflow."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from nutribox_pi.adapters.hx711_weight import WeightSensorUnavailable
from nutribox_pi.continuation import (
    ContinuationState,
    MealAnalysisContinuationWorkflow,
    SaveState,
)
from nutribox_pi.controller import NutriBoxController
from nutribox_pi.models import (
    AnalysisStatus,
    IngredientVerification,
    IngredientVerificationItem,
    MealAnalysisResponse,
    PreviewFrame,
    RecognitionSource,
    RecognizedFood,
)
from nutribox_pi.pairing import REVOKED_MESSAGE, PairingState, PairingWorkflow
from nutribox_pi.ports import (
    DeviceAuthenticationFailure,
    PreviewCamera,
    PreviewSession,
    RetryableBackendFailure,
)
from nutribox_pi.touchscreen import TouchRect
from nutribox_pi.ui_preferences import Language, Theme
from nutribox_pi.ui_shell import MILESTONES, StartupShell

DISPLAY_SIZE = (800, 480)
CAPTURE_FILE_NAME = "meal.jpg"

PRIMARY = (61, 179, 90)
PRIMARY_MUTED = (168, 222, 184)
BACKGROUND = (255, 255, 255)
ELEVATED_SURFACE = (250, 250, 250)
CARD = (240, 240, 243)
PRIMARY_TEXT = (13, 13, 13)
SECONDARY_TEXT = (96, 100, 108)
BORDER = (232, 232, 237)
DANGER = (229, 57, 53)

CAMERA_ERROR = "Unable to capture the meal image."
PREVIEW_ERROR = "Camera preview is unavailable."
CLEANUP_ERROR = "Temporary image cleanup failed."
DISPLAY_ERROR = "The Nutri-Box display is unavailable."
ANALYSIS_ERROR = "Meal analysis is unavailable."
WEIGHT_ERROR = "Weight sensor unavailable."
UI_CLOSED = "Nutri-Box UI closed."
DEVELOPMENT_NOTICE = "Development mode: simulated weight"

RESULT_MESSAGES = {
    AnalysisStatus.CALCULATED: "Meal analysis completed.",
    AnalysisStatus.FOOD_NOT_RECOGNIZED: "Food was not recognized.",
    AnalysisStatus.REQUIRES_FOOD_SELECTION: "Food selection is required.",
    AnalysisStatus.NUTRITION_REFERENCE_NOT_FOUND: (
        "Nutrition reference was not found."
    ),
    AnalysisStatus.REQUIRES_INGREDIENT_VERIFICATION: (
        "Additional meal confirmation is required."
    ),
    AnalysisStatus.REQUIRES_RECIPE_CONFIRMATION: (
        "Additional meal confirmation is required."
    ),
}


class UIScreen(StrEnum):
    LOADING = "loading"
    LANGUAGE = "language"
    INSTRUCTION = "instruction"
    HOME = "home"
    CAPTURE = "capture"
    CAPTURING = "capturing"
    REVIEW = "review"
    ANALYZING = "analyzing"
    CALCULATED = "calculated"
    FOOD_NOT_RECOGNIZED = "food_not_recognized"
    REQUIRES_FOOD_SELECTION = "requires_food_selection"
    FOOD_SELECTION = "food_selection"
    REQUIRES_INGREDIENT_VERIFICATION = "requires_ingredient_verification"
    INGREDIENT_EDITOR = "ingredient_editor"
    INGREDIENT_CANDIDATE_SELECTION = "ingredient_candidate_selection"
    REQUIRES_RECIPE_CONFIRMATION = "requires_recipe_confirmation"
    NUTRITION_REFERENCE_NOT_FOUND = "nutrition_reference_not_found"
    RECOGNIZED_FOODS = "recognized_foods"
    ERROR = "error"
    PAIR_REQUESTING = "pair_requesting"
    PAIR_WAITING = "pair_waiting"
    PAIR_PAIRED = "pair_paired"
    PAIR_EXPIRED = "pair_expired"
    PAIR_ERROR = "pair_error"
    PROFILE_SETTINGS = "profile_settings"
    UNPAIR_CONFIRM = "unpair_confirm"


class UIAction(StrEnum):
    SELECT_ENGLISH = "select_english"
    SELECT_TAGALOG = "select_tagalog"
    TOGGLE_INTRO = "toggle_intro"
    HELP = "help"
    CONTINUE = "continue"
    ANALYZE = "analyze"
    ANALYZE_MEAL = "analyze_meal"
    SHOW_RECOGNIZED_FOODS = "show_recognized_foods"
    SAVE_MEAL = "save_meal"
    ANALYZE_AGAIN = "analyze_again"
    CAPTURE = "capture"
    BACK = "back"
    RETAKE = "retake"
    RETRY = "retry"
    HOME = "home"
    EXIT = "exit"
    PAIR_DEVICE = "pair_device"
    CANCEL_PAIRING = "cancel_pairing"
    SELECT_FOOD_0 = "select_food_0"
    SELECT_FOOD_1 = "select_food_1"
    SELECT_FOOD_2 = "select_food_2"
    SELECT_FOOD_3 = "select_food_3"
    FOOD_PREVIOUS = "food_previous"
    FOOD_NEXT = "food_next"
    FOOD_CONTINUE = "food_continue"
    TOGGLE_INGREDIENT_0 = "toggle_ingredient_0"
    TOGGLE_INGREDIENT_1 = "toggle_ingredient_1"
    TOGGLE_INGREDIENT_2 = "toggle_ingredient_2"
    TOGGLE_INGREDIENT_3 = "toggle_ingredient_3"
    INGREDIENT_PREVIOUS = "ingredient_previous"
    INGREDIENT_NEXT = "ingredient_next"
    COMPONENT_PREVIOUS = "component_previous"
    COMPONENT_NEXT = "component_next"
    CONFIRM_INGREDIENTS = "confirm_ingredients"
    RESCAN = "rescan"
    EDIT_INGREDIENT_0 = "edit_ingredient_0"
    EDIT_INGREDIENT_1 = "edit_ingredient_1"
    EDIT_INGREDIENT_2 = "edit_ingredient_2"
    EDIT_INGREDIENT_3 = "edit_ingredient_3"
    ADD_INGREDIENT = "add_ingredient"
    EDITOR_SPACE = "editor_space"
    EDITOR_BACKSPACE = "editor_backspace"
    EDITOR_CLEAR = "editor_clear"
    EDITOR_CANCEL = "editor_cancel"
    EDITOR_DONE = "editor_done"
    EDITOR_KEY = "editor_key"
    SELECT_INGREDIENT_CANDIDATE_0 = "select_ingredient_candidate_0"
    SELECT_INGREDIENT_CANDIDATE_1 = "select_ingredient_candidate_1"
    SELECT_INGREDIENT_CANDIDATE_2 = "select_ingredient_candidate_2"
    SELECT_INGREDIENT_CANDIDATE_3 = "select_ingredient_candidate_3"
    INGREDIENT_CANDIDATE_PREVIOUS = "ingredient_candidate_previous"
    INGREDIENT_CANDIDATE_NEXT = "ingredient_candidate_next"
    INGREDIENT_CANDIDATE_PREVIOUS_ITEM = "ingredient_candidate_previous_item"
    INGREDIENT_CANDIDATE_NEXT_ITEM = "ingredient_candidate_next_item"
    CONTINUE_INGREDIENT_CANDIDATE = "continue_ingredient_candidate"
    NUTRITION_OVERVIEW = "nutrition_overview"
    NUTRITION_MACROS = "nutrition_macros"
    NUTRITION_MICROS = "nutrition_micros"
    NUTRITION_PREVIOUS = "nutrition_previous"
    NUTRITION_NEXT = "nutrition_next"
    PROFILE_SETTINGS = "profile_settings"
    SETTINGS_BACK = "settings_back"
    SETTINGS_ENGLISH = "settings_english"
    SETTINGS_TAGALOG = "settings_tagalog"
    TOGGLE_THEME = "toggle_theme"
    SETTINGS_DIAGNOSTICS = "settings_diagnostics"
    UNPAIR = "unpair"
    CONFIRM_UNPAIR = "confirm_unpair"
    CANCEL_UNPAIR = "cancel_unpair"


@dataclass(frozen=True, slots=True)
class UIResult:
    ok: bool
    message: str


@dataclass(frozen=True, slots=True)
class ButtonLayout:
    action: UIAction
    label: str
    rectangle: TouchRect
    role: str = "primary"
    enabled: bool = True


EXIT_BUTTON = ButtonLayout(UIAction.EXIT, "Exit", TouchRect(660, 20, 110, 58), "danger")
FOOD_SELECTION_PAGE_SIZE = 4
FOOD_SELECTION_LIMITATION = "Food selection is unavailable for this analysis."

# Calculated-result geometry is intentionally centralized: 800x480 is a hard
# device viewport, with mutually exclusive header, content, and action regions.
CALCULATED_HEADER = TouchRect(20, 16, 760, 48)
CALCULATED_LEFT_PANEL = TouchRect(20, 80, 250, 300)
CALCULATED_RIGHT_PANEL = TouchRect(284, 80, 496, 300)
CALCULATED_THUMBNAIL = TouchRect(55, 140, 180, 102)
CALCULATED_TAB_RECTS = (
    TouchRect(296, 94, 144, 44),
    TouchRect(448, 94, 144, 44),
    TouchRect(600, 94, 164, 44),
)
CALCULATED_ROWS = TouchRect(300, 154, 464, 120)
CALCULATED_PAGINATION = TouchRect(300, 306, 464, 44)
CALCULATED_ACTIONS = TouchRect(20, 400, 760, 60)
NUTRITION_ROW_HEIGHT = 30
NUTRITION_ROWS_PER_PAGE = CALCULATED_ROWS.height // NUTRITION_ROW_HEIGHT


class NutritionTab(StrEnum):
    OVERVIEW = "overview"
    MACROS = "macros"
    MICROS = "micros"


NUTRITION_ROW_COUNTS = {
    NutritionTab.OVERVIEW: 3,
    NutritionTab.MACROS: 8,
    NutritionTab.MICROS: 17,
}
NUTRITION_PAGE_COUNTS = {
    tab: (row_count + NUTRITION_ROWS_PER_PAGE - 1) // NUTRITION_ROWS_PER_PAGE
    for tab, row_count in NUTRITION_ROW_COUNTS.items()
}


@dataclass(frozen=True, slots=True)
class NutritionView:
    tab: NutritionTab = NutritionTab.OVERVIEW
    page: int = 0

    @property
    def page_count(self) -> int:
        return NUTRITION_PAGE_COUNTS[self.tab]


@dataclass(frozen=True, slots=True)
class FoodSelectionView:
    """Renderer-safe candidate projection; it contains no backend identifiers."""

    names: tuple[str, ...]
    page: int
    selected_index: int | None
    request_in_progress: bool
    retry_available: bool


@dataclass(frozen=True, slots=True)
class IngredientVerificationView:
    """Renderer-safe suggestion projection; all backend IDs remain private."""

    component_names: tuple[str, ...]
    names: tuple[str, ...]
    included: tuple[bool, ...]
    component_index: int
    page: int
    request_in_progress: bool
    retry_available: bool


@dataclass(frozen=True, slots=True)
class IngredientEditorView:
    draft: str
    target_index: int | None
    error: str | None


@dataclass(frozen=True, slots=True)
class IngredientCandidateView:
    ingredient_names: tuple[str, ...]
    candidate_names: tuple[str, ...]
    ingredient_index: int
    candidate_page: int
    selected_index: int | None
    request_in_progress: bool
    retry_available: bool


def normalize_ingredient_name(value: str) -> str | None:
    """Apply the Web-compatible trim while rejecting controls locally."""
    if not isinstance(value, str) or any(
        ord(char) < 32 or ord(char) == 127 for char in value
    ):
        return None
    normalized = " ".join(value.split())
    return normalized if 1 <= len(normalized) <= 160 else None


def buttons_for(
    screen: UIScreen,
    pairing_state: PairingState | None = None,
    food_selection: FoodSelectionView | None = None,
    nutrition_view: NutritionView | None = None,
    ingredient_verification: IngredientVerificationView | None = None,
    ingredient_candidates: IngredientCandidateView | None = None,
    save_enabled: bool = False,
) -> tuple[ButtonLayout, ...]:
    if screen is UIScreen.LOADING:
        return ()
    if screen is UIScreen.LANGUAGE:
        return (
            ButtonLayout(
                UIAction.SELECT_ENGLISH, "English", TouchRect(250, 164, 300, 58)
            ),
            ButtonLayout(
                UIAction.SELECT_TAGALOG, "Tagalog", TouchRect(250, 234, 300, 58), "card"
            ),
            ButtonLayout(
                UIAction.TOGGLE_INTRO,
                "Show intro",
                TouchRect(190, 350, 420, 52),
                "card",
            ),
            ButtonLayout(UIAction.HELP, "?", TouchRect(700, 398, 56, 56), "card"),
            EXIT_BUTTON,
        )
    if screen is UIScreen.INSTRUCTION:
        return (
            ButtonLayout(UIAction.BACK, "Back", TouchRect(570, 398, 96, 56), "card"),
            ButtonLayout(UIAction.CONTINUE, "Skip", TouchRect(678, 398, 96, 56)),
        )
    if screen is UIScreen.HOME:
        return (
            ButtonLayout(UIAction.BACK, "Back", TouchRect(24, 20, 104, 52), "card"),
            ButtonLayout(
                UIAction.ANALYZE,
                "Analyze Meal",
                TouchRect(210, 250, 380, 68),
            ),
            _home_pairing_button(pairing_state),
            ButtonLayout(
                UIAction.PROFILE_SETTINGS,
                "Profile & Settings",
                TouchRect(24, 402, 270, 56),
                "card",
            ),
            EXIT_BUTTON,
        )
    if screen is UIScreen.PROFILE_SETTINGS:
        return (
            ButtonLayout(
                UIAction.SETTINGS_BACK, "Back", TouchRect(24, 402, 140, 56), "card"
            ),
            ButtonLayout(
                UIAction.SETTINGS_ENGLISH,
                "English",
                TouchRect(180, 270, 180, 52),
                "card",
            ),
            ButtonLayout(
                UIAction.SETTINGS_TAGALOG,
                "Tagalog",
                TouchRect(380, 270, 180, 52),
                "card",
            ),
            ButtonLayout(
                UIAction.TOGGLE_THEME, "Theme", TouchRect(580, 270, 196, 52), "card"
            ),
            ButtonLayout(
                UIAction.SETTINGS_DIAGNOSTICS,
                "Diagnostics",
                TouchRect(180, 334, 180, 52),
                "card",
            ),
            ButtonLayout(
                UIAction.UNPAIR,
                "Unpair",
                TouchRect(380, 334, 180, 52),
                "danger",
                pairing_state is PairingState.PAIRED,
            ),
            EXIT_BUTTON,
        )
    if screen is UIScreen.UNPAIR_CONFIRM:
        return (
            ButtonLayout(
                UIAction.CANCEL_UNPAIR, "Cancel", TouchRect(180, 330, 200, 64), "card"
            ),
            ButtonLayout(
                UIAction.CONFIRM_UNPAIR,
                "Unpair",
                TouchRect(420, 330, 200, 64),
                "danger",
            ),
            EXIT_BUTTON,
        )
    if screen is UIScreen.CAPTURE:
        return (
            ButtonLayout(UIAction.BACK, "Back", TouchRect(570, 370, 200, 58), "card"),
            ButtonLayout(
                UIAction.CAPTURE, "Capture Meal", TouchRect(570, 286, 200, 64)
            ),
            EXIT_BUTTON,
        )
    if screen is UIScreen.CAPTURING:
        return (
            ButtonLayout(
                UIAction.CAPTURE,
                "Capturing...",
                TouchRect(570, 286, 200, 64),
                enabled=False,
            ),
            EXIT_BUTTON,
        )
    if screen is UIScreen.REVIEW:
        return (
            ButtonLayout(UIAction.ANALYZE_MEAL, "Yes", TouchRect(570, 244, 92, 60)),
            ButtonLayout(UIAction.RETAKE, "No", TouchRect(678, 244, 92, 60), "card"),
            ButtonLayout(UIAction.BACK, "Back", TouchRect(570, 370, 200, 58), "card"),
        )
    if screen is UIScreen.ANALYZING:
        return (
            ButtonLayout(
                UIAction.ANALYZE_MEAL,
                "Analyzing...",
                TouchRect(240, 318, 320, 88),
                enabled=False,
            ),
            EXIT_BUTTON,
        )
    if screen is UIScreen.CALCULATED:
        return _calculated_buttons(nutrition_view or NutritionView(), save_enabled)
    if screen is UIScreen.FOOD_SELECTION:
        return _food_selection_buttons(
            food_selection or FoodSelectionView((), 0, None, False, False)
        )
    if screen is UIScreen.REQUIRES_INGREDIENT_VERIFICATION:
        return _ingredient_verification_buttons(
            ingredient_verification
            or IngredientVerificationView((), (), (), 0, 0, False, False)
        )
    if screen is UIScreen.INGREDIENT_EDITOR:
        return _ingredient_editor_buttons()
    if screen is UIScreen.INGREDIENT_CANDIDATE_SELECTION:
        return _ingredient_candidate_buttons(
            ingredient_candidates
            or IngredientCandidateView((), (), 0, 0, None, False, False)
        )
    if screen in RESULT_SCREENS:
        return (
            ButtonLayout(
                UIAction.RETAKE, "Retake", TouchRect(70, 330, 300, 76), "card"
            ),
            ButtonLayout(UIAction.HOME, "Home", TouchRect(430, 330, 300, 76)),
            EXIT_BUTTON,
        )
    if screen is UIScreen.RECOGNIZED_FOODS:
        return (
            ButtonLayout(
                UIAction.RETAKE, "Retake", TouchRect(70, 394, 300, 66), "card"
            ),
            ButtonLayout(
                UIAction.ANALYZE_AGAIN,
                "Analyze again",
                TouchRect(430, 394, 300, 66),
            ),
            ButtonLayout(UIAction.HOME, "Home", TouchRect(430, 320, 300, 56), "card"),
            EXIT_BUTTON,
        )
    if screen in {UIScreen.PAIR_REQUESTING, UIScreen.PAIR_WAITING}:
        return (
            ButtonLayout(
                UIAction.CANCEL_PAIRING, "Cancel", TouchRect(250, 370, 300, 64), "card"
            ),
            EXIT_BUTTON,
        )
    if screen in {UIScreen.PAIR_PAIRED, UIScreen.PAIR_EXPIRED, UIScreen.PAIR_ERROR}:
        return (
            ButtonLayout(UIAction.RETRY, "Retry", TouchRect(90, 370, 280, 64)),
            ButtonLayout(UIAction.HOME, "Home", TouchRect(430, 370, 280, 64), "card"),
            EXIT_BUTTON,
        )
    return (
        ButtonLayout(UIAction.RETRY, "Retry", TouchRect(90, 330, 280, 76)),
        ButtonLayout(UIAction.HOME, "Home", TouchRect(430, 330, 280, 76), "card"),
        EXIT_BUTTON,
    )


def _food_selection_buttons(view: FoodSelectionView) -> tuple[ButtonLayout, ...]:
    actions = (
        UIAction.SELECT_FOOD_0,
        UIAction.SELECT_FOOD_1,
        UIAction.SELECT_FOOD_2,
        UIAction.SELECT_FOOD_3,
    )
    start = view.page * FOOD_SELECTION_PAGE_SIZE
    candidates = tuple(
        ButtonLayout(
            action,
            view.names[start + offset],
            TouchRect(40, 112 + offset * 56, 500, 50),
            "primary" if view.selected_index == start + offset else "card",
            not view.request_in_progress,
        )
        for offset, action in enumerate(actions)
        if start + offset < len(view.names)
    )
    page_count = max(
        1, (len(view.names) + FOOD_SELECTION_PAGE_SIZE - 1) // FOOD_SELECTION_PAGE_SIZE
    )
    navigation = (
        ButtonLayout(
            UIAction.FOOD_PREVIOUS,
            "Previous",
            TouchRect(560, 112, 180, 50),
            "card",
            view.page > 0 and not view.request_in_progress,
        ),
        ButtonLayout(
            UIAction.FOOD_NEXT,
            "Next",
            TouchRect(560, 168, 180, 50),
            "card",
            view.page + 1 < page_count and not view.request_in_progress,
        ),
        ButtonLayout(
            UIAction.FOOD_CONTINUE,
            "Continue",
            TouchRect(560, 224, 180, 50),
            "primary",
            view.selected_index is not None and not view.request_in_progress,
        ),
        ButtonLayout(UIAction.BACK, "Back", TouchRect(560, 280, 180, 50), "card"),
        ButtonLayout(UIAction.RETAKE, "Retake", TouchRect(170, 362, 220, 56), "card"),
        ButtonLayout(UIAction.HOME, "Home", TouchRect(410, 362, 220, 56), "card"),
        EXIT_BUTTON,
    )
    if view.retry_available:
        return candidates + (
            ButtonLayout(UIAction.RETRY, "Retry", TouchRect(560, 224, 180, 50)),
            ButtonLayout(UIAction.BACK, "Back", TouchRect(560, 280, 180, 50), "card"),
            ButtonLayout(
                UIAction.RETAKE, "Retake", TouchRect(170, 362, 220, 56), "card"
            ),
            ButtonLayout(UIAction.HOME, "Home", TouchRect(410, 362, 220, 56), "card"),
            EXIT_BUTTON,
        )
    return candidates + navigation


def _calculated_buttons(
    view: NutritionView, save_enabled: bool = False
) -> tuple[ButtonLayout, ...]:
    tab_actions = (
        UIAction.NUTRITION_OVERVIEW,
        UIAction.NUTRITION_MACROS,
        UIAction.NUTRITION_MICROS,
    )
    tab_labels = ("Overview", "Macros", "Micros")
    tabs = tuple(
        ButtonLayout(
            action,
            label,
            rectangle,
            "primary"
            if view.tab.value == action.removeprefix("nutrition_")
            else "card",
        )
        for action, label, rectangle in zip(
            tab_actions, tab_labels, CALCULATED_TAB_RECTS, strict=True
        )
    )
    actions = (
        ButtonLayout(
            UIAction.NUTRITION_PREVIOUS,
            "Previous",
            TouchRect(300, 306, 128, 44),
            "card",
            view.page > 0,
        ),
        ButtonLayout(
            UIAction.NUTRITION_NEXT,
            "Next",
            TouchRect(636, 306, 128, 44),
            "card",
            view.page + 1 < view.page_count,
        ),
        ButtonLayout(
            UIAction.SHOW_RECOGNIZED_FOODS,
            "See recognized foods",
            TouchRect(20, 400, 230, 60),
        ),
        ButtonLayout(UIAction.RETAKE, "Retake", TouchRect(430, 400, 110, 60), "card"),
        ButtonLayout(UIAction.HOME, "Home", TouchRect(550, 400, 110, 60)),
        ButtonLayout(UIAction.EXIT, "Exit", TouchRect(670, 400, 110, 60), "danger"),
    )
    if not save_enabled:
        return tabs + actions
    return tabs + (
        actions[0],
        actions[1],
        actions[2],
        ButtonLayout(UIAction.SAVE_MEAL, "Save Meal", TouchRect(260, 400, 160, 60)),
        *actions[3:],
    )


def _ingredient_verification_buttons(
    view: IngredientVerificationView,
) -> tuple[ButtonLayout, ...]:
    actions = (
        UIAction.TOGGLE_INGREDIENT_0,
        UIAction.TOGGLE_INGREDIENT_1,
        UIAction.TOGGLE_INGREDIENT_2,
        UIAction.TOGGLE_INGREDIENT_3,
    )
    start = view.page * FOOD_SELECTION_PAGE_SIZE
    rows = tuple(
        ButtonLayout(
            action,
            f"{'[x]' if view.included[start + offset] else '[ ]'} "
            f"{view.names[start + offset]}",
            TouchRect(28, 150 + offset * 46, 420, 42),
            "primary" if view.included[start + offset] else "card",
            not view.request_in_progress,
        )
        for offset, action in enumerate(actions)
        if start + offset < len(view.names)
    )
    edits = tuple(
        ButtonLayout(
            action,
            "Edit",
            TouchRect(456, 150 + offset * 46, 72, 42),
            "card",
            not view.request_in_progress,
        )
        for offset, action in enumerate(
            (
                UIAction.EDIT_INGREDIENT_0,
                UIAction.EDIT_INGREDIENT_1,
                UIAction.EDIT_INGREDIENT_2,
                UIAction.EDIT_INGREDIENT_3,
            )
        )
        if start + offset < len(view.names)
    )
    page_count = max(
        1, (len(view.names) + FOOD_SELECTION_PAGE_SIZE - 1) // FOOD_SELECTION_PAGE_SIZE
    )
    side = (
        ButtonLayout(
            UIAction.COMPONENT_PREVIOUS,
            "Previous meal part",
            TouchRect(548, 112, 224, 42),
            "card",
            view.component_index > 0 and not view.request_in_progress,
        ),
        ButtonLayout(
            UIAction.ADD_INGREDIENT,
            "Add Ingredient",
            TouchRect(548, 256, 224, 42),
            "card",
            len(view.names) < 50 and not view.request_in_progress,
        ),
        ButtonLayout(
            UIAction.COMPONENT_NEXT,
            "Next meal part",
            TouchRect(548, 160, 224, 42),
            "card",
            view.component_index + 1 < len(view.component_names)
            and not view.request_in_progress,
        ),
        ButtonLayout(
            UIAction.INGREDIENT_PREVIOUS,
            "Previous",
            TouchRect(548, 208, 108, 42),
            "card",
            view.page > 0 and not view.request_in_progress,
        ),
        ButtonLayout(
            UIAction.INGREDIENT_NEXT,
            "Next",
            TouchRect(664, 208, 108, 42),
            "card",
            view.page + 1 < page_count and not view.request_in_progress,
        ),
        ButtonLayout(
            UIAction.RESCAN,
            "Rescan",
            TouchRect(28, 402, 130, 58),
            "card",
            not view.request_in_progress,
        ),
        ButtonLayout(
            UIAction.RETAKE,
            "Retake",
            TouchRect(168, 402, 130, 58),
            "card",
            not view.request_in_progress,
        ),
        ButtonLayout(
            UIAction.CONFIRM_INGREDIENTS,
            "Confirm ingredients",
            TouchRect(308, 402, 212, 58),
            "primary",
            any(view.included) and not view.request_in_progress,
        ),
        ButtonLayout(
            UIAction.HOME,
            "Home",
            TouchRect(532, 402, 120, 58),
            "card",
            not view.request_in_progress,
        ),
        ButtonLayout(UIAction.EXIT, "Exit", TouchRect(660, 402, 112, 58), "danger"),
    )
    if view.retry_available:
        return (
            rows
            + edits
            + (
                ButtonLayout(UIAction.RETRY, "Retry", TouchRect(308, 402, 212, 58)),
                ButtonLayout(
                    UIAction.RESCAN, "Rescan", TouchRect(28, 402, 130, 58), "card"
                ),
                ButtonLayout(
                    UIAction.RETAKE, "Retake", TouchRect(168, 402, 130, 58), "card"
                ),
                ButtonLayout(
                    UIAction.HOME, "Home", TouchRect(532, 402, 120, 58), "card"
                ),
                ButtonLayout(
                    UIAction.EXIT, "Exit", TouchRect(660, 402, 112, 58), "danger"
                ),
            )
        )
    return rows + edits + side


def _ingredient_editor_buttons() -> tuple[ButtonLayout, ...]:
    rows = ("QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM")
    buttons: list[ButtonLayout] = []
    for row_index, keys in enumerate(rows):
        width = 54
        start = (800 - len(keys) * width) // 2
        for index, key in enumerate(keys):
            buttons.append(
                ButtonLayout(
                    UIAction.EDITOR_KEY,
                    key,
                    TouchRect(start + index * width, 210 + row_index * 52, 50, 46),
                    "card",
                )
            )
    return tuple(buttons) + (
        ButtonLayout(
            UIAction.EDITOR_SPACE, "Space", TouchRect(180, 366, 170, 54), "card"
        ),
        ButtonLayout(
            UIAction.EDITOR_BACKSPACE, "Backspace", TouchRect(360, 366, 120, 54), "card"
        ),
        ButtonLayout(
            UIAction.EDITOR_CLEAR, "Clear", TouchRect(490, 366, 100, 54), "card"
        ),
        ButtonLayout(
            UIAction.EDITOR_CANCEL, "Cancel", TouchRect(24, 426, 180, 46), "card"
        ),
        ButtonLayout(UIAction.EDITOR_DONE, "Done", TouchRect(596, 426, 180, 46)),
    )


def _ingredient_candidate_buttons(
    view: IngredientCandidateView,
) -> tuple[ButtonLayout, ...]:
    actions = (
        UIAction.SELECT_INGREDIENT_CANDIDATE_0,
        UIAction.SELECT_INGREDIENT_CANDIDATE_1,
        UIAction.SELECT_INGREDIENT_CANDIDATE_2,
        UIAction.SELECT_INGREDIENT_CANDIDATE_3,
    )
    start = view.candidate_page * FOOD_SELECTION_PAGE_SIZE
    candidates = tuple(
        ButtonLayout(
            action,
            view.candidate_names[start + offset],
            TouchRect(28, 145 + offset * 48, 500, 44),
            "primary" if view.selected_index == start + offset else "card",
            not view.request_in_progress,
        )
        for offset, action in enumerate(actions)
        if start + offset < len(view.candidate_names)
    )
    pages = max(
        1,
        (len(view.candidate_names) + FOOD_SELECTION_PAGE_SIZE - 1)
        // FOOD_SELECTION_PAGE_SIZE,
    )
    return candidates + (
        ButtonLayout(
            UIAction.INGREDIENT_CANDIDATE_PREVIOUS_ITEM,
            "Previous item",
            TouchRect(548, 112, 224, 44),
            "card",
            view.ingredient_index > 0 and not view.request_in_progress,
        ),
        ButtonLayout(
            UIAction.INGREDIENT_CANDIDATE_NEXT_ITEM,
            "Next item",
            TouchRect(548, 162, 224, 44),
            "card",
            view.ingredient_index + 1 < len(view.ingredient_names)
            and not view.request_in_progress,
        ),
        ButtonLayout(
            UIAction.INGREDIENT_CANDIDATE_PREVIOUS,
            "Previous",
            TouchRect(548, 212, 108, 44),
            "card",
            view.candidate_page > 0 and not view.request_in_progress,
        ),
        ButtonLayout(
            UIAction.INGREDIENT_CANDIDATE_NEXT,
            "Next",
            TouchRect(664, 212, 108, 44),
            "card",
            view.candidate_page + 1 < pages and not view.request_in_progress,
        ),
        ButtonLayout(
            UIAction.RESCAN,
            "Rescan",
            TouchRect(28, 402, 180, 58),
            "card",
            not view.request_in_progress,
        ),
        ButtonLayout(
            UIAction.CONTINUE_INGREDIENT_CANDIDATE,
            "Continue",
            TouchRect(220, 402, 300, 58),
            "primary",
            view.selected_index is not None and not view.request_in_progress,
        ),
        ButtonLayout(
            UIAction.HOME,
            "Home",
            TouchRect(532, 402, 120, 58),
            "card",
            not view.request_in_progress,
        ),
        ButtonLayout(UIAction.EXIT, "Exit", TouchRect(660, 402, 112, 58), "danger"),
    )


def _home_pairing_button(pairing_state: PairingState | None) -> ButtonLayout:
    if pairing_state is PairingState.PAIRED:
        return ButtonLayout(
            UIAction.PAIR_DEVICE,
            "Device paired",
            TouchRect(210, 330, 380, 58),
            "card",
            enabled=False,
        )
    if pairing_state in {PairingState.REQUESTING, PairingState.WAITING}:
        return ButtonLayout(
            UIAction.PAIR_DEVICE,
            "Checking device...",
            TouchRect(210, 330, 380, 58),
            "card",
            enabled=False,
        )
    return ButtonLayout(
        UIAction.PAIR_DEVICE, "Pair Device", TouchRect(210, 330, 380, 58), "card"
    )


def action_at(
    screen: UIScreen,
    x: float,
    y: float,
    pairing_state: PairingState | None = None,
    food_selection: FoodSelectionView | None = None,
    nutrition_view: NutritionView | None = None,
    ingredient_verification: IngredientVerificationView | None = None,
    ingredient_candidates: IngredientCandidateView | None = None,
    save_enabled: bool = False,
) -> UIAction | None:
    for button in buttons_for(
        screen,
        pairing_state,
        food_selection,
        nutrition_view,
        ingredient_verification,
        ingredient_candidates,
        save_enabled,
    ):
        if button.enabled and button.rectangle.contains(x, y):
            return button.action
    return None


def scaled_image_size(
    source: tuple[int, int], bounds: tuple[int, int]
) -> tuple[int, int]:
    source_width, source_height = source
    bound_width, bound_height = bounds
    if min(source_width, source_height, bound_width, bound_height) <= 0:
        raise ValueError("image dimensions must be positive")
    scale = min(bound_width / source_width, bound_height / source_height)
    return max(1, round(source_width * scale)), max(1, round(source_height * scale))


class TemporaryCaptureStore:
    def __init__(
        self,
        directory_factory: Callable[..., str] = tempfile.mkdtemp,
    ) -> None:
        self._directory_factory = directory_factory
        self._directory: Path | None = None
        self._image: Path | None = None

    @property
    def image_path(self) -> Path | None:
        return self._image

    def prepare(self) -> Path:
        if self._directory is not None and not self.cleanup():
            raise OSError
        directory = Path(self._directory_factory(prefix="nutribox-ui-"))
        self._directory = directory
        self._image = directory / CAPTURE_FILE_NAME
        if os.name == "posix":
            os.chmod(directory, 0o700)
        return self._image

    def cleanup(self) -> bool:
        failed = False
        if self._image is not None:
            try:
                self._image.unlink(missing_ok=True)
            except OSError:
                failed = True
        if self._directory is not None:
            try:
                self._directory.rmdir()
            except FileNotFoundError:
                pass
            except OSError:
                failed = True
        if not failed:
            self._image = None
            self._directory = None
        return not failed


STATUS_SCREENS = {
    AnalysisStatus.CALCULATED: UIScreen.CALCULATED,
    AnalysisStatus.FOOD_NOT_RECOGNIZED: UIScreen.FOOD_NOT_RECOGNIZED,
    AnalysisStatus.REQUIRES_FOOD_SELECTION: UIScreen.FOOD_SELECTION,
    AnalysisStatus.NUTRITION_REFERENCE_NOT_FOUND: (
        UIScreen.NUTRITION_REFERENCE_NOT_FOUND
    ),
    AnalysisStatus.REQUIRES_INGREDIENT_VERIFICATION: (
        UIScreen.REQUIRES_INGREDIENT_VERIFICATION
    ),
    AnalysisStatus.REQUIRES_RECIPE_CONFIRMATION: UIScreen.REQUIRES_RECIPE_CONFIRMATION,
}
RESULT_SCREENS = frozenset(STATUS_SCREENS.values())


class MealCaptureWorkflow:
    def __init__(
        self,
        camera: PreviewCamera,
        controller: NutriBoxController,
        store: TemporaryCaptureStore | None = None,
        simulated_weight: bool = False,
        pairing: PairingWorkflow | None = None,
        startup_shell: StartupShell | None = None,
        diagnostics_action: Callable[[], object] | None = None,
    ) -> None:
        self._camera = camera
        self._preview: PreviewSession | None = None
        self._controller = controller
        # The continuation workflow, not the renderer, owns active backend
        # session data.  PI-3B3-B will add the corresponding controls.
        self.continuation = MealAnalysisContinuationWorkflow(controller)
        self._store = store or TemporaryCaptureStore()
        self.simulated_weight = simulated_weight
        self.simulated_camera = bool(getattr(camera, "is_simulated", False))
        self.pairing = pairing
        self.startup_shell = startup_shell
        self._diagnostics_action = diagnostics_action
        self.settings_message: str | None = None
        self.screen = UIScreen.LOADING if startup_shell is not None else UIScreen.HOME
        self._startup_language_selection = startup_shell is not None
        self.error_message: str | None = None
        self.result_message: str | None = None
        self.recognized_foods: tuple[RecognizedFood, ...] = ()
        self.recognition_source: RecognitionSource | None = None
        self.analysis_response: MealAnalysisResponse | None = None
        self.captured_weight_grams: float | None = None
        self.analysis_retry_available = False
        self._food_selection = FoodSelectionView((), 0, None, False, False)
        self._ingredient_verification = IngredientVerificationView(
            (), (), (), 0, 0, False, False
        )
        self._ingredient_inclusions: tuple[tuple[bool, ...], ...] = ()
        self._ingredient_items: tuple[tuple[IngredientVerificationItem, ...], ...] = ()
        self._ingredient_editor: IngredientEditorView | None = None
        self._ingredient_candidates = IngredientCandidateView(
            (), (), 0, 0, None, False, False
        )
        self._nutrition_view = NutritionView()
        self._meal_generation = 0
        self._analysis_started_paired = False

    @property
    def language(self) -> Language:
        return (
            self.startup_shell.preferences.language
            if self.startup_shell is not None
            else Language.ENGLISH
        )

    @property
    def theme(self) -> Theme:
        return (
            self.startup_shell.preferences.theme if self.startup_shell else Theme.LIGHT
        )

    def tick_startup(self) -> None:
        shell = self.startup_shell
        if self.screen is not UIScreen.LOADING or shell is None:
            return
        if shell.completed < len(MILESTONES):
            shell.complete(MILESTONES[shell.completed])
        if shell.completed == len(MILESTONES):
            self.screen = UIScreen.LANGUAGE

    def select_language(self, language: Language) -> None:
        if self.startup_shell is None:
            return
        self.startup_shell.select_language(language)
        show_intro = (
            getattr(self, "_startup_language_selection", True)
            and self.startup_shell.preferences.show_intro_on_startup
        )
        self._startup_language_selection = False
        self.screen = UIScreen.INSTRUCTION if show_intro else UIScreen.HOME

    def toggle_intro(self) -> None:
        if self.startup_shell is not None:
            self.startup_shell.toggle_intro()

    def open_profile_settings(self) -> None:
        self.settings_message = None
        self.screen = UIScreen.PROFILE_SETTINGS

    def settings_back(self) -> None:
        self.settings_message = None
        self.screen = UIScreen.HOME

    def set_settings_language(self, language: Language) -> None:
        if self.startup_shell is not None:
            self.startup_shell.select_language(language)

    def toggle_theme(self) -> None:
        if self.startup_shell is not None:
            self.startup_shell.set_theme(
                Theme.DARK if self.theme is Theme.LIGHT else Theme.LIGHT
            )

    def run_diagnostics(self) -> None:
        try:
            report = self._diagnostics_action() if self._diagnostics_action else None
            self.settings_message = (
                "Diagnostics passed."
                if bool(getattr(report, "passed", False))
                else "Diagnostics unavailable."
            )
        except Exception:
            self.settings_message = "Diagnostics unavailable."

    def request_unpair(self) -> None:
        if self.pairing is not None and self.pairing.state is PairingState.PAIRED:
            self.screen = UIScreen.UNPAIR_CONFIRM

    def confirm_unpair(self) -> None:
        if self.pairing is not None:
            self.pairing.unpair()
        self.screen = UIScreen.PROFILE_SETTINGS

    def continue_from_instruction(self) -> None:
        self.screen = UIScreen.HOME

    def start_pairing(self) -> None:
        if self.pairing is not None and self.pairing.start():
            self.screen = UIScreen.PAIR_REQUESTING

    def tick_pairing(self) -> None:
        if self.pairing is None:
            return
        self.pairing.tick()
        if self._analysis_started_paired and not self._paired_and_verified():
            self._analysis_started_paired = False
            self.continuation.disable_save()
        if self.pairing.error_message == REVOKED_MESSAGE and self.screen in {
            UIScreen.CAPTURE,
            UIScreen.CAPTURING,
            UIScreen.REVIEW,
        }:
            self._close_preview()
            self._store.cleanup()
            self._clear_analysis_state()
            self.continuation.revoke()
            self.screen = UIScreen.HOME
            return
        screens = {
            PairingState.UNPAIRED: UIScreen.HOME,
            PairingState.REQUESTING: UIScreen.PAIR_REQUESTING,
            PairingState.WAITING: UIScreen.PAIR_WAITING,
            PairingState.PAIRED: UIScreen.PAIR_PAIRED,
            PairingState.EXPIRED: UIScreen.PAIR_EXPIRED,
            PairingState.ERROR: UIScreen.PAIR_ERROR,
        }
        if self.screen in {
            UIScreen.PAIR_REQUESTING,
            UIScreen.PAIR_WAITING,
            UIScreen.PAIR_PAIRED,
            UIScreen.PAIR_EXPIRED,
            UIScreen.PAIR_ERROR,
        }:
            self.screen = screens[self.pairing.state]

    def cancel_pairing(self) -> None:
        if self.pairing is not None:
            self.pairing.cancel()
        self.screen = UIScreen.HOME

    @property
    def review_image(self) -> Path | None:
        return self._store.image_path if self.screen is UIScreen.REVIEW else None

    @property
    def food_selection(self) -> FoodSelectionView:
        return self._food_selection

    @property
    def nutrition_view(self) -> NutritionView:
        return self._nutrition_view

    @property
    def ingredient_verification(self) -> IngredientVerificationView:
        return self._ingredient_verification

    @property
    def ingredient_editor(self) -> IngredientEditorView | None:
        return self._ingredient_editor

    @property
    def ingredient_candidates(self) -> IngredientCandidateView:
        return self._ingredient_candidates

    @property
    def meal_generation(self) -> int:
        """Opaque lifecycle signal for renderer-owned transient image state."""
        return self._meal_generation

    def select_nutrition_tab(self, tab: NutritionTab) -> None:
        if self.screen is UIScreen.CALCULATED:
            self._nutrition_view = NutritionView(tab)

    def previous_nutrition_page(self) -> None:
        view = self._nutrition_view
        if self.screen is UIScreen.CALCULATED and view.page > 0:
            self._nutrition_view = NutritionView(view.tab, view.page - 1)

    def next_nutrition_page(self) -> None:
        view = self._nutrition_view
        if self.screen is UIScreen.CALCULATED and view.page + 1 < view.page_count:
            self._nutrition_view = NutritionView(view.tab, view.page + 1)

    def select_food_candidate(self, visible_slot: int) -> None:
        view = self._food_selection
        index = view.page * FOOD_SELECTION_PAGE_SIZE + visible_slot
        if view.request_in_progress or not 0 <= index < len(view.names):
            return
        self._food_selection = replace(view, selected_index=index)

    def next_food_selection_page(self) -> None:
        view = self._food_selection
        pages = max(
            1,
            (len(view.names) + FOOD_SELECTION_PAGE_SIZE - 1)
            // FOOD_SELECTION_PAGE_SIZE,
        )
        if view.page + 1 < pages and not view.request_in_progress:
            self._food_selection = replace(view, page=view.page + 1)

    def previous_food_selection_page(self) -> None:
        view = self._food_selection
        if view.page > 0 and not view.request_in_progress:
            self._food_selection = replace(view, page=view.page - 1)

    def continue_food_selection(self) -> None:
        view = self._food_selection
        if view.selected_index is None or view.request_in_progress:
            return
        try:
            submitted = self.continuation.select_food_candidate(view.selected_index)
        except Exception:
            self.screen = UIScreen.ERROR
            self.error_message = FOOD_SELECTION_LIMITATION
            return
        if submitted:
            self._food_selection = replace(view, request_in_progress=True)

    def retry_food_selection(self) -> None:
        view = self._food_selection
        if view.retry_available and self.continuation.retry():
            self._food_selection = replace(
                view, request_in_progress=True, retry_available=False
            )

    def toggle_ingredient(self, visible_slot: int) -> None:
        view = self._ingredient_verification
        index = view.page * FOOD_SELECTION_PAGE_SIZE + visible_slot
        if view.request_in_progress or not 0 <= index < len(view.included):
            return
        included = list(view.included)
        included[index] = not included[index]
        states = list(self._ingredient_inclusions)
        if not 0 <= view.component_index < len(states):
            return
        states[view.component_index] = tuple(included)
        self._ingredient_inclusions = tuple(states)
        items = list(self._ingredient_items)
        items[view.component_index] = tuple(
            replace(item, included=selected)
            for item, selected in zip(
                items[view.component_index], included, strict=True
            )
        )
        self._ingredient_items = tuple(items)
        self._ingredient_verification = replace(view, included=tuple(included))

    def next_ingredient_page(self) -> None:
        view = self._ingredient_verification
        pages = max(
            1,
            (len(view.names) + FOOD_SELECTION_PAGE_SIZE - 1)
            // FOOD_SELECTION_PAGE_SIZE,
        )
        if view.page + 1 < pages and not view.request_in_progress:
            self._ingredient_verification = replace(view, page=view.page + 1)

    def previous_ingredient_page(self) -> None:
        view = self._ingredient_verification
        if view.page > 0 and not view.request_in_progress:
            self._ingredient_verification = replace(view, page=view.page - 1)

    def next_ingredient_component(self) -> None:
        view = self._ingredient_verification
        if (
            view.component_index + 1 < len(view.component_names)
            and not view.request_in_progress
        ):
            self._set_ingredient_component(view.component_index + 1)

    def previous_ingredient_component(self) -> None:
        view = self._ingredient_verification
        if view.component_index > 0 and not view.request_in_progress:
            self._set_ingredient_component(view.component_index - 1)

    def confirm_ingredients(self) -> None:
        view = self._ingredient_verification
        if view.request_in_progress or not any(view.included):
            return
        try:
            submitted = self.continuation.confirm_ingredient_items(
                view.component_index,
                IngredientVerification(self._ingredient_items[view.component_index]),
            )
        except Exception:
            self.screen = UIScreen.ERROR
            self.error_message = ANALYSIS_ERROR
            return
        if submitted:
            self._ingredient_verification = replace(view, request_in_progress=True)

    def retry_ingredient_verification(self) -> None:
        view = self._ingredient_verification
        if view.retry_available and self.continuation.retry():
            self._ingredient_verification = replace(
                view, request_in_progress=True, retry_available=False
            )

    def select_ingredient_candidate(self, visible_slot: int) -> None:
        view = self._ingredient_candidates
        index = view.candidate_page * FOOD_SELECTION_PAGE_SIZE + visible_slot
        if not view.request_in_progress and 0 <= index < len(view.candidate_names):
            self._ingredient_candidates = replace(view, selected_index=index)

    def continue_ingredient_candidate(self) -> None:
        view = self._ingredient_candidates
        if view.request_in_progress or view.selected_index is None:
            return
        try:
            submitted = self.continuation.select_ingredient_candidate_ordinal(
                view.ingredient_index, view.selected_index
            )
        except Exception:
            self.screen = UIScreen.ERROR
            self.error_message = ANALYSIS_ERROR
            return
        if submitted:
            self._ingredient_candidates = replace(view, request_in_progress=True)

    def next_ingredient_candidate_page(self) -> None:
        view = self._ingredient_candidates
        pages = max(
            1,
            (len(view.candidate_names) + FOOD_SELECTION_PAGE_SIZE - 1)
            // FOOD_SELECTION_PAGE_SIZE,
        )
        if view.candidate_page + 1 < pages:
            self._ingredient_candidates = replace(
                view, candidate_page=view.candidate_page + 1
            )

    def previous_ingredient_candidate_page(self) -> None:
        view = self._ingredient_candidates
        if view.candidate_page > 0:
            self._ingredient_candidates = replace(
                view, candidate_page=view.candidate_page - 1
            )

    def next_ingredient_candidate_item(self) -> None:
        view = self._ingredient_candidates
        if view.ingredient_index + 1 < len(view.ingredient_names):
            self._set_ingredient_candidate(view.ingredient_index + 1)

    def previous_ingredient_candidate_item(self) -> None:
        view = self._ingredient_candidates
        if view.ingredient_index > 0:
            self._set_ingredient_candidate(view.ingredient_index - 1)

    def edit_ingredient(self, visible_slot: int) -> None:
        view = self._ingredient_verification
        index = view.page * FOOD_SELECTION_PAGE_SIZE + visible_slot
        if view.request_in_progress or not 0 <= index < len(view.names):
            return
        self._ingredient_editor = IngredientEditorView(view.names[index], index, None)
        self.screen = UIScreen.INGREDIENT_EDITOR

    def add_ingredient(self) -> None:
        view = self._ingredient_verification
        if view.request_in_progress or len(view.names) >= 50:
            return
        self._ingredient_editor = IngredientEditorView("", None, None)
        self.screen = UIScreen.INGREDIENT_EDITOR

    def append_editor_text(self, value: str) -> None:
        editor = self._ingredient_editor
        if editor is None:
            return
        candidate = editor.draft + value
        self._ingredient_editor = replace(editor, draft=candidate[:160], error=None)

    def editor_backspace(self) -> None:
        if self._ingredient_editor is not None:
            self._ingredient_editor = replace(
                self._ingredient_editor,
                draft=self._ingredient_editor.draft[:-1],
                error=None,
            )

    def editor_clear(self) -> None:
        if self._ingredient_editor is not None:
            self._ingredient_editor = replace(
                self._ingredient_editor, draft="", error=None
            )

    def cancel_ingredient_editor(self) -> None:
        if self._ingredient_editor is not None:
            self._ingredient_editor = None
            self.screen = UIScreen.REQUIRES_INGREDIENT_VERIFICATION

    def apply_ingredient_editor(self) -> None:
        editor = self._ingredient_editor
        view = self._ingredient_verification
        if editor is None:
            return
        name = normalize_ingredient_name(editor.draft)
        existing = tuple(
            item.name.casefold()
            for index, item in enumerate(self._ingredient_items[view.component_index])
            if index != editor.target_index
        )
        if name is None or name.casefold() in existing:
            self._ingredient_editor = replace(
                editor, error="Enter a unique valid ingredient."
            )
            return
        component_items = list(self._ingredient_items[view.component_index])
        if editor.target_index is None:
            component_items.append(IngredientVerificationItem(name, True))
        else:
            current = component_items[editor.target_index]
            component_items[editor.target_index] = replace(current, name=name)
        all_items = list(self._ingredient_items)
        all_items[view.component_index] = tuple(component_items)
        self._ingredient_items = tuple(all_items)
        self._ingredient_inclusions = tuple(
            tuple(item.included for item in items) for items in self._ingredient_items
        )
        self._ingredient_editor = None
        self._set_ingredient_component(view.component_index)
        self.screen = UIScreen.REQUIRES_INGREDIENT_VERIFICATION

    def tick_continuation(self) -> None:
        before = self.continuation.state
        before_save = self.continuation.save_state
        self.continuation.tick()
        state = self.continuation.state
        if state is before and self.continuation.save_state is before_save:
            return
        if state is ContinuationState.RETRYABLE_ERROR:
            self._food_selection = replace(
                self._food_selection, request_in_progress=False, retry_available=True
            )
            self._ingredient_verification = replace(
                self._ingredient_verification,
                request_in_progress=False,
                retry_available=True,
            )
            self._ingredient_candidates = replace(
                self._ingredient_candidates,
                request_in_progress=False,
                retry_available=True,
            )
            return
        if state is ContinuationState.REVOKED:
            if self.pairing is not None:
                self.pairing.confirm_revocation()
            self._store.cleanup()
            self._clear_analysis_state()
            self.continuation.revoke()
            self.screen = UIScreen.HOME
            return
        if state is ContinuationState.TERMINAL_ERROR:
            message = self.continuation.error_message or ANALYSIS_ERROR
            self._food_selection = FoodSelectionView((), 0, None, False, False)
            self._clear_analysis_state()
            self.screen = UIScreen.ERROR
            self.error_message = message
            return
        if state is ContinuationState.CANCELLED:
            self._clear_analysis_state()
            self.screen = UIScreen.HOME
            return
        response = self.continuation.response
        if response is not None:
            self._show_analysis_response(response)

    def analyze(self) -> None:
        self._advance_meal_generation()
        self.error_message = None
        self.result_message = None
        self.recognized_foods = ()
        self.recognition_source = None
        self.analysis_response = None
        self.captured_weight_grams = None
        self.analysis_retry_available = False
        self.continuation.home()
        self._start_preview()

    def back(self) -> None:
        if (
            self.screen in {UIScreen.HOME, UIScreen.INSTRUCTION}
            and self.startup_shell is not None
        ):
            self.home()
            self.screen = UIScreen.LANGUAGE
            return
        if self._close_preview() and self._cleanup_or_error():
            self._clear_analysis_state()
            self.error_message = None
            self.screen = UIScreen.HOME

    def begin_capture(self) -> None:
        self.error_message = None
        self.result_message = None
        self.recognized_foods = ()
        self.recognition_source = None
        self.analysis_response = None
        self.captured_weight_grams = None
        self.analysis_retry_available = False
        self.continuation.home()
        self.screen = UIScreen.CAPTURING

    def perform_capture(self) -> None:
        if self.screen is not UIScreen.CAPTURING:
            return
        try:
            destination = self._store.prepare()
            preview = self._preview
            if preview is None:
                self._fail_after_cleanup(PREVIEW_ERROR)
                return
            result = preview.capture(destination, overwrite=False)
        except Exception:
            self._fail_after_cleanup(CAMERA_ERROR)
            return
        finally:
            preview_closed = self._close_preview()
        if not preview_closed:
            self._fail_after_cleanup(CLEANUP_ERROR)
            return
        if (
            result.ok
            and result.published
            and result.output_path == destination
            and destination.is_file()
        ):
            try:
                self.captured_weight_grams = self._controller.captured_weight_grams()
            except WeightSensorUnavailable:
                self._fail_after_cleanup(WEIGHT_ERROR)
                self.captured_weight_grams = None
                return
            except Exception:
                self._fail_after_cleanup(ANALYSIS_ERROR)
                self.captured_weight_grams = None
                return
            self.screen = UIScreen.REVIEW
            return
        self._fail_after_cleanup(CAMERA_ERROR)

    def begin_analysis(self) -> None:
        if self.screen is UIScreen.REVIEW:
            self.error_message = None
            self.result_message = None
            self._analysis_started_paired = self._paired_and_verified()
            self.screen = UIScreen.ANALYZING

    def perform_analysis(self) -> None:
        if self.screen is not UIScreen.ANALYZING:
            return
        image_path = self._store.image_path
        captured_weight = self.captured_weight_grams
        if image_path is None or captured_weight is None:
            self._fail_after_cleanup(ANALYSIS_ERROR)
            return
        result = None
        try:
            result = self._controller.analyze_meal(image_path, captured_weight)
        except RetryableBackendFailure:
            self.screen = UIScreen.ERROR
            self.error_message = ANALYSIS_ERROR
            self.analysis_retry_available = True
            return
        except DeviceAuthenticationFailure:
            if self.pairing is not None:
                self.pairing.confirm_revocation()
            self._store.cleanup()
            self._clear_analysis_state()
            self.continuation.revoke()
            self.screen = UIScreen.HOME
            return
        except Exception:
            cleaned = self._store.cleanup()
            self._clear_analysis_state()
            if not cleaned:
                self.screen = UIScreen.ERROR
                self.error_message = CLEANUP_ERROR
                return
            self.screen = UIScreen.ERROR
            self.error_message = ANALYSIS_ERROR
            return
        except BaseException:
            self._store.cleanup()
            self._clear_analysis_state()
            raise
        cleaned = self._store.cleanup()
        if not cleaned:
            self.screen = UIScreen.ERROR
            self.error_message = CLEANUP_ERROR
            return
        if result is None:
            self.screen = UIScreen.ERROR
            self.error_message = ANALYSIS_ERROR
            self._clear_analysis_state()
            return
        if isinstance(result, MealAnalysisResponse):
            self.continuation.accept_initial_response(
                result, save_permitted=self._analysis_started_paired
            )
            self._show_analysis_response(result)
        else:
            self.screen = STATUS_SCREENS[result.status]
            self.result_message = RESULT_MESSAGES[result.status]
        self.captured_weight_grams = None
        self.analysis_retry_available = False

    def retake(self) -> None:
        if self._cleanup_or_error():
            self._clear_analysis_state()
            self.error_message = None
            self._start_preview()

    def show_recognized_foods(self) -> None:
        if self.screen is UIScreen.CALCULATED:
            self.screen = UIScreen.RECOGNIZED_FOODS

    def save_meal(self) -> None:
        if self.save_enabled:
            self.continuation.save()

    @property
    def save_enabled(self) -> bool:
        return (
            self.screen is UIScreen.CALCULATED
            and self._analysis_started_paired
            and self._paired_and_verified()
            and self.continuation.save_state is SaveState.READY
        )

    @property
    def save_notice(self) -> str | None:
        response = self.continuation.response
        if (
            self.screen is UIScreen.CALCULATED
            and response is not None
            and response.analysis_session_id is not None
            and not self._analysis_started_paired
            and self._paired_and_verified()
        ):
            return "Analyze a new meal while paired to save it."
        return None

    def retry(self) -> None:
        if self.screen is UIScreen.FOOD_SELECTION:
            self.retry_food_selection()
            return
        if self.screen is UIScreen.REQUIRES_INGREDIENT_VERIFICATION:
            self.retry_ingredient_verification()
            return
        if self.analysis_retry_available and self._store.image_path is not None:
            self.analysis_retry_available = False
            self.error_message = None
            self.screen = UIScreen.REVIEW
            return
        if self._cleanup_or_error():
            self._clear_analysis_state()
            self.error_message = None
            self._start_preview()

    def home(self) -> None:
        if self._close_preview() and self._cleanup_or_error():
            self.screen = UIScreen.HOME
            self._clear_analysis_state()
            self.error_message = None

    def close(self) -> UIResult:
        if self.pairing is not None:
            self.pairing.close()
        self.continuation.close()
        self._advance_meal_generation()
        preview_closed = self._close_preview()
        if not preview_closed or not self._store.cleanup():
            self.screen = UIScreen.ERROR
            self.error_message = CLEANUP_ERROR
            return UIResult(False, CLEANUP_ERROR)
        self._clear_analysis_state()
        return UIResult(True, UI_CLOSED)

    def preview_frame(self) -> PreviewFrame | None:
        if self.screen is not UIScreen.CAPTURE or self._preview is None:
            return None
        frame = self._preview.read_frame()
        if frame is None:
            self._close_preview()
            self.screen = UIScreen.ERROR
            self.error_message = PREVIEW_ERROR
        return frame

    def _start_preview(self) -> None:
        try:
            preview = self._camera.open_preview_session()
        except Exception:
            preview = None
        if preview is None:
            self.screen = UIScreen.ERROR
            self.error_message = PREVIEW_ERROR
            return
        self._preview = preview
        self.screen = UIScreen.CAPTURE

    def _close_preview(self) -> bool:
        preview = self._preview
        self._preview = None
        if preview is None:
            return True
        try:
            return preview.close()
        except Exception:
            return False

    def _fail_after_cleanup(self, message: str) -> None:
        if not self._store.cleanup():
            message = CLEANUP_ERROR
        self.screen = UIScreen.ERROR
        self.error_message = message
        self.captured_weight_grams = None
        self.analysis_retry_available = False
        self._advance_meal_generation()

    def _clear_analysis_state(self) -> None:
        self._advance_meal_generation()
        self.continuation.home()
        self._food_selection = FoodSelectionView((), 0, None, False, False)
        self._ingredient_verification = IngredientVerificationView(
            (), (), (), 0, 0, False, False
        )
        self._ingredient_inclusions = ()
        self._ingredient_items = ()
        self._ingredient_editor = None
        self._ingredient_candidates = IngredientCandidateView(
            (), (), 0, 0, None, False, False
        )
        self.recognized_foods = ()
        self.recognition_source = None
        self.analysis_response = None
        self.captured_weight_grams = None
        self.analysis_retry_available = False
        self._nutrition_view = NutritionView()
        self._analysis_started_paired = False

    def _paired_and_verified(self) -> bool:
        pairing = self.pairing
        return pairing is not None and pairing.get_verified_device_token() is not None

    def _advance_meal_generation(self) -> None:
        self._meal_generation = getattr(self, "_meal_generation", 0) + 1

    def _show_analysis_response(self, response: MealAnalysisResponse) -> None:
        self.screen = STATUS_SCREENS[response.status]
        self.result_message = RESULT_MESSAGES[response.status]
        # The renderer receives a presentation-only response.  The continuation
        # workflow exclusively owns opaque backend IDs and candidate mappings.
        self.analysis_response = replace(
            response,
            analysis_session_id=None,
            analysis_session_expires_at=None,
            components=None,
        )
        self.recognized_foods = response.recognized_foods
        self.recognition_source = response.recognition_source
        if response.status is AnalysisStatus.REQUIRES_FOOD_SELECTION:
            names = self.continuation.food_candidate_names
            if not names:
                self.screen = UIScreen.ERROR
                self.error_message = FOOD_SELECTION_LIMITATION
                return
            self._food_selection = FoodSelectionView(names, 0, None, False, False)
        elif response.status is AnalysisStatus.REQUIRES_INGREDIENT_VERIFICATION:
            unresolved = self.continuation.unresolved_ingredient_names
            if unresolved:
                self._set_ingredient_candidate(0)
                self.screen = UIScreen.INGREDIENT_CANDIDATE_SELECTION
                return
            component_names = self.continuation.ingredient_component_names
            if not component_names:
                self._ingredient_verification = IngredientVerificationView(
                    (), (), (), 0, 0, False, False
                )
                return
            self._ingredient_inclusions = tuple(
                self.continuation.ingredient_initial_inclusions(index)
                for index in range(len(component_names))
            )
            self._ingredient_items = tuple(
                self.continuation.ingredient_items(index)
                for index in range(len(component_names))
            )
            self._set_ingredient_component(0)

    def _set_ingredient_component(self, index: int) -> None:
        component_names = self.continuation.ingredient_component_names
        if not 0 <= index < len(component_names):
            return
        names = tuple(item.name for item in self._ingredient_items[index])
        inclusions = self._ingredient_inclusions[index]
        self._ingredient_verification = IngredientVerificationView(
            component_names,
            names,
            inclusions,
            index,
            0,
            False,
            False,
        )

    def _set_ingredient_candidate(self, index: int) -> None:
        names = self.continuation.unresolved_ingredient_names
        if not 0 <= index < len(names):
            return
        self._ingredient_candidates = IngredientCandidateView(
            names,
            self.continuation.unresolved_candidate_names(index),
            index,
            0,
            None,
            False,
            False,
        )

    def _cleanup_or_error(self) -> bool:
        if self._store.cleanup():
            return True
        self.screen = UIScreen.ERROR
        self.error_message = CLEANUP_ERROR
        return False
