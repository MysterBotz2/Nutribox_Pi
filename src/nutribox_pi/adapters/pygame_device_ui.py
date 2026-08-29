"""Lazy pygame renderer for the PI-1D/PI-2A meal-analysis UI."""

from __future__ import annotations

import importlib
import sys
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from nutribox_pi.camera_factory import camera_from_env
from nutribox_pi.controller import NutriBoxController
from nutribox_pi.device_ui import (
    ANALYSIS_ERROR,
    BACKGROUND,
    BORDER,
    CARD,
    DANGER,
    DISPLAY_ERROR,
    DISPLAY_SIZE,
    ELEVATED_SURFACE,
    FOOD_SELECTION_PAGE_SIZE,
    PREVIEW_ERROR,
    PRIMARY,
    PRIMARY_MUTED,
    PRIMARY_TEXT,
    RESULT_SCREENS,
    SECONDARY_TEXT,
    UI_CLOSED,
    ButtonLayout,
    FoodSelectionView,
    MealCaptureWorkflow,
    TemporaryCaptureStore,
    UIAction,
    UIResult,
    UIScreen,
    action_at,
    buttons_for,
    scaled_image_size,
)
from nutribox_pi.models import AnalysisStatus, CalculatedResponse
from nutribox_pi.pairing import PairingState, PairingWorkflow, format_countdown
from nutribox_pi.ports import PreviewCamera
from nutribox_pi.ui_preferences import Language, UIPreferenceStore
from nutribox_pi.ui_shell import StartupShell, text

PRESSED_PRIMARY = (48, 143, 72)
PRESSED_CARD = (222, 222, 227)
WHITE = (255, 255, 255)
NUTRIBOX_BLUE = (16, 57, 128)
NUTRIBOX_BLUE_DARK = (10, 42, 97)
GRID_BLUE = (232, 240, 250)
TILE_BLUE = (235, 242, 252)
CALORIE = (245, 166, 35)
PROTEIN = (74, 144, 217)
CARBOHYDRATES = (244, 125, 111)
FAT = (247, 206, 104)
FIBER = (78, 205, 196)
SUGAR = (194, 125, 218)
REVIEW_BOUNDS = (620, 300)
PREVIEW_BOUNDS = (420, 236)
PREVIEW_INTERVAL_SECONDS = 1 / 15
THUMBNAIL_BOUNDS = (150, 84)


def display_flags_for(platform: str, fullscreen_flag: int) -> int:
    """Single deterministic native-display decision boundary."""
    return 0 if platform.startswith("win") else fullscreen_flag


def run_device_ui(
    camera: PreviewCamera | None = None,
    controller: NutriBoxController | None = None,
    *,
    simulated_weight: bool = False,
    pygame_module: Any | None = None,
    store: TemporaryCaptureStore | None = None,
    pairing: PairingWorkflow | None = None,
    preference_store: UIPreferenceStore | None = None,
    platform: str | None = None,
) -> UIResult:
    pygame = pygame_module
    if pygame is None:
        try:
            pygame = importlib.import_module("pygame")
        except Exception:
            return UIResult(False, DISPLAY_ERROR)

    workflow: MealCaptureWorkflow | None = None
    outcome = UIResult(False, DISPLAY_ERROR)
    cleanup_result = UIResult(True, UI_CLOSED)
    try:
        pygame.init()
        pygame.display.init()
        if not pygame.display.get_init():
            return outcome
        display_flags = display_flags_for(platform or sys.platform, pygame.FULLSCREEN)
        screen = pygame.display.set_mode(DISPLAY_SIZE, display_flags)

        if tuple(screen.get_size()) != DISPLAY_SIZE:
            return outcome
        pygame.display.set_caption("Nutri-Box")
        fonts = _Fonts(
            heading=pygame.font.Font(None, 48),
            subheading=pygame.font.Font(None, 34),
            body=pygame.font.Font(None, 28),
            small=pygame.font.Font(None, 20),
            button=pygame.font.Font(None, 32),
        )
        if controller is None:
            outcome = UIResult(False, ANALYSIS_ERROR)
            return outcome
        workflow = MealCaptureWorkflow(
            camera or camera_from_env(),
            controller,
            store,
            simulated_weight,
            pairing,
            StartupShell(preference_store or UIPreferenceStore()),
        )
        outcome = _run_loop(pygame, screen, fonts, workflow)
    except Exception:
        outcome = UIResult(False, DISPLAY_ERROR)
    finally:
        if workflow is not None:
            cleanup_result = workflow.close()
        with suppress(Exception):
            pygame.quit()
    if not cleanup_result.ok:
        return cleanup_result
    return outcome


class _PreviewSurfaceCache:
    def __init__(self) -> None:
        self.surface: Any | None = None

    def update(self, pygame: Any, frame: Any) -> None:
        detached = pygame.image.frombuffer(
            frame.rgb_bytes,
            (frame.width, frame.height),
            "RGB",
        ).copy()
        size = scaled_image_size((frame.width, frame.height), PREVIEW_BOUNDS)
        self.surface = pygame.transform.smoothscale(detached, size)

    def clear(self) -> None:
        self.surface = None


