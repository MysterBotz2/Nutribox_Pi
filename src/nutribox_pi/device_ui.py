"""Hardware-independent PI-1D local meal-capture workflow."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from nutribox_pi.ports import Camera
from nutribox_pi.touchscreen import TouchRect

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
CLEANUP_ERROR = "Temporary image cleanup failed."
DISPLAY_ERROR = "The Nutri-Box display is unavailable."
UI_CLOSED = "Nutri-Box UI closed."


class UIScreen(StrEnum):
    HOME = "home"
    CAPTURE = "capture"
    CAPTURING = "capturing"
    REVIEW = "review"
    ERROR = "error"


class UIAction(StrEnum):
    ANALYZE = "analyze"
    CAPTURE = "capture"
    BACK = "back"
    RETAKE = "retake"
    DONE = "done"
    RETRY = "retry"
    HOME = "home"
    EXIT = "exit"


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


EXIT_BUTTON = ButtonLayout(
    UIAction.EXIT, "Exit", TouchRect(660, 20, 110, 58), "danger"
)


def buttons_for(screen: UIScreen) -> tuple[ButtonLayout, ...]:
    if screen is UIScreen.HOME:
        return (
            ButtonLayout(
                UIAction.ANALYZE,
                "Analyze Meal",
                TouchRect(180, 300, 440, 88),
            ),
            EXIT_BUTTON,
        )
    if screen is UIScreen.CAPTURE:
        return (
            ButtonLayout(UIAction.BACK, "Back", TouchRect(30, 20, 110, 58), "card"),
            ButtonLayout(
                UIAction.CAPTURE, "Capture", TouchRect(240, 318, 320, 88)
            ),
            EXIT_BUTTON,
        )
    if screen is UIScreen.CAPTURING:
        return (
            ButtonLayout(
                UIAction.CAPTURE,
                "Capturing...",
                TouchRect(240, 318, 320, 88),
                enabled=False,
            ),
            EXIT_BUTTON,
        )
    if screen is UIScreen.REVIEW:
        return (
            ButtonLayout(
                UIAction.RETAKE, "Retake", TouchRect(70, 394, 300, 66), "card"
            ),
            ButtonLayout(UIAction.DONE, "Done", TouchRect(430, 394, 300, 66)),
            EXIT_BUTTON,
        )
    return (
        ButtonLayout(UIAction.RETRY, "Retry", TouchRect(90, 330, 280, 76)),
        ButtonLayout(UIAction.HOME, "Home", TouchRect(430, 330, 280, 76), "card"),
        EXIT_BUTTON,
    )


def action_at(screen: UIScreen, x: float, y: float) -> UIAction | None:
    for button in buttons_for(screen):
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


class MealCaptureWorkflow:
    def __init__(
        self, camera: Camera, store: TemporaryCaptureStore | None = None
    ) -> None:
        self._camera = camera
        self._store = store or TemporaryCaptureStore()
        self.screen = UIScreen.HOME
        self.error_message: str | None = None

    @property
    def review_image(self) -> Path | None:
        return self._store.image_path if self.screen is UIScreen.REVIEW else None

    def analyze(self) -> None:
        self.error_message = None
        self.screen = UIScreen.CAPTURE

    def back(self) -> None:
        self.error_message = None
        self.screen = UIScreen.HOME

    def begin_capture(self) -> None:
        self.error_message = None
        self.screen = UIScreen.CAPTURING

    def perform_capture(self) -> None:
        if self.screen is not UIScreen.CAPTURING:
            return
        try:
            destination = self._store.prepare()
            result = self._camera.capture(destination, overwrite=False)
        except Exception:
            self._fail_after_cleanup(CAMERA_ERROR)
            return
        if (
            result.ok
            and result.published
            and result.output_path == destination
            and destination.is_file()
        ):
            self.screen = UIScreen.REVIEW
            return
        self._fail_after_cleanup(CAMERA_ERROR)

    def retake(self) -> None:
        if self._cleanup_or_error():
            self.screen = UIScreen.CAPTURE
            self.error_message = None

    def done(self) -> None:
        if self._cleanup_or_error():
            self.screen = UIScreen.HOME
            self.error_message = None

    def retry(self) -> None:
        if self._cleanup_or_error():
            self.screen = UIScreen.CAPTURE
            self.error_message = None

    def home(self) -> None:
        if self._cleanup_or_error():
            self.screen = UIScreen.HOME
            self.error_message = None

    def close(self) -> UIResult:
        if not self._store.cleanup():
            self.screen = UIScreen.ERROR
            self.error_message = CLEANUP_ERROR
            return UIResult(False, CLEANUP_ERROR)
        return UIResult(True, UI_CLOSED)

    def _fail_after_cleanup(self, message: str) -> None:
        if not self._store.cleanup():
            message = CLEANUP_ERROR
        self.screen = UIScreen.ERROR
        self.error_message = message

    def _cleanup_or_error(self) -> bool:
        if self._store.cleanup():
            return True
        self.screen = UIScreen.ERROR
        self.error_message = CLEANUP_ERROR
        return False
