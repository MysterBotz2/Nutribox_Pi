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
    CalculatedResponse,
    CameraCode,
    CaptureResult,
    HealthResult,
    NutritionReferenceNotFoundResponse,
    NutritionValues,
    PreviewFrame,
    RecognitionSource,
    RecognizedFood,
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


class RecordingPreviewSession:
    def __init__(self, camera: SimulatedCamera, *, close_result: bool = True) -> None:
        self.camera = camera
        self.close_result = close_result
        self.closed = False
        self.frame_calls = 0

    def read_frame(self) -> PreviewFrame | None:
        self.frame_calls += 1
        return PreviewFrame(640, 360, bytes((1, 2, 3)) * (640 * 360))

    def capture(self, output_path: Path, overwrite: bool = False) -> CaptureResult:
        return self.camera.capture(output_path, overwrite)

    def close(self) -> bool:
        self.closed = True
        return self.close_result


class RecordingPreviewCamera(SimulatedCamera):
    def __init__(self, *, close_result: bool = True) -> None:
        self.close_result = close_result
        self.sessions: list[RecordingPreviewSession] = []

    def open_preview_session(self) -> RecordingPreviewSession:
        session = RecordingPreviewSession(self, close_result=self.close_result)
        self.sessions.append(session)
        return session


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


def test_capture_entry_starts_preview_and_back_closes_it(tmp_path: Path) -> None:
    camera = RecordingPreviewCamera()
    workflow = MealCaptureWorkflow(camera, _controller(), _store(tmp_path))

    workflow.analyze()

    assert workflow.screen is UIScreen.CAPTURE
    assert len(camera.sessions) == 1
    assert workflow.preview_frame() == PreviewFrame(
        640, 360, bytes((1, 2, 3)) * (640 * 360)
    )
    workflow.back()
    assert workflow.screen is UIScreen.HOME
    assert camera.sessions[0].closed is True


def test_capture_closes_preview_before_review_and_retake_opens_new_preview(
    tmp_path: Path,
) -> None:
    camera = RecordingPreviewCamera()
    workflow = MealCaptureWorkflow(camera, _controller(), _store(tmp_path))
    workflow.analyze()
    first = camera.sessions[0]
    workflow.begin_capture()
    workflow.perform_capture()

    assert workflow.screen is UIScreen.REVIEW
    assert first.closed is True
    workflow.retake()
    assert workflow.screen is UIScreen.CAPTURE
    assert len(camera.sessions) == 2


def test_preview_cleanup_failure_overrides_capture_success(tmp_path: Path) -> None:
    workflow = MealCaptureWorkflow(
        RecordingPreviewCamera(close_result=False), _controller(), _store(tmp_path)
    )
    workflow.analyze()
    workflow.begin_capture()
    workflow.perform_capture()

    assert workflow.screen is UIScreen.ERROR
    assert workflow.error_message == CLEANUP_ERROR


def test_preview_failure_is_normalized(tmp_path: Path) -> None:
    class UnavailablePreviewCamera(SimulatedCamera):
        def open_preview_session(self) -> None:
            return None

    workflow = MealCaptureWorkflow(
        UnavailablePreviewCamera(), _controller(), _store(tmp_path)
    )

    workflow.analyze()

    assert workflow.screen is UIScreen.ERROR
    assert workflow.error_message == "Camera preview is unavailable."


def test_capture_cancellation_closes_preview_before_reraising(
    tmp_path: Path,
) -> None:
    class CancellingSession(RecordingPreviewSession):
        def capture(self, output_path: Path, overwrite: bool = False) -> CaptureResult:
            raise KeyboardInterrupt

    class CancellingCamera(RecordingPreviewCamera):
        def open_preview_session(self) -> CancellingSession:
            session = CancellingSession(self)
            self.sessions.append(session)
            return session

    camera = CancellingCamera()
    workflow = MealCaptureWorkflow(camera, _controller(), _store(tmp_path))
    workflow.analyze()
    workflow.begin_capture()

    with pytest.raises(KeyboardInterrupt):
        workflow.perform_capture()

    assert camera.sessions[0].closed is True


def test_preview_loop_throttles_to_about_fifteen_fps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    camera = RecordingPreviewCamera()
    workflow = MealCaptureWorkflow(camera, _controller(), _store(tmp_path))
    workflow.analyze()
    events = iter([[], [SimpleNamespace(type=FakePygame.QUIT)]])
    waits: list[int] = []
    pygame = SimpleNamespace(
        QUIT=FakePygame.QUIT,
        KEYDOWN=FakePygame.KEYDOWN,
        K_ESCAPE=FakePygame.K_ESCAPE,
        MOUSEBUTTONDOWN=FakePygame.MOUSEBUTTONDOWN,
        MOUSEBUTTONUP=FakePygame.MOUSEBUTTONUP,
        FINGERDOWN=FakePygame.FINGERDOWN,
        FINGERUP=FakePygame.FINGERUP,
        event=SimpleNamespace(get=lambda: next(events)),
        time=SimpleNamespace(wait=waits.append),
    )
    monotonic_values = iter([0.0, 0.0, 0.01])
    monkeypatch.setattr(
        pygame_device_ui.time, "monotonic", lambda: next(monotonic_values)
    )
    monkeypatch.setattr(
        pygame_device_ui._PreviewSurfaceCache, "update", lambda *args: None
    )
    monkeypatch.setattr(pygame_device_ui, "_render", lambda *args: None)

    result = pygame_device_ui._run_loop(pygame, object(), object(), workflow)

    assert result.ok is True
    assert camera.sessions[0].frame_calls == 1
    assert waits == [67]