class _UiImageCache:
    """Renderer-owned detached surfaces; no capture file ownership."""

    def __init__(self) -> None:
        self.review_surface: Any | None = None
        self.thumbnail: Any | None = None
        self._image_path: object | None = None

    def capture_review_image(self, pygame: Any, image_path: object) -> Any:
        if self._image_path != image_path or self.review_surface is None:
            image = pygame.image.load(str(image_path))
            if tuple(image.get_size()) != (1920, 1080):
                raise RuntimeError
            detached = image.copy()
            self.review_surface = pygame.transform.smoothscale(
                detached, scaled_image_size((1920, 1080), (450, 300))
            )
            self.thumbnail = pygame.transform.smoothscale(
                detached, scaled_image_size((1920, 1080), THUMBNAIL_BOUNDS)
            )
            self._image_path = image_path
        return self.review_surface

    def clear(self) -> None:
        self.review_surface = None
        self.thumbnail = None
        self._image_path = None


class _Fonts:
    def __init__(
        self, *, heading: Any, subheading: Any, body: Any, small: Any, button: Any
    ) -> None:
        self.heading = heading
        self.subheading = subheading
        self.body = body
        self.small = small
        self.button = button


@dataclass(frozen=True, slots=True)
class _PointerPress:
    """A gesture bound to the screen and input source where it began."""

    source: tuple[str, int | None]
    screen: UIScreen
    action: UIAction


def _run_loop(
    pygame: Any,
    screen: Any,
    fonts: _Fonts,
    workflow: MealCaptureWorkflow,
) -> UIResult:
    pressed: _PointerPress | None = None
    next_preview_at = 0.0
    preview_cache = _PreviewSurfaceCache()
    image_cache = _UiImageCache()
    while True:
        workflow.tick_startup()
        workflow.tick_pairing()
        workflow.tick_continuation()
        if workflow.screen is UIScreen.CAPTURE:
            now = time.monotonic()
            if now >= next_preview_at:
                preview = workflow.preview_frame()
                if preview is not None:
                    preview_cache.update(pygame, preview)
                next_preview_at = now + PREVIEW_INTERVAL_SECONDS
        else:
            preview_cache.clear()
        _render(
            pygame,
            screen,
            fonts,
            workflow,
            pressed,
            preview_cache.surface,
            image_cache,
        )
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return UIResult(True, UI_CLOSED)
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return UIResult(True, UI_CLOSED)
            pointer = _pointer_event(pygame, event, down=True)
            if pointer is not None:
                source, point = pointer
                action = action_at(
                    workflow.screen,
                    *point,
                    _pairing_state(workflow),
                    _food_selection(workflow),
                )
                if pressed is not None or action is None:
                    continue
                pressed = _PointerPress(source, workflow.screen, action)
                _render(
                    pygame,
                    screen,
                    fonts,
                    workflow,
                    pressed.action,
                    preview_cache.surface,
                    image_cache,
                )
                continue
            pointer = _pointer_event(pygame, event, down=False)
            if pointer is None:
                continue
            source, point = pointer
            active_press = pressed
            if active_press is None or source != active_press.source:
                continue
            pressed = None
            if workflow.screen is not active_press.screen:
                continue
            if (
                action_at(
                    active_press.screen,
                    *point,
                    _pairing_state(workflow),
                    _food_selection(workflow),
                )
                is not active_press.action
            ):
                pressed = None
                continue
            outcome = _apply_action(
                pygame,
                screen,
                fonts,
                workflow,
                active_press.action,
                preview_cache.surface,
                image_cache,
            )
            if outcome is not None:
                return outcome
            if workflow.screen is not active_press.screen:
                _discard_pointer_events(pygame)
                # The rest of this batch originated before the synchronous
                # transition.  Never reinterpret it against the new screen.
                break
        if workflow.screen is UIScreen.CAPTURE:
            remaining = next_preview_at - time.monotonic()
            if remaining > 0:
                pygame.time.wait(max(1, round(remaining * 1000)))


