from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from nutribox_pi.adapters.mock_hardware import (
    SimulatedTemperatureSensor,
    SimulatedWeightSensor,
)
from nutribox_pi.adapters.simulated_camera import SimulatedCamera
from nutribox_pi.continuation import SaveState
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


def test_guest_portion_analysis_is_disabled_on_home_and_paired_is_enabled() -> None:
    guest_button = next(
        button
        for button in buttons_for(UIScreen.HOME, PairingState.UNPAIRED)
        if button.action is UIAction.PORTION_ANALYSIS
    )
    paired_button = next(
        button
        for button in buttons_for(UIScreen.HOME, PairingState.PAIRED)
        if button.action is UIAction.PORTION_ANALYSIS
    )
    assert guest_button.enabled is False
    assert (
        action_at(
            UIScreen.HOME,
            guest_button.rectangle.center_x,
            guest_button.rectangle.center_y,
            PairingState.UNPAIRED,
        )
        is None
    )
    assert paired_button.enabled is True


def test_saved_meal_selection_requires_a_row_before_continue() -> None:
    before = next(
        button
        for button in buttons_for(UIScreen.SAVED_MEAL_SELECTION)
        if button.action is UIAction.LEFTOVER_CONTINUE
    )
    after = next(
        button
        for button in buttons_for(
            UIScreen.SAVED_MEAL_SELECTION, saved_meal_selected=True
        )
        if button.action is UIAction.LEFTOVER_CONTINUE
    )
    assert before.enabled is False
    assert after.enabled is True


def test_saved_meal_pagination_controls_require_an_adjacent_page() -> None:
    disabled = buttons_for(UIScreen.SAVED_MEAL_SELECTION)
    enabled = buttons_for(
        UIScreen.SAVED_MEAL_SELECTION,
        saved_meal_has_previous=True,
        saved_meal_has_next=True,
    )
    for action in (UIAction.SAVED_MEAL_PREVIOUS, UIAction.SAVED_MEAL_NEXT):
        assert (
            next(button for button in disabled if button.action is action).enabled
            is False
        )
        assert (
            next(button for button in enabled if button.action is action).enabled
            is True
        )


def test_home_and_saved_meal_controls_do_not_overlap() -> None:
    for screen, pairing_state, selected in (
        (UIScreen.HOME, PairingState.PAIRED, False),
        (UIScreen.SAVED_MEAL_SELECTION, None, True),
    ):
        buttons = buttons_for(screen, pairing_state, saved_meal_selected=selected)
        for index, first in enumerate(buttons):
            for second in buttons[index + 1 :]:
                assert not (
                    first.rectangle.x < second.rectangle.x + second.rectangle.width
                    and second.rectangle.x < first.rectangle.x + first.rectangle.width
                    and first.rectangle.y < second.rectangle.y + second.rectangle.height
                    and second.rectangle.y < first.rectangle.y + first.rectangle.height
                ), (screen, first.action, second.action)


def test_saved_meal_selection_continues_only_after_selection(tmp_path: Path) -> None:
    workflow = _workflow(tmp_path, paired=True)
    workflow.leftovers.select_saved_meal_id(7)
    workflow.screen = UIScreen.SAVED_MEAL_SELECTION
    workflow.continue_leftover_capture()
    assert workflow.leftover_mode is True
    assert workflow.screen is UIScreen.CAPTURE


def test_saved_shortcut_requires_paired_analysis_and_starts_new_leftover_capture(
    tmp_path: Path,
) -> None:
    workflow = _workflow(tmp_path, paired=True)
    workflow.screen = UIScreen.CALCULATED
    workflow._analysis_started_paired = True
    workflow.continuation._save_state = SaveState.SAVED
    workflow.continuation._saved_meal = SimpleNamespace(id=7)
    assert workflow.leftover_shortcut_enabled is True
    workflow.start_saved_meal_leftover()
    assert workflow.leftover_mode is True
    assert workflow.leftovers.selected_meal_id == 7
    assert workflow.screen is UIScreen.CAPTURE


def test_pairing_after_guest_analysis_does_not_enable_leftover_shortcut(
    tmp_path: Path,
) -> None:
    workflow = _workflow(tmp_path, paired=True)
    workflow.screen = UIScreen.CALCULATED
    workflow.continuation._save_state = SaveState.SAVED
    workflow.continuation._saved_meal = SimpleNamespace(id=7)
    assert workflow.leftover_shortcut_enabled is False


def test_portion_theme_uses_existing_ui_system() -> None:
    workflow = _workflow(Path("/tmp"))
    workflow.startup_shell.preferences.theme = Theme.DARK
    assert workflow.theme is Theme.DARK
    assert text(Language.ENGLISH, "portion_analysis")
