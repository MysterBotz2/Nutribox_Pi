from __future__ import annotations

import os
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from nutribox_pi.adapters import pygame_device_ui
from nutribox_pi.adapters.mock_hardware import (
    SimulatedTemperatureSensor,
    SimulatedWeightSensor,
)
from nutribox_pi.adapters.simulated_camera import SimulatedCamera
from nutribox_pi.adapters.v1_backend import BackendError
from nutribox_pi.controller import NutriBoxController
from nutribox_pi.device_ui import (
    ANALYSIS_ERROR,
    CAMERA_ERROR,
    CLEANUP_ERROR,
    DISPLAY_ERROR,
    RESULT_MESSAGES,
    STATUS_SCREENS,
    MealCaptureWorkflow,
    TemporaryCaptureStore,
    UIAction,
    UIResult,
    UIScreen,
    buttons_for,
    scaled_image_size,
)
from nutribox_pi.models import (
    AnalysisResult,
    AnalysisStatus,
    CameraCode,
    CaptureResult,
    HealthResult,
)


class RecordingBackend:
    def __init__(
        self,
        status: AnalysisStatus = AnalysisStatus.CALCULATED,
        error: BaseException | None = None,
    ) -> None:
        self.status = status
        self.error = error
        self.calls: list[tuple[Path, float]] = []

    def health(self) -> HealthResult:
        raise AssertionError("UI must not call backend health")

    def analyze_meal(self, image_path: Path, weight_grams: float) -> AnalysisResult:
        self.calls.append((image_path, weight_grams))
        if self.error is not None:
            raise self.error
        return AnalysisResult(self.status, {"status": self.status.value})


def _controller(
    backend: RecordingBackend | None = None, weight: float = 250.0
) -> NutriBoxController:
    return NutriBoxController(
        backend or RecordingBackend(),
        SimulatedWeightSensor(weight),
        SimulatedTemperatureSensor(),
    )


def _store(tmp_path: Path) -> TemporaryCaptureStore:
    directory = tmp_path / "private-capture"

    def create_directory(**kwargs: object) -> str:
        directory.mkdir(mode=0o700)
        return str(directory)

    return TemporaryCaptureStore(directory_factory=create_directory)


def _captured_workflow(tmp_path: Path) -> MealCaptureWorkflow:
    workflow = MealCaptureWorkflow(
        SimulatedCamera(), _controller(), _store(tmp_path)
    )
    workflow.analyze()
    workflow.begin_capture()
    workflow.perform_capture()
    return workflow


def test_home_capture_capturing_review_transition(tmp_path: Path) -> None:
    class RecordingCamera(SimulatedCamera):
        calls = 0

        def capture(self, output_path: Path, overwrite: bool = False) -> CaptureResult:
            self.calls += 1
            return super().capture(output_path, overwrite)

    camera = RecordingCamera()
    workflow = MealCaptureWorkflow(camera, _controller(), _store(tmp_path))

    assert workflow.screen is UIScreen.HOME
    workflow.analyze()
    assert workflow.screen is UIScreen.CAPTURE
    workflow.begin_capture()
    assert workflow.screen is UIScreen.CAPTURING
    assert camera.calls == 0
    workflow.perform_capture()

    assert camera.calls == 1
    assert workflow.screen is UIScreen.REVIEW
    assert workflow.review_image is not None
    assert workflow.review_image.is_file()


def test_retake_deletes_image_and_returns_to_capture(tmp_path: Path) -> None:
    workflow = _captured_workflow(tmp_path)
    image = workflow.review_image
    assert image is not None
    directory = image.parent

    workflow.retake()

    assert workflow.screen is UIScreen.CAPTURE
    assert not image.exists()
    assert not directory.exists()


def test_analyze_deletes_image_and_home_returns_home(tmp_path: Path) -> None:
    workflow = _captured_workflow(tmp_path)
    image = workflow.review_image
    assert image is not None
    directory = image.parent

    workflow.begin_analysis()
    workflow.perform_analysis()

    assert workflow.screen is UIScreen.CALCULATED
    assert not image.exists()
    assert not directory.exists()
    workflow.home()
    assert workflow.screen is UIScreen.HOME