def _apply_action(
    pygame: Any,
    screen: Any,
    fonts: _Fonts,
    workflow: MealCaptureWorkflow,
    action: UIAction | None,
    preview_surface: Any | None = None,
    image_cache: _UiImageCache | None = None,
) -> UIResult | None:
    if action is None:
        return None

    if action is UIAction.EXIT:
        if image_cache is not None:
            image_cache.clear()
        return UIResult(True, UI_CLOSED)
    if action is UIAction.SELECT_ENGLISH:
        workflow.select_language(Language.ENGLISH)
    elif action is UIAction.SELECT_TAGALOG:
        workflow.select_language(Language.TAGALOG)
    elif action is UIAction.TOGGLE_INTRO:
        workflow.toggle_intro()
    elif action is UIAction.HELP:
        workflow.screen = UIScreen.INSTRUCTION
    elif action is UIAction.CONTINUE:
        workflow.continue_from_instruction()
    elif action is UIAction.ANALYZE:
        workflow.analyze()
    elif action is UIAction.PAIR_DEVICE:
        workflow.start_pairing()
    elif action is UIAction.CANCEL_PAIRING:
        workflow.cancel_pairing()
    elif action in {
        UIAction.SELECT_FOOD_0,
        UIAction.SELECT_FOOD_1,
        UIAction.SELECT_FOOD_2,
        UIAction.SELECT_FOOD_3,
    }:
        workflow.select_food_candidate(
            (
                UIAction.SELECT_FOOD_0,
                UIAction.SELECT_FOOD_1,
                UIAction.SELECT_FOOD_2,
                UIAction.SELECT_FOOD_3,
            ).index(action)
        )
    elif action is UIAction.FOOD_PREVIOUS:
        workflow.previous_food_selection_page()
    elif action is UIAction.FOOD_NEXT:
        workflow.next_food_selection_page()
    elif action is UIAction.FOOD_CONTINUE:
        workflow.continue_food_selection()
    elif action is UIAction.BACK:
        workflow.back()
    elif action is UIAction.CAPTURE:
        if image_cache is not None:
            image_cache.clear()
        workflow.begin_capture()
        _render(pygame, screen, fonts, workflow, None, preview_surface)
        pygame.event.pump()
        workflow.perform_capture()
    elif action is UIAction.ANALYZE_MEAL:
        if image_cache is not None:
            image_cache.clear()
        workflow.begin_analysis()
        _render(pygame, screen, fonts, workflow, None)
        pygame.event.pump()
        workflow.perform_analysis()
    elif action is UIAction.RETAKE:
        if image_cache is not None:
            image_cache.clear()
        workflow.retake()
    elif action is UIAction.SHOW_RECOGNIZED_FOODS:
        workflow.show_recognized_foods()
    elif action is UIAction.ANALYZE_AGAIN:
        if image_cache is not None:
            image_cache.clear()
        workflow.retake()
    elif action is UIAction.RETRY:
        if workflow.screen is UIScreen.FOOD_SELECTION:
            workflow.retry_food_selection()
        elif workflow.screen in {UIScreen.PAIR_EXPIRED, UIScreen.PAIR_ERROR}:
            workflow.start_pairing()
        else:
            workflow.retry()
    elif action is UIAction.HOME:
        if image_cache is not None:
            image_cache.clear()
        if workflow.screen in {
            UIScreen.PAIR_REQUESTING,
            UIScreen.PAIR_WAITING,
            UIScreen.PAIR_EXPIRED,
            UIScreen.PAIR_ERROR,
        }:
            workflow.cancel_pairing()
        else:
            workflow.home()
    return None


def _pointer_event(
    pygame: Any, event: Any, *, down: bool
) -> tuple[tuple[str, int | None], tuple[float, float]] | None:
    mouse_type = pygame.MOUSEBUTTONDOWN if down else pygame.MOUSEBUTTONUP
    finger_type = pygame.FINGERDOWN if down else pygame.FINGERUP
    if event.type == mouse_type and event.button == 1:
        return ("mouse", None), (float(event.pos[0]), float(event.pos[1]))
    if event.type == finger_type:
        finger_id = getattr(event, "finger_id", getattr(event, "touch_id", None))
        return (
            ("finger", finger_id),
            (event.x * DISPLAY_SIZE[0], event.y * DISPLAY_SIZE[1]),
        )
    return None


def _discard_pointer_events(pygame: Any) -> None:
    clear = getattr(pygame.event, "clear", None)
    if callable(clear):
        clear(
            [
                pygame.MOUSEBUTTONDOWN,
                pygame.MOUSEBUTTONUP,
                pygame.FINGERDOWN,
                pygame.FINGERUP,
            ]
        )


def _render(
    pygame: Any,
    screen: Any,
    fonts: _Fonts,
    workflow: MealCaptureWorkflow,
    pressed: UIAction | None,
    preview: Any | None = None,
    image_cache: _UiImageCache | None = None,
) -> None:
    _draw_grid(pygame, screen)
    cache = image_cache or _UiImageCache()
    if workflow.screen is UIScreen.LOADING:
        _render_loading(pygame, screen, fonts, workflow)
    elif workflow.screen is UIScreen.LANGUAGE:
        _render_language(pygame, screen, fonts, workflow)
    elif workflow.screen is UIScreen.INSTRUCTION:
        _render_instruction(pygame, screen, fonts, workflow)
    elif workflow.screen is UIScreen.HOME:
        _render_home(pygame, screen, fonts, workflow)
    elif workflow.screen in {UIScreen.CAPTURE, UIScreen.CAPTURING}:
        _render_capture(pygame, screen, fonts, workflow, preview)
    elif workflow.screen is UIScreen.REVIEW:
        _render_review(pygame, screen, fonts, workflow, cache)
    elif workflow.screen is UIScreen.ANALYZING:
        _render_analyzing(pygame, screen, fonts, workflow)
    elif workflow.screen is UIScreen.FOOD_SELECTION:
        _render_food_selection(pygame, screen, fonts, workflow)
    elif workflow.screen in RESULT_SCREENS:
        _render_result(pygame, screen, fonts, workflow, cache.thumbnail)
    elif workflow.screen is UIScreen.RECOGNIZED_FOODS:
        _render_recognized_foods(pygame, screen, fonts, workflow, cache.thumbnail)
    elif workflow.screen in {
        UIScreen.PAIR_REQUESTING,
        UIScreen.PAIR_WAITING,
        UIScreen.PAIR_PAIRED,
        UIScreen.PAIR_EXPIRED,
        UIScreen.PAIR_ERROR,
    }:
        _render_pairing(pygame, screen, fonts, workflow)
    else:
        _render_error(pygame, screen, fonts, workflow.error_message, workflow.language)
    for button in buttons_for(
        workflow.screen, _pairing_state(workflow), _food_selection(workflow)
    ):
        button = _localized_button(button, workflow)
        _draw_button(pygame, screen, fonts.button, button, pressed is button.action)
    pygame.display.flip()


