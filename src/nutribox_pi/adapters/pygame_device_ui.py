"""Lazy pygame renderer for the PI-1D/PI-2A meal-analysis UI."""

from __future__ import annotations

import importlib
import time
from contextlib import suppress
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
    PRIMARY,
    PRIMARY_MUTED,
    PRIMARY_TEXT,
    RESULT_SCREENS,
    SECONDARY_TEXT,
    UI_CLOSED,
    ButtonLayout,
    MealCaptureWorkflow,
    TemporaryCaptureStore,
    UIAction,
    UIResult,
    UIScreen,
    action_at,
    buttons_for,
    scaled_image_size,
)
from nutribox_pi.ports import FoodRecognizer, PreviewCamera

PRESSED_PRIMARY = (48, 143, 72)
PRESSED_CARD = (222, 222, 227)
WHITE = (255, 255, 255)
REVIEW_BOUNDS = (620, 300)
PREVIEW_BOUNDS = (420, 236)
PREVIEW_INTERVAL_SECONDS = 1 / 15


def run_device_ui(
    camera: PreviewCamera | None = None,
    controller: NutriBoxController | None = None,
    recognizer: FoodRecognizer | None = None,
    *,
    pygame_module: Any | None = None,
    store: TemporaryCaptureStore | None = None,
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
        screen = pygame.display.set_mode(DISPLAY_SIZE, pygame.FULLSCREEN)
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
            camera or camera_from_env(), controller, store, recognizer
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
class _Fonts:
    def __init__(
        self, *, heading: Any, subheading: Any, body: Any, small: Any, button: Any
    ) -> None:
        self.heading = heading
        self.subheading = subheading
        self.body = body
        self.small = small
        self.button = button


def _run_loop(
    pygame: Any,
    screen: Any,
    fonts: _Fonts,
    workflow: MealCaptureWorkflow,
) -> UIResult:
    pressed: UIAction | None = None
    next_preview_at = 0.0
    preview_cache = _PreviewSurfaceCache()
    while True:
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
            pygame, screen, fonts, workflow, pressed, preview_cache.surface
        )
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return UIResult(True, UI_CLOSED)
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return UIResult(True, UI_CLOSED)
            point = _pointer_point(pygame, event, down=True)
            if point is not None:
                pressed = action_at(workflow.screen, *point)
                _render(
                    pygame,
                    screen,
                    fonts,
                    workflow,
                    pressed,
                    preview_cache.surface,
                )
                continue
            point = _pointer_point(pygame, event, down=False)
            if point is None:
                continue
            action = action_at(workflow.screen, *point)
            if pressed is not None and pressed is not action:
                pressed = None
                continue
            pressed = None
            outcome = _apply_action(
                pygame,
                screen,
                fonts,
                workflow,
                action,
                preview_cache.surface,
            )
            if outcome is not None:
                return outcome
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
) -> UIResult | None:
    if action is None:
        return None

    if action is UIAction.EXIT:
        return UIResult(True, UI_CLOSED)
    if action is UIAction.ANALYZE:
        workflow.analyze()
    elif action is UIAction.BACK:
        workflow.back()
    elif action is UIAction.CAPTURE:
        workflow.begin_capture()
        _render(pygame, screen, fonts, workflow, None, preview_surface)
        pygame.event.pump()
        pygame.time.wait(80)
        workflow.perform_capture()
    elif action is UIAction.ANALYZE_MEAL:
        workflow.begin_analysis()
        _render(pygame, screen, fonts, workflow, None)
        pygame.event.pump()
        pygame.time.wait(80)
        workflow.perform_analysis()
    elif action is UIAction.RETAKE:
        workflow.retake()
    elif action is UIAction.RETRY:
        workflow.retry()
    elif action is UIAction.HOME:
        workflow.home()
    return None


def _pointer_point(
    pygame: Any, event: Any, *, down: bool
) -> tuple[float, float] | None:
    mouse_type = pygame.MOUSEBUTTONDOWN if down else pygame.MOUSEBUTTONUP
    finger_type = pygame.FINGERDOWN if down else pygame.FINGERUP
    if event.type == mouse_type and event.button == 1:
        return float(event.pos[0]), float(event.pos[1])
    if event.type == finger_type:
        return event.x * DISPLAY_SIZE[0], event.y * DISPLAY_SIZE[1]
    return None


def _render(
    pygame: Any,
    screen: Any,
    fonts: _Fonts,
    workflow: MealCaptureWorkflow,
    pressed: UIAction | None,
    preview: Any | None = None,
) -> None:
    screen.fill(BACKGROUND)
    if workflow.screen is UIScreen.HOME:
        _render_home(pygame, screen, fonts)
    elif workflow.screen in {UIScreen.CAPTURE, UIScreen.CAPTURING}:
        _render_capture(pygame, screen, fonts, workflow.screen, preview)
    elif workflow.screen is UIScreen.REVIEW:
        _render_review(pygame, screen, fonts, workflow)
    elif workflow.screen is UIScreen.ANALYZING:
        _render_analyzing(pygame, screen, fonts)
    elif workflow.screen in RESULT_SCREENS:
        _render_result(pygame, screen, fonts, workflow)
    elif workflow.screen is UIScreen.RECOGNIZED_FOODS:
        _render_recognized_foods(pygame, screen, fonts, workflow)
    else:
        _render_error(pygame, screen, fonts, workflow.error_message)
    for button in buttons_for(workflow.screen):
        _draw_button(pygame, screen, fonts.button, button, pressed is button.action)
    pygame.display.flip()