def test_preview_cache_detaches_scales_once_and_persists() -> None:
    class RawSurface:
        def __init__(self) -> None:
            self.copied = False

        def copy(self) -> CachedSurface:
            self.copied = True
            return CachedSurface()

    class CachedSurface:
        def get_size(self) -> tuple[int, int]:
            return 420, 236

    raw = RawSurface()
    scaled = CachedSurface()
    scale_calls: list[tuple[object, tuple[int, int]]] = []
    pygame = SimpleNamespace(
        image=SimpleNamespace(frombuffer=lambda *args: raw),
        transform=SimpleNamespace(
            smoothscale=lambda surface, size: scale_calls.append((surface, size))
            or scaled
        ),
    )
    cache = pygame_device_ui._PreviewSurfaceCache()
    frame = PreviewFrame(640, 360, bytes((1, 2, 3)) * (640 * 360))

    cache.update(pygame, frame)

    assert raw.copied is True
    assert len(scale_calls) == 1
    assert scale_calls[0][0] is not raw
    assert scale_calls[0][1] == (420, 236)
    assert cache.surface is scaled
    assert cache.surface is cache.surface


def test_render_performs_one_display_flip_per_cycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow = MealCaptureWorkflow(
        SimulatedCamera(), _controller(), _store(tmp_path)
    )
    flips: list[None] = []
    pygame = SimpleNamespace(
        display=SimpleNamespace(flip=lambda: flips.append(None))
    )
    screen = SimpleNamespace(fill=lambda color: None)
    monkeypatch.setattr(pygame_device_ui, "_render_home", lambda *args: None)
    monkeypatch.setattr(pygame_device_ui, "_draw_button", lambda *args: None)

    pygame_device_ui._render(
        pygame, screen, SimpleNamespace(button=object()), workflow, None
    )

    assert flips == [None]


def test_retake_deletes_image_and_returns_to_capture(tmp_path: Path) -> None:
    workflow = _captured_workflow(tmp_path)
    image = workflow.review_image
    assert image is not None
    directory = image.parent

    workflow.retake()

    assert workflow.screen is UIScreen.CAPTURE
    assert not image.exists()
    assert not directory.exists()


def test_analysis_uses_controller_once_not_food_recognizer_and_cleans_image(
    tmp_path: Path,
) -> None:
    class TypedBackend(RecordingBackend):
        def analyze_meal(
            self, image_path: Path, weight_grams: float
        ) -> CalculatedResponse:
            self.calls.append((image_path, weight_grams))
            return CalculatedResponse(
                AnalysisStatus.CALCULATED,
                (RecognizedFood("Rice"),),
                RecognitionSource.SIMULATED,
                nutrition=NutritionValues("100", "2", "20", "1", "3"),
            )

    backend = TypedBackend()
    workflow = MealCaptureWorkflow(
        SimulatedCamera(),
        _controller(backend, weight=321.5),
        _store(tmp_path),
        True,
    )
    workflow.analyze()
    workflow.begin_capture()
    workflow.perform_capture()
    image = workflow.review_image
    assert image is not None
    directory = image.parent

    workflow.begin_analysis()
    workflow.perform_analysis()

    assert workflow.screen is UIScreen.CALCULATED
    assert backend.calls == [(image, 321.5)]
    assert workflow.analysis_response is not None
    assert workflow.recognition_source is RecognitionSource.SIMULATED
    assert not image.exists()
    assert not directory.exists()


def test_active_ui_sources_do_not_call_food_recognizer() -> None:
    source = Path("src/nutribox_pi/device_ui.py").read_text()
    assert "recognize_food(" not in source


def test_nutrition_reference_result_flows_through_controller_workflow_and_ui(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class ReferenceMissingBackend(RecordingBackend):
        def analyze_meal(
            self, image_path: Path, weight_grams: float
        ) -> NutritionReferenceNotFoundResponse:
            self.calls.append((image_path, weight_grams))
            return NutritionReferenceNotFoundResponse(
                AnalysisStatus.NUTRITION_REFERENCE_NOT_FOUND,
                (RecognizedFood("chicken adobo"),),
                RecognitionSource.SIMULATED,
            )

    backend = ReferenceMissingBackend()
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
    workflow.perform_analysis()

    assert workflow.screen is UIScreen.NUTRITION_REFERENCE_NOT_FOUND
    assert workflow.recognized_foods == (RecognizedFood("chicken adobo"),)
    assert workflow.recognition_source is RecognitionSource.SIMULATED
    assert not image.exists()
    assert not directory.exists()

    text: list[str] = []
    monkeypatch.setattr(
        pygame_device_ui,
        "_draw_text",
        lambda screen, font, value, center, color: text.append(value),
    )
    monkeypatch.setattr(pygame_device_ui, "_draw_card", lambda *args: None)
    font = SimpleNamespace(size=lambda value: (len(value), 1))
    pygame_device_ui._render_result(
        SimpleNamespace(),
        object(),
        SimpleNamespace(subheading=font, body=font, small=font),
        workflow,
    )

    assert "chicken adobo" in text
    assert "No nutrition reference is available." in text
    assert "Simulated recognition" in text


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
        def open_preview_session(self) -> RecordingPreviewSession:
            class FailingPreview:
                def read_frame(self) -> PreviewFrame | None:
                    return None

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

                def close(self) -> bool:
                    return True

            return FailingPreview()  # type: ignore[return-value]

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