def test_back_and_exit_are_clean(tmp_path: Path) -> None:
    workflow = MealCaptureWorkflow(
        SimulatedCamera(), _controller(), _store(tmp_path)
    )
    workflow.analyze()
    workflow.back()

    assert workflow.screen is UIScreen.HOME
    assert workflow.close() == UIResult(True, "Nutri-Box UI closed.")


def test_camera_failure_is_normalized_and_retry_returns_to_capture(
    tmp_path: Path,
) -> None:
    class FailingCamera:
        def capture(
            self, output_path: Path, overwrite: bool = False
        ) -> CaptureResult:
            return CaptureResult(
                False,
                CameraCode.CAPTURE_FAILED,
                "/secret/raw camera exception",
                False,
                None,
                None,
                None,
                None,
                None,
            )

    workflow = MealCaptureWorkflow(
        FailingCamera(), _controller(), _store(tmp_path)
    )
    workflow.analyze()
    workflow.begin_capture()
    workflow.perform_capture()

    assert workflow.screen is UIScreen.ERROR
    assert workflow.error_message == CAMERA_ERROR
    assert "/secret" not in workflow.error_message
    workflow.retry()
    assert workflow.screen is UIScreen.CAPTURE


@pytest.mark.parametrize("status", list(AnalysisStatus))
def test_analysis_status_uses_controller_boundary_weight_and_cleans_image(
    tmp_path: Path, status: AnalysisStatus
) -> None:
    backend = RecordingBackend(status)
    workflow = MealCaptureWorkflow(
        SimulatedCamera(), _controller(backend, weight=321.5), _store(tmp_path)
    )
    workflow.analyze()
    workflow.begin_capture()
    workflow.perform_capture()
    image = workflow.review_image
    assert image is not None
    directory = image.parent

    workflow.begin_analysis()

    assert workflow.screen is UIScreen.ANALYZING
    assert backend.calls == []
    workflow.perform_analysis()

    assert workflow.screen is STATUS_SCREENS[status]
    assert workflow.result_message == RESULT_MESSAGES[status]
    assert backend.calls == [(image, 321.5)]
    assert not image.exists()
    assert not directory.exists()


@pytest.mark.parametrize(
    "failure",
    [
        BackendError("request failed /secret"),
        TimeoutError("timed out /secret"),
        ValueError("invalid response /secret"),
    ],
)
def test_analysis_failures_are_normalized_and_cleaned(
    tmp_path: Path, failure: Exception
) -> None:
    workflow = MealCaptureWorkflow(
        SimulatedCamera(),
        _controller(RecordingBackend(error=failure)),
        _store(tmp_path),
    )
    workflow.analyze()
    workflow.begin_capture()
    workflow.perform_capture()
    image = workflow.review_image
    assert image is not None
    directory = image.parent

    workflow.begin_analysis()
    workflow.perform_analysis()

    assert workflow.screen is UIScreen.ERROR
    assert workflow.error_message == ANALYSIS_ERROR
    assert "/secret" not in workflow.error_message
    assert not image.exists()
    assert not directory.exists()


def test_analysis_cleanup_failure_overrides_success(tmp_path: Path) -> None:
    class FailingAnalysisCleanupStore(TemporaryCaptureStore):
        cleanup_calls = 0

        def cleanup(self) -> bool:
            self.cleanup_calls += 1
            return False

    store = FailingAnalysisCleanupStore()
    image = tmp_path / "meal.jpg"
    image.write_bytes(b"meal")
    store._image = image
    store._directory = tmp_path
    workflow = MealCaptureWorkflow(SimulatedCamera(), _controller(), store)
    workflow.screen = UIScreen.REVIEW

    workflow.begin_analysis()
    workflow.perform_analysis()

    assert workflow.screen is UIScreen.ERROR
    assert workflow.error_message == CLEANUP_ERROR
    assert store.cleanup_calls == 1