def _render_home(pygame: Any, screen: Any, fonts: _Fonts) -> None:
    _draw_card(pygame, screen, (90, 105, 620, 170))
    _draw_text(screen, fonts.heading, "Nutri-Box", (400, 150), PRIMARY_TEXT)
    _draw_text(
        screen,
        fonts.body,
        "Make every meal a healthier choice.",
        (400, 213),
        SECONDARY_TEXT,
    )


def _render_capture(
    pygame: Any,
    screen: Any,
    fonts: _Fonts,
    state: UIScreen,
    preview: Any | None,
) -> None:
    _draw_text(screen, fonts.subheading, "Capture your meal", (400, 68), PRIMARY_TEXT)
    _draw_card(pygame, screen, (180, 88, 440, 256))
    message = (
        "Capturing your meal..."
        if state is UIScreen.CAPTURING
        else "Place the full meal inside the camera view, then tap Capture."
    )
    _draw_text(screen, fonts.body, message, (400, 360), SECONDARY_TEXT)
    if preview is not None:
        target_size = tuple(preview.get_size())
        left = (DISPLAY_SIZE[0] - target_size[0]) // 2
        top = 98 + (PREVIEW_BOUNDS[1] - target_size[1]) // 2
        screen.blit(preview, (left, top))
    else:
        _draw_text(
            screen,
            fonts.body,
            "Starting camera preview...",
            (400, 215),
            SECONDARY_TEXT,
        )


def _render_review(
    pygame: Any, screen: Any, fonts: _Fonts, workflow: MealCaptureWorkflow
) -> None:
    _draw_text(screen, fonts.subheading, "Review meal photo", (400, 35), PRIMARY_TEXT)
    image_path = workflow.review_image
    if image_path is None:
        raise RuntimeError
    image = pygame.image.load(str(image_path))
    source_size = tuple(image.get_size())
    if source_size != (1920, 1080):
        raise RuntimeError
    target_size = scaled_image_size(source_size, REVIEW_BOUNDS)
    scaled = pygame.transform.smoothscale(image, target_size)
    left = (DISPLAY_SIZE[0] - target_size[0]) // 2
    top = 72 + (REVIEW_BOUNDS[1] - target_size[1]) // 2
    _draw_card(pygame, screen, (80, 62, 640, 320))
    screen.blit(scaled, (left, top))


def _render_analyzing(pygame: Any, screen: Any, fonts: _Fonts) -> None:
    _draw_text(screen, fonts.heading, "Analyzing meal", (400, 120), PRIMARY_TEXT)
    _draw_card(pygame, screen, (120, 165, 560, 110))
    _draw_text(
        screen,
        fonts.body,
        "Sending the meal image and simulated weight...",
        (400, 220),
        SECONDARY_TEXT,
    )


def _render_result(
    pygame: Any, screen: Any, fonts: _Fonts, workflow: MealCaptureWorkflow
) -> None:
    _draw_text(screen, fonts.heading, "Meal analysis", (400, 115), PRIMARY_TEXT)
    _draw_card(pygame, screen, (100, 165, 600, 110))
    _draw_text(
        screen,
        fonts.body,
        workflow.result_message or ANALYSIS_ERROR,
        (400, 220),
        SECONDARY_TEXT,
    )


def _render_recognized_foods(
    pygame: Any, screen: Any, fonts: _Fonts, workflow: MealCaptureWorkflow
) -> None:
    _draw_text(screen, fonts.subheading, "Recognized Foods", (400, 90), PRIMARY_TEXT)
    _draw_card(pygame, screen, (90, 120, 620, 245))
    source = (
        "Simulated recognition"
        if workflow.recognition_source is not None
        and workflow.recognition_source.value == "simulated"
        else "AI recognition"
    )
    _draw_text(screen, fonts.body, source, (400, 145), SECONDARY_TEXT)
    if not workflow.recognized_foods:
        _draw_text(screen, fonts.body, "No food recognized", (400, 240), PRIMARY_TEXT)
        return
    for index, food in enumerate(workflow.recognized_foods):
        _draw_text(
            screen,
            fonts.small,
            _ellipsize(fonts.small, food.name, 560),
            (400, 175 + index * 18),
            PRIMARY_TEXT,
        )


def _ellipsize(font: Any, text: str, maximum_width: int) -> str:
    if font.size(text)[0] <= maximum_width:
        return text
    shortened = text
    while shortened and font.size(shortened + "...")[0] > maximum_width:
        shortened = shortened[:-1]
    return shortened + "..."


def _render_error(
    pygame: Any, screen: Any, fonts: _Fonts, message: str | None
) -> None:
    _draw_text(screen, fonts.heading, "Something went wrong", (400, 125), DANGER)
    _draw_card(pygame, screen, (100, 175, 600, 110))
    _draw_text(
        screen,
        fonts.body,
        message or "Unable to continue safely.",
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
    _draw_text(screen, font, button.label, center, text_color)


def _draw_text(
    screen: Any,
    font: Any,
    text: str,
    center: tuple[int, int],
    color: tuple[int, int, int],
) -> None:
    rendered = font.render(text, True, color)
    screen.blit(rendered, rendered.get_rect(center=center))