def _pairing_state(workflow: MealCaptureWorkflow) -> Any:
    return workflow.pairing.state if workflow.pairing is not None else None


def _food_selection(workflow: MealCaptureWorkflow) -> FoodSelectionView | None:
    return (
        workflow.food_selection if workflow.screen is UIScreen.FOOD_SELECTION else None
    )


def _localized_button(
    button: ButtonLayout, workflow: MealCaptureWorkflow
) -> ButtonLayout:
    language = workflow.language
    keys = {
        UIAction.ANALYZE: "analyze",
        UIAction.BACK: "back",
        UIAction.EXIT: "exit",
        UIAction.PAIR_DEVICE: "pair",
        UIAction.CONTINUE: "skip",
        UIAction.SELECT_ENGLISH: "english",
        UIAction.SELECT_TAGALOG: "tagalog",
        UIAction.FOOD_PREVIOUS: "previous",
        UIAction.FOOD_NEXT: "next",
        UIAction.FOOD_CONTINUE: "continue_food",
    }
    key = keys.get(button.action)
    if button.action is UIAction.TOGGLE_INTRO:
        selected = (
            workflow.startup_shell.preferences.show_intro_on_startup
            if workflow.startup_shell is not None
            else True
        )
        label = f"{'[x]' if selected else '[ ]'} {text(language, 'show_intro')}"
        return ButtonLayout(
            button.action, label, button.rectangle, button.role, button.enabled
        )
    if button.action is UIAction.PAIR_DEVICE and not button.enabled:
        key = "paired" if button.label == "Device paired" else "checking"
    if button.action is UIAction.CAPTURE:
        key = "capture_meal"
    if workflow.screen is UIScreen.REVIEW:
        if button.action is UIAction.ANALYZE_MEAL:
            key = "yes"
        elif button.action is UIAction.RETAKE:
            key = "no"
    if button.action is UIAction.RETRY:
        key = "retry"
    if key is None:
        return button
    return ButtonLayout(
        button.action,
        text(language, key),
        button.rectangle,
        button.role,
        button.enabled,
    )


def _render_loading(
    pygame: Any, screen: Any, fonts: _Fonts, workflow: MealCaptureWorkflow
) -> None:
    shell = workflow.startup_shell
    progress = shell.progress if shell is not None else 0.0
    _draw_brand_mark(pygame, screen, (400, 132))
    _draw_wordmark(screen, fonts, (400, 205))
    pygame.draw.rect(screen, BORDER, (190, 258, 420, 16), border_radius=8)
    pygame.draw.rect(
        screen, PRIMARY, (190, 258, round(420 * progress), 16), border_radius=8
    )
    _draw_text(screen, fonts.body, "Loading...", (400, 306), PRIMARY_TEXT)
    _draw_card(pygame, screen, (180, 350, 440, 76))
    _draw_text(
        screen,
        fonts.small,
        "Tip: Add variety for a balanced meal.",
        (400, 388),
        SECONDARY_TEXT,
    )


def _render_language(
    pygame: Any, screen: Any, fonts: _Fonts, workflow: MealCaptureWorkflow
) -> None:
    language = workflow.language
    _draw_text(
        screen,
        fonts.subheading,
        text(language, "choose_language"),
        (400, 112),
        PRIMARY_TEXT,
    )


def _render_instruction(
    pygame: Any, screen: Any, fonts: _Fonts, workflow: MealCaptureWorkflow
) -> None:
    language = workflow.language
    _draw_card(pygame, screen, (24, 48, 520, 330))
    _draw_brand_mark(pygame, screen, (284, 170))
    _draw_text(
        screen,
        fonts.body,
        text(language, "media_unavailable"),
        (284, 270),
        SECONDARY_TEXT,
    )
    _draw_card(pygame, screen, (558, 48, 218, 330))
    _draw_text(
        screen, fonts.body, text(language, "instructions"), (667, 92), PRIMARY_TEXT
    )
    lines = (
        (
            "1. Place meal on plate.",
            "2. Select Analyze Meal.",
            "3. Keep meal in frame.",
            "4. Review the results.",
        )
        if language is Language.ENGLISH
        else (
            "1. Ilagay ang pagkain.",
            "2. Piliin ang Suriin.",
            "3. Panatilihin sa frame.",
            "4. Suriin ang resulta.",
        )
    )
    for index, line in enumerate(lines):
        _draw_text(screen, fonts.small, line, (667, 142 + index * 42), PRIMARY_TEXT)