def test_analysis_cancellation_cleans_image_and_is_reraised(tmp_path: Path) -> None:
    backend = RecordingBackend(error=KeyboardInterrupt())
    workflow = MealCaptureWorkflow(
        SimulatedCamera(), _controller(backend), _store(tmp_path)
    )
    workflow.analyze()
    workflow.begin_capture()
    workflow.perform_capture()
    image = workflow.review_image
    assert image is not None
    directory = image.parent
    workflow.begin_analysis()

    with pytest.raises(KeyboardInterrupt):
        workflow.perform_analysis()

    assert not image.exists()
    assert not directory.exists()


def test_review_scaling_preserves_1920_by_1080_aspect_ratio() -> None:
    width, height = scaled_image_size((1920, 1080), (620, 300))

    assert (width, height) == (533, 300)
    assert width <= 620 and height <= 300
    assert width / height == pytest.approx(16 / 9, abs=0.002)


def test_analyze_action_renders_visible_state_before_backend_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = RecordingBackend()
    workflow = MealCaptureWorkflow(
        SimulatedCamera(), _controller(backend), _store(tmp_path)
    )
    workflow.analyze()
    workflow.begin_capture()
    workflow.perform_capture()
    rendered_states: list[UIScreen] = []
    monkeypatch.setattr(
        pygame_device_ui,
        "_render",
        lambda pygame, screen, fonts, active, pressed: rendered_states.append(
            active.screen
        ),
    )
    pygame = SimpleNamespace(
        event=SimpleNamespace(pump=lambda: None),
        time=SimpleNamespace(wait=lambda milliseconds: None),
    )

    pygame_device_ui._apply_action(
        pygame, object(), object(), workflow, UIAction.ANALYZE_MEAL
    )

    assert rendered_states == [UIScreen.ANALYZING]
    assert workflow.screen is UIScreen.CALCULATED
    assert len(backend.calls) == 1


def test_review_and_result_actions_match_pi2a_workflow() -> None:
    review_labels = {button.label for button in buttons_for(UIScreen.REVIEW)}
    assert "Analyze Meal" in review_labels
    assert "Done" not in review_labels

    for screen in STATUS_SCREENS.values():
        labels = {button.label for button in buttons_for(screen)}
        assert {"Home", "Retake", "Exit"} <= labels


def test_ui_sources_have_no_direct_network_or_forbidden_contract_fields() -> None:
    source = "\n".join(
        Path(path).read_text()
        for path in (
            "src/nutribox_pi/device_ui.py",
            "src/nutribox_pi/adapters/pygame_device_ui.py",
        )
    )

    for forbidden in (
        "requests",
        "multipart",
        "user_id",
        "confidence",
    ):
        assert forbidden not in source
    assert re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", source) is None


class FakeScreen:
    def get_size(self) -> tuple[int, int]:
        return 800, 480


class FakeDisplay:
    def init(self) -> None:
        pass

    def get_init(self) -> bool:
        return True

    def set_mode(self, size: tuple[int, int], flags: int) -> FakeScreen:
        return FakeScreen()

    def set_caption(self, caption: str) -> None:
        pass


class FakeEventQueue:
    def __init__(self, failure: BaseException | None = None) -> None:
        self.failure = failure

    def get(self) -> list[object]:
        if self.failure is not None:
            raise self.failure
        return [SimpleNamespace(type=FakePygame.QUIT)]

    def pump(self) -> None:
        pass


class FakePygame:
    FULLSCREEN = 1
    QUIT = 2
    KEYDOWN = 3
    K_ESCAPE = 4
    MOUSEBUTTONDOWN = 5
    MOUSEBUTTONUP = 6
    FINGERDOWN = 7
    FINGERUP = 8

    def __init__(self, failure: BaseException | None = None) -> None:
        self.display = FakeDisplay()
        self.font = SimpleNamespace(Font=lambda name, size: object())
        self.event = FakeEventQueue(failure)
        self.quit_called = False

    def init(self) -> None:
        pass

    def quit(self) -> None:
        self.quit_called = True


