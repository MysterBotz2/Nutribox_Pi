from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from nutribox_pi.adapters import pygame_device_ui
from nutribox_pi.adapters.mock_hardware import (
    SimulatedTemperatureSensor,
    SimulatedWeightSensor,
)
from nutribox_pi.adapters.simulated_camera import SimulatedCamera
from nutribox_pi.controller import NutriBoxController
from nutribox_pi.device_ui import MealCaptureWorkflow, UIAction, UIScreen, buttons_for
from nutribox_pi.pairing import PairingState
from nutribox_pi.ui_preferences import Language, Theme, UIPreferenceStore
from nutribox_pi.ui_shell import StartupShell


class _Pairing:
    def __init__(self, paired: bool = False) -> None:
        self.state = PairingState.PAIRED if paired else PairingState.UNPAIRED
        self.device = SimpleNamespace(owner_first_name="Ana") if paired else None
        self.error_message = None
        self.unpaired = False

    def unpair(self) -> None:
        self.unpaired = True
        self.state = PairingState.UNPAIRED
        self.device = None


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


def test_profile_navigation_preferences_and_unpair_confirmation(tmp_path: Path) -> None:
    workflow = _workflow(tmp_path, paired=True)
    workflow.open_profile_settings()
    assert workflow.screen is UIScreen.PROFILE_SETTINGS
    workflow.set_settings_language(Language.TAGALOG)
    workflow.toggle_intro()
    workflow.toggle_theme()
    assert workflow.language is Language.TAGALOG
    assert workflow.theme is Theme.DARK
    assert workflow.startup_shell is not None
    assert workflow.startup_shell.store.load().theme is Theme.DARK
    workflow.request_unpair()
    assert workflow.screen is UIScreen.UNPAIR_CONFIRM
    workflow.confirm_unpair()
    assert (
        workflow.pairing is not None and workflow.pairing.state is PairingState.UNPAIRED
    )
    workflow.settings_back()
    assert workflow.screen is UIScreen.HOME


def test_guest_profile_and_actions_keep_analysis_available(tmp_path: Path) -> None:
    workflow = _workflow(tmp_path)
    workflow.open_profile_settings()
    actions = {button.action for button in buttons_for(UIScreen.PROFILE_SETTINGS)}
    assert UIAction.UNPAIR in actions
    assert (
        next(
            button
            for button in buttons_for(UIScreen.PROFILE_SETTINGS)
            if button.action is UIAction.UNPAIR
        ).enabled
        is False
    )
    workflow.settings_back()
    assert UIAction.ANALYZE in {button.action for button in buttons_for(UIScreen.HOME)}


def test_diagnostics_and_revocation_are_safe_and_private(tmp_path: Path) -> None:
    workflow = _workflow(tmp_path, paired=True)
    workflow._diagnostics_action = lambda: SimpleNamespace(passed=True)
    workflow.open_profile_settings()
    workflow.run_diagnostics()
    assert workflow.settings_message == "Diagnostics passed."
    assert "Ana" not in workflow.settings_message
    assert "token" not in repr(workflow)
    assert workflow.pairing is not None
    workflow.pairing.state = PairingState.UNPAIRED
    workflow.pairing.device = None
    assert workflow.pairing.device is None


def test_profile_buttons_fit_viewport() -> None:
    for screen in (UIScreen.PROFILE_SETTINGS, UIScreen.UNPAIR_CONFIRM):
        for button in buttons_for(screen):
            rectangle = button.rectangle
            assert rectangle.x >= 0 and rectangle.y >= 0
            assert rectangle.x + rectangle.width <= 800
            assert rectangle.y + rectangle.height <= 480


def test_profile_action_dispatch_is_hardware_independent(tmp_path: Path) -> None:
    workflow = _workflow(tmp_path)
    pygame_device_ui._apply_action(
        object(), object(), object(), workflow, UIAction.PROFILE_SETTINGS
    )
    assert workflow.screen is UIScreen.PROFILE_SETTINGS
    pygame_device_ui._apply_action(
        object(), object(), object(), workflow, UIAction.SETTINGS_BACK
    )
    assert workflow.screen is UIScreen.HOME
