"""Hardware-independent PI-1D/PI-2A meal-capture and analysis workflow."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from nutribox_pi.controller import NutriBoxController
from nutribox_pi.models import (
    AnalysisStatus,
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
from nutribox_pi.ui_preferences import Language
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
    NUTRITION_REFERENCE_NOT_FOUND = "nutrition_reference_not_found"
    RECOGNIZED_FOODS = "recognized_foods"
    ERROR = "error"
    PAIR_REQUESTING = "pair_requesting"
    PAIR_WAITING = "pair_waiting"
    PAIR_PAIRED = "pair_paired"
    PAIR_EXPIRED = "pair_expired"
    PAIR_ERROR = "pair_error"


class UIAction(StrEnum):
    SELECT_ENGLISH = "select_english"
    SELECT_TAGALOG = "select_tagalog"
    TOGGLE_INTRO = "toggle_intro"
    HELP = "help"
    CONTINUE = "continue"
    ANALYZE = "analyze"
    ANALYZE_MEAL = "analyze_meal"
    SHOW_RECOGNIZED_FOODS = "show_recognized_foods"
    ANALYZE_AGAIN = "analyze_again"
    CAPTURE = "capture"
    BACK = "back"
    RETAKE = "retake"
    RETRY = "retry"
    HOME = "home"
    EXIT = "exit"
    PAIR_DEVICE = "pair_device"
    CANCEL_PAIRING = "cancel_pairing"


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


def buttons_for(
    screen: UIScreen, pairing_state: PairingState | None = None
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
        return (
            ButtonLayout(
                UIAction.RETAKE, "Retake", TouchRect(70, 330, 300, 76), "card"
            ),
            ButtonLayout(UIAction.HOME, "Home", TouchRect(430, 330, 300, 76)),
            ButtonLayout(
                UIAction.SHOW_RECOGNIZED_FOODS,
                "See recognized foods",
                TouchRect(430, 240, 300, 64),
            ),
            EXIT_BUTTON,
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
    screen: UIScreen, x: float, y: float, pairing_state: PairingState | None = None
) -> UIAction | None:
    for button in buttons_for(screen, pairing_state):
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
    AnalysisStatus.REQUIRES_FOOD_SELECTION: UIScreen.REQUIRES_FOOD_SELECTION,
    AnalysisStatus.NUTRITION_REFERENCE_NOT_FOUND: (
        UIScreen.NUTRITION_REFERENCE_NOT_FOUND
    ),
    AnalysisStatus.REQUIRES_INGREDIENT_VERIFICATION: (
        UIScreen.NUTRITION_REFERENCE_NOT_FOUND
    ),
    AnalysisStatus.REQUIRES_RECIPE_CONFIRMATION: (
        UIScreen.NUTRITION_REFERENCE_NOT_FOUND
    ),
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
    ) -> None:
        self._camera = camera
        self._preview: PreviewSession | None = None
        self._controller = controller
        self._store = store or TemporaryCaptureStore()
        self.simulated_weight = simulated_weight
        self.simulated_camera = bool(getattr(camera, "is_simulated", False))
        self.pairing = pairing
        self.startup_shell = startup_shell
        self.screen = UIScreen.LOADING if startup_shell is not None else UIScreen.HOME
        self._startup_language_selection = startup_shell is not None
        self.error_message: str | None = None
        self.result_message: str | None = None
        self.recognized_foods: tuple[RecognizedFood, ...] = ()
        self.recognition_source: RecognitionSource | None = None
        self.analysis_response: MealAnalysisResponse | None = None
        self.captured_weight_grams: float | None = None
        self.analysis_retry_available = False

    @property
    def language(self) -> Language:
        return (
            self.startup_shell.preferences.language
            if self.startup_shell is not None
            else Language.ENGLISH
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
        self.screen = (
            UIScreen.INSTRUCTION
            if show_intro
            else UIScreen.HOME
        )

    def toggle_intro(self) -> None:
        if self.startup_shell is not None:
            self.startup_shell.toggle_intro()

    def continue_from_instruction(self) -> None:
        self.screen = UIScreen.HOME

    def start_pairing(self) -> None:
        if self.pairing is not None and self.pairing.start():
            self.screen = UIScreen.PAIR_REQUESTING

    def tick_pairing(self) -> None:
        if self.pairing is None:
            return
        self.pairing.tick()
        if self.pairing.error_message == REVOKED_MESSAGE and self.screen in {
            UIScreen.CAPTURE,
            UIScreen.CAPTURING,
            UIScreen.REVIEW,
        }:
            self._close_preview()
            self._store.cleanup()
            self._clear_analysis_state()
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

    def analyze(self) -> None:
        self.error_message = None
        self.result_message = None
        self.recognized_foods = ()
        self.recognition_source = None
        self.analysis_response = None
        self.captured_weight_grams = None
        self.analysis_retry_available = False
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
            self._store.cleanup()
            self._clear_analysis_state()
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
        self.screen = STATUS_SCREENS[result.status]
        self.result_message = RESULT_MESSAGES[result.status]
        if isinstance(result, MealAnalysisResponse):
            self.analysis_response = result
            self.recognized_foods = result.recognized_foods
            self.recognition_source = result.recognition_source
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

    def retry(self) -> None:
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

    def _clear_analysis_state(self) -> None:
        self.recognized_foods = ()
        self.recognition_source = None
        self.analysis_response = None
        self.captured_weight_grams = None
        self.analysis_retry_available = False

    def _cleanup_or_error(self) -> bool:
        if self._store.cleanup():
            return True
        self.screen = UIScreen.ERROR
        self.error_message = CLEANUP_ERROR
        return False
