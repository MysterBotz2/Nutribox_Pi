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
from nutribox_pi.models import AnalysisStatus, CalculatedResponse
from nutribox_pi.ports import PreviewCamera

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


def run_device_ui(
    camera: PreviewCamera | None = None,
    controller: NutriBoxController | None = None,
    *,
    simulated_weight: bool = False,
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
            camera or camera_from_env(), controller, store, simulated_weight
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


def _run_loop(
    pygame: Any,
    screen: Any,
    fonts: _Fonts,
    workflow: MealCaptureWorkflow,
) -> UIResult:
    pressed: UIAction | None = None
    next_preview_at = 0.0
    preview_cache = _PreviewSurfaceCache()
    image_cache = _UiImageCache()
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
                    image_cache,
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
                image_cache,
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
    image_cache: _UiImageCache | None = None,
) -> UIResult | None:
    if action is None:
        return None

    if action is UIAction.EXIT:
        if image_cache is not None:
            image_cache.clear()
        return UIResult(True, UI_CLOSED)
    if action is UIAction.ANALYZE:
        workflow.analyze()
    elif action is UIAction.BACK:
        workflow.back()
    elif action is UIAction.CAPTURE:
        if image_cache is not None:
            image_cache.clear()
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
        workflow.retry()
    elif action is UIAction.HOME:
        if image_cache is not None:
            image_cache.clear()
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
    image_cache: _UiImageCache | None = None,
) -> None:
    _draw_grid(pygame, screen)
    cache = image_cache or _UiImageCache()
    if workflow.screen is UIScreen.HOME:
        _render_home(pygame, screen, fonts)
    elif workflow.screen in {UIScreen.CAPTURE, UIScreen.CAPTURING}:
        _render_capture(pygame, screen, fonts, workflow.screen, preview)
    elif workflow.screen is UIScreen.REVIEW:
        _render_review(pygame, screen, fonts, workflow, cache)
    elif workflow.screen is UIScreen.ANALYZING:
        _render_analyzing(pygame, screen, fonts, workflow.simulated_weight)
    elif workflow.screen in RESULT_SCREENS:
        _render_result(pygame, screen, fonts, workflow, cache.thumbnail)
    elif workflow.screen is UIScreen.RECOGNIZED_FOODS:
        _render_recognized_foods(pygame, screen, fonts, workflow, cache.thumbnail)
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
    _draw_card(pygame, screen, (24, 24, 456, 360))
    image_size = tuple(image.get_size())
    left = 27 + (450 - image_size[0]) // 2
    top = 54 + (300 - image_size[1]) // 2
    screen.blit(image, (left, top))
    _draw_corner_marks(pygame, screen, (left, top, image_size[0], image_size[1]))
    _draw_wordmark(screen, fonts, (625, 88))
    _draw_text(
        screen,
        fonts.small,
        "Know your meal, eat mindfully.",
        (625, 128),
        SECONDARY_TEXT,
    )
    _draw_text(
        screen, fonts.small, "Ready for a closer look?", (625, 214), SECONDARY_TEXT
    )


def _render_analyzing(
    pygame: Any, screen: Any, fonts: _Fonts, simulated_weight: bool
) -> None:
    _draw_magnifier_illustration(pygame, screen, (400, 160))
    _draw_text(
        screen,
        fonts.subheading,
        "Analyzing nutritional data…",
        (400, 300),
        NUTRIBOX_BLUE,
    )
    if simulated_weight:
        _draw_text(
            screen,
            fonts.small,
            "Development mode: simulated weight",
            (400, 335),
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
    _draw_thumbnail(pygame, screen, thumbnail, (620, 25))
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
    _draw_thumbnail(pygame, screen, thumbnail, (620, 25))
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
    _draw_thumbnail(pygame, screen, thumbnail, (620, 24))
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
    for x in range(0, DISPLAY_SIZE[0] + 1, 20):
        pygame.draw.line(screen, GRID_BLUE, (x, 0), (x, DISPLAY_SIZE[1]))
    for y in range(0, DISPLAY_SIZE[1] + 1, 20):
        pygame.draw.line(screen, GRID_BLUE, (0, y), (DISPLAY_SIZE[0], y))


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


def _render_error(pygame: Any, screen: Any, fonts: _Fonts, message: str | None) -> None:
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