def _render_home(
    pygame: Any, screen: Any, fonts: _Fonts, workflow: MealCaptureWorkflow
) -> None:
    _draw_brand_mark(pygame, screen, (400, 128))
    language = getattr(workflow, "language", Language.ENGLISH)
    heading_font = getattr(fonts, "subheading", fonts.heading)
    fitting_font = heading_font if hasattr(heading_font, "size") else fonts.small
    _draw_text(
        screen,
        heading_font,
        _ellipsize(fitting_font, text(language, "ready"), 560),
        (400, 205),
        PRIMARY_TEXT,
    )
    if workflow.pairing is not None and workflow.pairing.state is PairingState.PAIRED:
        name = _ellipsize(fonts.small, workflow.pairing.device.owner_first_name, 240)
        if workflow.pairing.greeting:
            _draw_text(
                screen,
                fonts.small,
                _ellipsize(fonts.small, workflow.pairing.greeting, 420),
                (400, 404),
                PRIMARY_TEXT,
            )
        _draw_text(
            screen, fonts.small, f"Paired with {name}", (400, 430), SECONDARY_TEXT
        )
    elif workflow.pairing is not None and workflow.pairing.error_message:
        _draw_text(
            screen,
            fonts.small,
            workflow.pairing.error_message,
            (400, 410),
            SECONDARY_TEXT,
        )


def _render_pairing(
    pygame: Any, screen: Any, fonts: _Fonts, workflow: MealCaptureWorkflow
) -> None:
    pairing = workflow.pairing
    _draw_text(screen, fonts.subheading, "Pair Device", (400, 100), NUTRIBOX_BLUE)
    _draw_card(pygame, screen, (100, 140, 600, 180))
    if pairing is None:
        message = "Device pairing is unavailable."
    elif workflow.screen is UIScreen.PAIR_WAITING:
        message = pairing.code or "Waiting for pairing code..."
    elif workflow.screen is UIScreen.PAIR_PAIRED:
        message = pairing.greeting or "Device paired."
    elif workflow.screen is UIScreen.PAIR_EXPIRED:
        message = "Pairing code expired."
    elif workflow.screen is UIScreen.PAIR_ERROR:
        message = pairing.error_message or "Device pairing is unavailable."
    else:
        message = "Requesting pairing code..."
    _draw_text(screen, fonts.body, message, (400, 220), PRIMARY_TEXT)
    if pairing is not None and workflow.screen is UIScreen.PAIR_WAITING:
        _draw_text(
            screen,
            fonts.small,
            format_countdown(pairing.remaining_seconds()),
            (400, 270),
            SECONDARY_TEXT,
        )


def _render_capture(
    pygame: Any,
    screen: Any,
    fonts: _Fonts,
    workflow: MealCaptureWorkflow,
    preview: Any | None,
) -> None:
    language = workflow.language
    state = workflow.screen
    _draw_text(
        screen,
        fonts.subheading,
        text(language, "camera_preview"),
        (280, 34),
        PRIMARY_TEXT,
    )
    _draw_card(pygame, screen, (20, 56, 520, 372))
    _draw_card(pygame, screen, (558, 86, 222, 174))
    message = (
        text(language, "capture_meal") + "..."
        if state is UIScreen.CAPTURING
        else (
            text(language, "simulated_preview")
            if workflow.simulated_camera
            else text(language, "live_preview")
        )
    )
    _draw_text(screen, fonts.small, message, (280, 402), SECONDARY_TEXT)
    _draw_text(screen, fonts.body, text(language, "weight"), (669, 126), PRIMARY_TEXT)
    _draw_text(screen, fonts.small, "Measured at capture", (669, 174), SECONDARY_TEXT)
    if preview is not None:
        target_size = tuple(preview.get_size())
        left = 30 + (500 - target_size[0]) // 2
        top = 66 + (320 - target_size[1]) // 2
        screen.blit(preview, (left, top))
    else:
        _draw_text(
            screen,
            fonts.body,
            "Starting camera preview...",
            (280, 220),
            SECONDARY_TEXT,
        )


def _render_review(
    pygame: Any,
    screen: Any,
    fonts: _Fonts,
    workflow: MealCaptureWorkflow,
    image_cache: _UiImageCache,
) -> None:
    image_path = workflow.review_image
    if image_path is None:
        raise RuntimeError
    image = image_cache.capture_review_image(pygame, image_path)
    language = workflow.language
    _draw_card(pygame, screen, (20, 20, 520, 420))
    image_size = tuple(image.get_size())
    left = 24 + (512 - image_size[0]) // 2
    top = 45 + (350 - image_size[1]) // 2
    screen.blit(image, (left, top))
    _draw_corner_marks(pygame, screen, (left, top, image_size[0], image_size[1]))
    _draw_text(
        screen,
        fonts.small,
        text(language, "captured_preview"),
        (280, 416),
        SECONDARY_TEXT,
    )
    _draw_text(screen, fonts.body, text(language, "weight"), (670, 70), PRIMARY_TEXT)
    weight = workflow.captured_weight_grams
    _draw_text(
        screen,
        fonts.body,
        f"{weight:g} g" if weight is not None else "--",
        (670, 112),
        PRIMARY_TEXT,
    )
    _draw_text(
        screen,
        fonts.body,
        _ellipsize(fonts.body, text(language, "meal_clear"), 210),
        (670, 190),
        PRIMARY_TEXT,
    )


