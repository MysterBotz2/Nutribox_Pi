from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from nutribox_pi.adapters.mock_hardware import (
    SimulatedTemperatureSensor,
    SimulatedWeightSensor,
)
from nutribox_pi.adapters.simulated_camera import SimulatedCamera
from nutribox_pi.controller import NutriBoxController
from nutribox_pi.device_ui import (
    MealCaptureWorkflow,
    UIAction,
    UIScreen,
    action_at,
    buttons_for,
)
from nutribox_pi.pairing import PairingState
from nutribox_pi.ui_preferences import Language, Theme, UIPreferenceStore
from nutribox_pi.ui_shell import StartupShell, text


class _Pairing:
    def __init__(self, paired: bool = False) -> None:
        self.state = PairingState.PAIRED if paired else PairingState.UNPAIRED
        self.device = SimpleNamespace(owner_first_name="Ana") if paired else None
        self.error_message = None
        self.greeting = "Hello Ana" if paired else None
        self.code = None
        self.unpaired = False

    def unpair(self) -> None:
        self.unpaired = True
        self.state = PairingState.UNPAIRED
        self.device = None

    def cancel(self) -> None:
        self.state = PairingState.UNPAIRED
        self.device = None

    def start(self) -> bool:
        self.state = PairingState.REQUESTING
        return True

    def tick(self) -> None:
        return None

    def close(self) -> None:
        return None

    def get_verified_device_token(self) -> str | None:
        return "token" if self.state is PairingState.PAIRED else None

    def confirm_revocation(self) -> None:
        self.state = PairingState.UNPAIRED
        self.device = None

    def remaining_seconds(self) -> int:
        return 30


class _Backend:
    pass


def _workflow(tmp_path: Path, paired: bool = False) -> MealCaptureWorkflow:
    shell = StartupShell(UIPreferenceStore(tmp_path))
    controller = NutriBoxController(
        _Backend(), SimulatedWeightSensor(), SimulatedTemperatureSensor()
    )
    return MealCaptureWorkflow(
        SimulatedCamera(), controller, pairing=_Pairing(paired), startup_shell=shell
    )


def test_home_navigation_to_placeholder_pages(tmp_path: Path) -> None:
    workflow = _workflow(tmp_path)
    buttons = buttons_for(
        UIScreen.HOME, workflow.pairing.state if workflow.pairing else None
    )
    actions = {button.action for button in buttons}
    assert UIAction.ANALYZE in actions
    assert UIAction.PORTION_ANALYSIS in actions
    assert UIAction.PROFILE_SETTINGS in actions
    assert UIAction.PAIR_DEVICE in actions
    assert UIAction.EXIT in actions


def test_portion_analysis_back_and_home_clear_state(tmp_path: Path) -> None:
    workflow = _workflow(tmp_path)
    workflow.open_portion_analysis()
    assert workflow.screen is UIScreen.PORTION_ANALYSIS
    workflow.home()
    assert workflow.screen is UIScreen.HOME


def test_guest_portion_control_remains_safely_disabled(tmp_path: Path) -> None:
    workflow = _workflow(tmp_path)
    workflow.open_portion_analysis()
    left_over_button = next(
        button
        for button in buttons_for(UIScreen.PORTION_ANALYSIS)
        if button.action is UIAction.ANALYZE_LEFTOVERS
    )
    assert left_over_button.enabled is False
    center = (left_over_button.rectangle.center_x, left_over_button.rectangle.center_y)
    assert action_at(UIScreen.PORTION_ANALYSIS, *center) is None


def test_portion_copy_and_language_support() -> None:
    assert text(Language.ENGLISH, "portion_analysis") == "Portion Analysis"
    assert text(Language.TAGALOG, "portion_analysis") == "Pagsusuri ng Porsyon"


def test_portion_buttons_fit_800_by_480() -> None:
    for screen in (UIScreen.PORTION_ANALYSIS, UIScreen.HOME):
        for button in buttons_for(screen):
            rectangle = button.rectangle
            assert rectangle.x >= 0 and rectangle.y >= 0
            assert rectangle.x + rectangle.width <= 800
            assert rectangle.y + rectangle.height <= 480


def test_portion_theme_uses_existing_ui_system() -> None:
    workflow = _workflow(Path("/tmp"))
    workflow.startup_shell.preferences.theme = Theme.DARK
    assert workflow.theme is Theme.DARK
    assert text(Language.ENGLISH, "portion_analysis")
