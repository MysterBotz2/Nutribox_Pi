"""Guest versus paired Save Meal eligibility stays local to one analysis."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nutribox_pi.adapters.mock_hardware import (
    SimulatedTemperatureSensor,
    SimulatedWeightSensor,
)
from nutribox_pi.adapters.simulated_camera import SimulatedCamera
from nutribox_pi.continuation import SaveState
from nutribox_pi.controller import NutriBoxController
from nutribox_pi.device_ui import (
    MealCaptureWorkflow,
    TemporaryCaptureStore,
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
from nutribox_pi.pairing import PairingState


class _Pairing:
    def __init__(self, token: str | None) -> None:
        self.token = token
        self.state = PairingState.PAIRED if token else PairingState.UNPAIRED
        self.error_message: str | None = None

    def get_verified_device_token(self) -> str | None:
        return self.token

    def tick(self) -> None:
        pass

    def confirm_revocation(self) -> None:
        self.token = None
        self.state = PairingState.UNPAIRED

    def close(self) -> None:
        self.token = None


class _Backend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def analyze_meal(self, *_: object, **kwargs: Any) -> CalculatedResponse:
        self.calls.append(("analyze", kwargs))
        return _calculated()

    def save_meal(self, _: int, **kwargs: Any) -> object:
        self.calls.append(("save", kwargs))
        return object()


def _calculated() -> CalculatedResponse:
    return CalculatedResponse(
        AnalysisStatus.CALCULATED,
        (RecognizedFood("rice"),),
        RecognitionSource.SIMULATED,
        analysis_session_id=41,
        nutrition=NutritionValues("100", "2", "20", "1", "3"),
        weight_grams="250",
    )


def _store(tmp_path: Path) -> TemporaryCaptureStore:
    directory = tmp_path / "private-capture"

    def create_directory(**_: object) -> str:
        directory.mkdir(mode=0o700)
        return str(directory)

    return TemporaryCaptureStore(directory_factory=create_directory)


def _workflow(
    tmp_path: Path, token: str | None
) -> tuple[MealCaptureWorkflow, _Backend, _Pairing]:
    backend = _Backend()
    pairing = _Pairing(token)
    controller = NutriBoxController(
        backend,
        SimulatedWeightSensor(250),
        SimulatedTemperatureSensor(),
        pairing,
    )
    return (
        MealCaptureWorkflow(
            SimulatedCamera(), controller, _store(tmp_path), pairing=pairing
        ),
        backend,
        pairing,
    )


def _analyze_to_calculated(workflow: MealCaptureWorkflow) -> None:
    workflow.analyze()
    workflow.begin_capture()
    workflow.perform_capture()
    workflow.begin_analysis()
    workflow.perform_analysis()
    assert workflow.screen is UIScreen.CALCULATED


def _save_button(workflow: MealCaptureWorkflow):
    return next(
        button
        for button in buttons_for(
            UIScreen.CALCULATED, save_enabled=workflow.save_enabled
        )
        if button.action is UIAction.SAVE_MEAL
    )


def test_guest_calculated_analysis_has_no_device_header_or_save_action(
    tmp_path: Path,
) -> None:
    workflow, backend, _ = _workflow(tmp_path, None)

    _analyze_to_calculated(workflow)

    assert backend.calls[0][0] == "analyze"
    assert "device_token" not in backend.calls[0][1]
    assert all(
        button.action is not UIAction.SAVE_MEAL
        for button in buttons_for(
            UIScreen.CALCULATED, save_enabled=workflow.save_enabled
        )
    )
    assert workflow.continuation.save_state is SaveState.UNAVAILABLE


def test_pairing_after_guest_calculation_cannot_retroactively_enable_save(
    tmp_path: Path,
) -> None:
    workflow, _, pairing = _workflow(tmp_path, None)
    _analyze_to_calculated(workflow)

    pairing.token = "verified-device-token"
    pairing.state = PairingState.PAIRED

    assert workflow.save_enabled is False
    assert all(
        button.action is not UIAction.SAVE_MEAL
        for button in buttons_for(
            UIScreen.CALCULATED, save_enabled=workflow.save_enabled
        )
    )
    assert workflow.save_notice == "Analyze a new meal while paired to save it."
    workflow.save_meal()
    assert workflow.continuation.save_state is SaveState.UNAVAILABLE


def test_fresh_paired_analysis_enables_one_explicit_token_only_save(
    tmp_path: Path,
) -> None:
    workflow, backend, _ = _workflow(tmp_path, "verified-device-token")
    _analyze_to_calculated(workflow)

    assert backend.calls[0][0] == "analyze"
    assert backend.calls[0][1]["device_token"] == "verified-device-token"
    assert _save_button(workflow).enabled is True
    workflow.save_meal()
    workflow.tick_continuation()

    assert backend.calls[-1] == ("save", {"device_token": "verified-device-token"})
    assert workflow.continuation.save_state is SaveState.SAVED
    assert workflow.save_enabled is False
    workflow.save_meal()
    assert len(backend.calls) == 2


def test_unverification_fences_old_paired_session_without_losing_calculated_view(
    tmp_path: Path,
) -> None:
    workflow, _, pairing = _workflow(tmp_path, "verified-device-token")
    _analyze_to_calculated(workflow)
    assert workflow.save_enabled

    pairing.token = None
    pairing.state = PairingState.UNPAIRED
    workflow.tick_pairing()
    pairing.token = "new-verified-device-token"
    pairing.state = PairingState.PAIRED

    assert workflow.screen is UIScreen.CALCULATED
    assert workflow.save_enabled is False
    assert workflow.continuation.save_state is SaveState.UNAVAILABLE


def test_navigation_and_cancellation_clear_save_eligibility(tmp_path: Path) -> None:
    workflow, _, _ = _workflow(tmp_path, "verified-device-token")
    _analyze_to_calculated(workflow)
    assert workflow.save_enabled

    workflow.home()
    assert workflow.continuation.save_state is SaveState.UNAVAILABLE
    assert workflow.save_enabled is False

    _analyze_to_calculated(workflow)
    workflow.retake()
    assert workflow.continuation.save_state is SaveState.UNAVAILABLE

    workflow.continuation.cancel()
    workflow.tick_continuation()
    assert workflow.continuation.save_state is SaveState.UNAVAILABLE
    workflow.close()
    assert workflow.continuation.save_state is SaveState.UNAVAILABLE


def test_save_action_is_absent_for_guest_result(
    tmp_path: Path,
) -> None:
    workflow, _, _ = _workflow(tmp_path, None)
    _analyze_to_calculated(workflow)
    assert all(
        button.action is not UIAction.SAVE_MEAL
        for button in buttons_for(
            UIScreen.CALCULATED, save_enabled=workflow.save_enabled
        )
    )