def _render_analyzing(
    pygame: Any, screen: Any, fonts: _Fonts, workflow: MealCaptureWorkflow
) -> None:
    _draw_magnifier_illustration(pygame, screen, (400, 160))
    _draw_text(
        screen,
        fonts.subheading,
        text(workflow.language, "analyzing_meal"),
        (400, 300),
        NUTRIBOX_BLUE,
    )
    if workflow.simulated_weight:
        _draw_text(
            screen,
            fonts.small,
            "Development mode: simulated weight",
            (400, 335),
            SECONDARY_TEXT,
        )


def _render_food_selection(
    pygame: Any, screen: Any, fonts: _Fonts, workflow: MealCaptureWorkflow
) -> None:
    """Render only safe names and ordinal selection state from the workflow."""
    view = workflow.food_selection
    _draw_text(
        screen,
        fonts.subheading,
        text(workflow.language, "food_selection_title"),
        (400, 48),
        NUTRIBOX_BLUE,
    )
    _draw_text(
        screen,
        fonts.small,
        text(workflow.language, "food_selection_prompt"),
        (400, 78),
        SECONDARY_TEXT,
    )
    page_count = max(
        1,
        (len(view.names) + FOOD_SELECTION_PAGE_SIZE - 1) // FOOD_SELECTION_PAGE_SIZE,
    )
    _draw_text(
        screen,
        fonts.small,
        f"{view.page + 1}/{page_count}",
        (740, 78),
        SECONDARY_TEXT,
    )
    if view.request_in_progress:
        _draw_text(
            screen,
            fonts.small,
            text(workflow.language, "food_selection_submitting"),
            (400, 338),
            SECONDARY_TEXT,
        )
    elif view.retry_available:
        _draw_text(
            screen,
            fonts.small,
            text(workflow.language, "food_selection_retry"),
            (400, 338),
            SECONDARY_TEXT,
        )


def _render_result(
    pygame: Any,
    screen: Any,
    fonts: _Fonts,
    workflow: MealCaptureWorkflow,
    thumbnail: Any | None = None,
) -> None:
    response = workflow.analysis_response
    if response is None:
        _draw_text(screen, fonts.subheading, "Meal analysis", (400, 90), NUTRIBOX_BLUE)
        _draw_card(pygame, screen, (100, 130, 600, 140))
        _draw_text(
            screen,
            fonts.body,
            workflow.result_message or ANALYSIS_ERROR,
            (400, 190),
            SECONDARY_TEXT,
        )
        return
    if response.status is AnalysisStatus.CALCULATED and isinstance(
        response, CalculatedResponse
    ):
        _render_nutrition_contents(pygame, screen, fonts, workflow, thumbnail)
        return
    _draw_text(screen, fonts.subheading, "Meal analysis", (400, 55), NUTRIBOX_BLUE)
    _draw_card(pygame, screen, (55, 95, 690, 260))
    source = (
        "Simulated recognition"
        if response.recognition_source.value == "simulated"
        else "AI recognition"
    )
    _draw_text(screen, fonts.small, source, (310, 125), SECONDARY_TEXT)
    if response.status is AnalysisStatus.FOOD_NOT_RECOGNIZED:
        _draw_text(screen, fonts.body, "No food recognized", (400, 220), PRIMARY_TEXT)
        return
    if response.status is AnalysisStatus.REQUIRES_FOOD_SELECTION:
        _draw_text(
            screen,
            fonts.body,
            "Food selection is required",
            (400, 170),
            PRIMARY_TEXT,
        )
        _draw_foods(screen, fonts, response.recognized_foods, 210)
        return
    food = (
        response.recognized_foods[0].name
        if response.recognized_foods
        else "Recognized food"
    )
    if response.status is AnalysisStatus.NUTRITION_REFERENCE_NOT_FOUND:
        _draw_text(
            screen,
            fonts.body,
            _ellipsize(fonts.body, food, 560),
            (400, 195),
            PRIMARY_TEXT,
        )
        _draw_text(
            screen,
            fonts.small,
            "No nutrition reference is available.",
            (400, 245),
            SECONDARY_TEXT,
        )
        return
    _draw_text(screen, fonts.body, ANALYSIS_ERROR, (400, 220), SECONDARY_TEXT)