@pytest.mark.parametrize("failure", [RuntimeError("secret UI path")])
def test_ui_exception_cleans_temporary_capture_and_is_normalized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
) -> None:
    store = _store(tmp_path)
    image = store.prepare()
    image.write_bytes(b"temporary meal")
    directory = image.parent
    pygame = FakePygame(failure)
    monkeypatch.setattr(pygame_device_ui, "_render", lambda *args: None)

    result = pygame_device_ui.run_device_ui(
        SimulatedCamera(), _controller(), pygame_module=pygame, store=store
    )

    assert result == UIResult(False, DISPLAY_ERROR)
    assert not image.exists()
    assert not directory.exists()
    assert pygame.quit_called is True


def test_ui_cancellation_cleans_temporary_capture_and_is_reraised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    image = store.prepare()
    image.write_bytes(b"temporary meal")
    directory = image.parent
    pygame = FakePygame(KeyboardInterrupt())
    monkeypatch.setattr(pygame_device_ui, "_render", lambda *args: None)

    with pytest.raises(KeyboardInterrupt):
        pygame_device_ui.run_device_ui(
            SimulatedCamera(), _controller(), pygame_module=pygame, store=store
        )

    assert not image.exists()
    assert not directory.exists()
    assert pygame.quit_called is True


def test_quit_cleans_temporary_capture_without_backend_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NUTRIBOX_API_BASE_URL", raising=False)
    store = _store(tmp_path)
    image = store.prepare()
    image.write_bytes(b"temporary meal")
    directory = image.parent
    pygame = FakePygame()
    monkeypatch.setattr(pygame_device_ui, "_render", lambda *args: None)

    result = pygame_device_ui.run_device_ui(
        SimulatedCamera(), _controller(), pygame_module=pygame, store=store
    )

    assert result.ok is True
    assert not image.exists()
    assert not directory.exists()


def test_escape_cleans_temporary_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    image = store.prepare()
    image.write_bytes(b"temporary meal")
    directory = image.parent
    pygame = FakePygame()
    pygame.event = SimpleNamespace(
        get=lambda: [SimpleNamespace(type=pygame.KEYDOWN, key=pygame.K_ESCAPE)]
    )
    monkeypatch.setattr(pygame_device_ui, "_render", lambda *args: None)

    result = pygame_device_ui.run_device_ui(
        SimulatedCamera(), _controller(), pygame_module=pygame, store=store
    )

    assert result.ok is True
    assert not image.exists()
    assert not directory.exists()


def test_cleanup_failure_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingCleanupStore(TemporaryCaptureStore):
        def cleanup(self) -> bool:
            return False

    pygame = FakePygame()
    monkeypatch.setattr(pygame_device_ui, "_render", lambda *args: None)

    result = pygame_device_ui.run_device_ui(
        SimulatedCamera(),
        _controller(),
        pygame_module=pygame,
        store=FailingCleanupStore(),
    )

    assert result == UIResult(False, "Temporary image cleanup failed.")


def test_private_capture_directory_mode(tmp_path: Path) -> None:
    store = _store(tmp_path)
    image = store.prepare()

    if os.name == "posix":
        assert image.parent.stat().st_mode & 0o777 == 0o700
    assert store.cleanup() is True


def test_device_ui_launcher_uses_existing_pi_environment_and_wayland_logic() -> None:
    script = Path("scripts/run_device_ui.sh")
    text = script.read_text()

    assert script.stat().st_mode & 0o111
    assert ".venv-pi/bin/python" in text
    assert "/run/user/$(id -u)" in text
    assert "sudo" not in text
    assert 'exec "$VENV_PYTHON" -m nutribox_pi ui' in text
    assert ".venv/bin/python" not in text