def _render_nutrition_contents(
    pygame: Any,
    screen: Any,
    fonts: _Fonts,
    workflow: MealCaptureWorkflow,
    thumbnail: Any | None,
) -> None:
    response = workflow.analysis_response
    assert isinstance(response, CalculatedResponse)
    _draw_text(
        screen, fonts.subheading, "Nutritional Contents", (235, 48), NUTRIBOX_BLUE
    )
    food = response.recognized_foods[0].name if response.recognized_foods else "Meal"
    _draw_text(
        screen,
        fonts.small,
        _ellipsize(fonts.small, food, 400),
        (215, 78),
        SECONDARY_TEXT,
    )
    nutrition = response.nutrition
    values = nutrition.values
    tiles = (
        ("Energy", nutrition.calories, CALORIE),
        ("Protein", nutrition.protein, PROTEIN),
        ("Carbohydrates", nutrition.carbohydrates, CARBOHYDRATES),
        ("Total fat", nutrition.fat, FAT),
        ("Fiber", nutrition.fiber, FIBER),
        ("Saturated fat", values.get("saturated_fat"), FAT),
        ("Sugars", values.get("sugars"), SUGAR),
        ("Sodium", values.get("sodium"), PROTEIN),
    )
    for index, (label, value, color) in enumerate(tiles):
        x = 28 + (index % 4) * 190
        y = 108 + (index // 4) * 118
        _draw_nutrient_tile(pygame, screen, fonts, (x, y, 170, 96), label, value, color)
    if workflow.simulated_weight:
        _draw_text(
            screen,
            fonts.small,
            "Development mode: simulated weight",
            (280, 365),
            SECONDARY_TEXT,
        )


def _draw_nutrient_tile(
    pygame: Any,
    screen: Any,
    fonts: _Fonts,
    rectangle: tuple[int, int, int, int],
    label: str,
    value: str | None,
    color: tuple[int, int, int],
) -> None:
    pygame.draw.rect(screen, TILE_BLUE, rectangle, border_radius=12)
    pygame.draw.rect(screen, color, rectangle, width=2, border_radius=12)
    x, y, width, _ = rectangle
    _draw_text(screen, fonts.small, label, (x + width // 2, y + 25), PRIMARY_TEXT)
    _draw_text(
        screen,
        fonts.body,
        value if value is not None else "—",
        (x + width // 2, y + 62),
        color,
    )


def _draw_thumbnail(
    pygame: Any, screen: Any, thumbnail: Any | None, point: tuple[int, int]
) -> None:
    if thumbnail is None:
        return
    size = tuple(thumbnail.get_size())
    rectangle = (point[0] - 5, point[1] - 5, size[0] + 10, size[1] + 10)
    _draw_card(pygame, screen, rectangle)
    screen.blit(thumbnail, point)


def _draw_food_chips(
    pygame: Any, screen: Any, fonts: _Fonts, foods: tuple[Any, ...]
) -> None:
    x, y, row_height = 55, 160, 43
    for food in foods[:10]:
        name = _ellipsize(fonts.small, food.name, 180)
        width = min(190, max(85, fonts.small.size(name)[0] + 28))
        if x + width > 745:
            x, y = 55, y + row_height
        pygame.draw.rect(screen, TILE_BLUE, (x, y, width, 31), border_radius=15)
        _draw_text(screen, fonts.small, name, (x + width // 2, y + 16), NUTRIBOX_BLUE)
        x += width + 10


def _draw_foods(screen: Any, fonts: _Fonts, foods: tuple[Any, ...], top: int) -> None:
    for index, food in enumerate(foods):
        _draw_text(
            screen,
            fonts.small,
            _ellipsize(fonts.small, food.name, 560),
            (400, top + index * 20),
            PRIMARY_TEXT,
        )


def _render_recognized_foods(
    pygame: Any,
    screen: Any,
    fonts: _Fonts,
    workflow: MealCaptureWorkflow,
    thumbnail: Any | None,
) -> None:
    _draw_text(screen, fonts.subheading, "Recognized Foods", (235, 54), NUTRIBOX_BLUE)
    _draw_card(pygame, screen, (30, 95, 740, 285))
    source = (
        "Simulated recognition"
        if workflow.recognition_source is not None
        and workflow.recognition_source.value == "simulated"
        else "AI recognition"
    )
    _draw_text(screen, fonts.small, source, (190, 125), SECONDARY_TEXT)
    if not workflow.recognized_foods:
        _draw_text(screen, fonts.body, "No food recognized", (400, 220), PRIMARY_TEXT)
        return
    _draw_food_chips(pygame, screen, fonts, workflow.recognized_foods)


def _ellipsize(font: Any, text: str, maximum_width: int) -> str:
    if font.size(text)[0] <= maximum_width:
        return text
    shortened = text
    while shortened and font.size(shortened + "...")[0] > maximum_width:
        shortened = shortened[:-1]
    return shortened + "..."


def _draw_grid(pygame: Any, screen: Any) -> None:
    screen.fill(BACKGROUND)
    if not hasattr(pygame, "draw"):
        return
    pygame.draw.circle(screen, (239, 248, 232), (30, 450), 110)
    pygame.draw.circle(screen, (230, 243, 220), (780, 445), 92)


def _draw_brand_mark(pygame: Any, screen: Any, center: tuple[int, int]) -> None:
    """Clean shape fallback until a standalone client logo is supplied."""
    if not hasattr(pygame, "draw"):
        return
    x, y = center
    pygame.draw.rect(screen, PRIMARY, (x - 34, y - 25, 68, 52), border_radius=8)
    pygame.draw.line(screen, WHITE, (x - 27, y - 15), (x, y), 4)
    pygame.draw.line(screen, WHITE, (x + 27, y - 15), (x, y), 4)
    pygame.draw.line(screen, WHITE, (x, y), (x, y + 22), 4)
    pygame.draw.line(screen, PRIMARY, (x, y - 25), (x, y - 44), 5)
    pygame.draw.ellipse(screen, PRIMARY, (x - 23, y - 49, 23, 13))
    pygame.draw.ellipse(screen, PRIMARY, (x, y - 53, 25, 14))


def _draw_wordmark(screen: Any, fonts: _Fonts, center: tuple[int, int]) -> None:
    _draw_text(screen, fonts.heading, "Nutri-Box", center, NUTRIBOX_BLUE)


def _draw_corner_marks(
    pygame: Any, screen: Any, rectangle: tuple[int, int, int, int]
) -> None:
    x, y, width, height = rectangle
    length, line_width = 24, 4
    for start, horizontal, vertical in (
        ((x, y), (x + length, y), (x, y + length)),
        ((x + width, y), (x + width - length, y), (x + width, y + length)),
        ((x, y + height), (x + length, y + height), (x, y + height - length)),
        (
            (x + width, y + height),
            (x + width - length, y + height),
            (x + width, y + height - length),
        ),
    ):
        pygame.draw.line(screen, WHITE, start, horizontal, line_width)
        pygame.draw.line(screen, WHITE, start, vertical, line_width)


def _draw_magnifier_illustration(
    pygame: Any, screen: Any, center: tuple[int, int]
) -> None:
    x, y = center
    pygame.draw.circle(screen, NUTRIBOX_BLUE, (x - 15, y - 15), 65, width=8)
    pygame.draw.line(screen, NUTRIBOX_BLUE, (x + 30, y + 30), (x + 90, y + 90), 15)
    pygame.draw.circle(screen, CARD, (x - 15, y - 15), 53)
    pygame.draw.circle(screen, CALORIE, (x - 35, y - 30), 15)
    pygame.draw.circle(screen, FIBER, (x + 5, y - 8), 17)
    pygame.draw.circle(screen, CARBOHYDRATES, (x - 15, y + 22), 14)


def _render_error(
    pygame: Any,
    screen: Any,
    fonts: _Fonts,
    message: str | None,
    language: Language = Language.ENGLISH,
) -> None:
    safe_message = {
        PREVIEW_ERROR: text(language, "camera_error"),
        ANALYSIS_ERROR: text(language, "network_error"),
    }.get(message, message or "Unable to continue safely.")
    heading = (
        "Nagkaroon ng problema"
        if language is Language.TAGALOG
        else "Something went wrong"
    )
    _draw_text(screen, fonts.heading, heading, (400, 125), DANGER)
    _draw_card(pygame, screen, (100, 175, 600, 110))
    _draw_text(
        screen,
        fonts.body,
        _ellipsize(fonts.body, safe_message, 560),
        (400, 230),
        SECONDARY_TEXT,
    )


def _draw_card(pygame: Any, screen: Any, rectangle: tuple[int, int, int, int]) -> None:
    pygame.draw.rect(screen, CARD, rectangle, border_radius=16)
    pygame.draw.rect(screen, BORDER, rectangle, width=2, border_radius=16)


def _draw_button(
    pygame: Any,
    screen: Any,
    font: Any,
    button: ButtonLayout,
    pressed: bool,
) -> None:
    if not button.enabled:
        color, text_color = PRIMARY_MUTED, SECONDARY_TEXT
    elif button.role == "danger":
        color, text_color = DANGER, WHITE
    elif button.role == "card":
        color = PRESSED_CARD if pressed else ELEVATED_SURFACE
        text_color = PRIMARY_TEXT
    elif button.role == "navy":
        color = NUTRIBOX_BLUE_DARK if pressed else NUTRIBOX_BLUE
        text_color = WHITE
    else:
        color = PRESSED_PRIMARY if pressed else PRIMARY
        text_color = WHITE
    rectangle = button.rectangle.as_tuple()
    pygame.draw.rect(screen, color, rectangle, border_radius=12)
    if button.role == "card":
        pygame.draw.rect(screen, BORDER, rectangle, width=2, border_radius=12)
    center = (
        button.rectangle.x + button.rectangle.width // 2,
        button.rectangle.y + button.rectangle.height // 2,
    )
    _draw_text(
        screen,
        font,
        _ellipsize(font, button.label, max(1, button.rectangle.width - 20)),
        center,
        text_color,
    )


def _draw_text(
    screen: Any,
    font: Any,
    text: str,
    center: tuple[int, int],
    color: tuple[int, int, int],
) -> None:
    rendered = font.render(text, True, color)
    screen.blit(rendered, rendered.get_rect(center=center))
