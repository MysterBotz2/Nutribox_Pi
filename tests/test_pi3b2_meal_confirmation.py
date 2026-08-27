from __future__ import annotations

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from nutribox_pi.adapters import pygame_device_ui
from nutribox_pi.adapters.mock_hardware import SimulatedTemperatureSensor
from nutribox_pi.adapters.simulated_camera import SimulatedCamera
from nutribox_pi.adapters.v1_backend import V1BackendClient
from nutribox_pi.controller import NutriBoxController
from nutribox_pi.device_ui import (
    ANALYSIS_ERROR,
    DISPLAY_SIZE,
    MealCaptureWorkflow,
    TemporaryCaptureStore,
    UIScreen,
)
from nutribox_pi.models import AnalysisResult, AnalysisStatus, HealthResult
from nutribox_pi.pairing import REVOKED_MESSAGE, PairingState
from nutribox_pi.ports import DeviceAuthenticationFailure, RetryableBackendFailure
from nutribox_pi.ui_preferences import Language


class SequenceWeight:
    def __init__(self, *values: float) -> None:
        self.values = iter(values)
        self.calls = 0

    def read_grams(self) -> float:
        self.calls += 1
        return next(self.values)


class RecordingBackend:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls: list[tuple[Path, float, str | None]] = []

    def health(self) -> HealthResult:
        return HealthResult(True, {})

    def analyze_meal(
        self, image_path: Path, weight_grams: float, device_token: str | None = None
    ) -> AnalysisResult:
        self.calls.append((image_path, weight_grams, device_token))
        if self.failure is not None:
            raise self.failure
        return AnalysisResult(AnalysisStatus.CALCULATED, {})


class CredentialProvider:
    def __init__(self, token: str | None) -> None:
        self.token = token
        self.revoked = False

    def get_verified_device_token(self) -> str | None:
        return self.token

    def confirm_revocation(self) -> None:
        self.token = None
        self.revoked = True


def workflow_for(
    tmp_path: Path,
    backend: RecordingBackend,
    weight: SequenceWeight,
    credential: CredentialProvider | None = None,
) -> MealCaptureWorkflow:
    controller = NutriBoxController(
        backend,
        weight,
        SimulatedTemperatureSensor(),
        credential,
    )
    store = TemporaryCaptureStore(
        lambda **_: tempfile.mkdtemp(prefix="capture-", dir=tmp_path)
    )
    return MealCaptureWorkflow(SimulatedCamera(), controller, store, True)


def capture(workflow: MealCaptureWorkflow) -> Path:
    workflow.analyze()
    assert workflow.screen is UIScreen.CAPTURE
    workflow.begin_capture()
    workflow.perform_capture()
    assert workflow.screen is UIScreen.REVIEW
    assert workflow.review_image is not None
    return workflow.review_image


@pytest.mark.parametrize("token", [None, "verified-device-token"])
def test_capture_weight_snapshot_is_uploaded_once_on_explicit_confirm(
    tmp_path: Path, token: str | None
) -> None:
    backend = RecordingBackend()
    weight = SequenceWeight(321.5, 999.0)
    credential = CredentialProvider(token)
    workflow = workflow_for(tmp_path, backend, weight, credential)
    image = capture(workflow)

    assert workflow.captured_weight_grams == 321.5
    assert weight.calls == 1
    assert backend.calls == []
    workflow.begin_analysis()
    workflow.begin_analysis()  # duplicate confirmation is fenced by state
    workflow.perform_analysis()
    workflow.perform_analysis()

    assert backend.calls == [(image, 321.5, token)]
    assert weight.calls == 1
    assert not image.exists()


def test_retake_and_back_clear_image_weight_and_preview(tmp_path: Path) -> None:
    workflow = workflow_for(tmp_path, RecordingBackend(), SequenceWeight(100, 200))
    first = capture(workflow)
    workflow.retake()
    assert workflow.screen is UIScreen.CAPTURE
    assert workflow.captured_weight_grams is None
    assert not first.exists()
    workflow.begin_capture()
    workflow.perform_capture()
    second = workflow.review_image
    assert second is not None and workflow.captured_weight_grams == 200
    workflow.back()
    assert workflow.screen is UIScreen.HOME
    assert workflow.captured_weight_grams is None and not second.exists()


def test_retryable_failure_retains_capture_until_explicit_retry(tmp_path: Path) -> None:
    backend = RecordingBackend(RetryableBackendFailure())
    workflow = workflow_for(tmp_path, backend, SequenceWeight(250))
    image = capture(workflow)
    workflow.begin_analysis()
    workflow.perform_analysis()
    assert workflow.screen is UIScreen.ERROR
    assert workflow.error_message == ANALYSIS_ERROR
    assert workflow.analysis_retry_available is True
    assert image.exists() and workflow.captured_weight_grams == 250
    workflow.retry()
    assert workflow.screen is UIScreen.REVIEW
    assert len(backend.calls) == 1


def test_confirmed_401_revokes_and_cleans_capture(tmp_path: Path) -> None:
    backend = RecordingBackend(DeviceAuthenticationFailure())
    credential = CredentialProvider("verified")
    workflow = workflow_for(tmp_path, backend, SequenceWeight(250), credential)
    image = capture(workflow)
    workflow.begin_analysis()
    workflow.perform_analysis()
    assert credential.revoked is True and credential.token is None
    assert workflow.screen is UIScreen.HOME
    assert workflow.captured_weight_grams is None and not image.exists()


def test_periodic_revocation_stops_preview_and_cleans_state(tmp_path: Path) -> None:
    class RevokedPairing:
        state = PairingState.PAIRED
        error_message = None

        def tick(self) -> None:
            self.state = PairingState.UNPAIRED
            self.error_message = REVOKED_MESSAGE

    workflow = workflow_for(tmp_path, RecordingBackend(), SequenceWeight(250))
    workflow.pairing = RevokedPairing()  # type: ignore[assignment]
    workflow.analyze()
    assert workflow.screen is UIScreen.CAPTURE
    workflow.tick_pairing()
    assert workflow.screen is UIScreen.HOME
    assert workflow.preview_frame() is None
    assert workflow.captured_weight_grams is None


def test_frozen_confirmation_is_not_replaced_by_preview(tmp_path: Path) -> None:
    workflow = workflow_for(tmp_path, RecordingBackend(), SequenceWeight(250))
    image = capture(workflow)
    assert workflow.preview_frame() is None
    assert workflow.review_image == image


def test_transport_uses_only_one_device_header_and_no_authorization(
    tmp_path: Path,
) -> None:
    class Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "status": "food_not_recognized",
                "recognized_foods": [],
                "recognition_source": "simulated",
            }

    class Session:
        calls: list[dict[str, object]] = []

        def request(self, method: str, url: str, **kwargs: object) -> Response:
            self.calls.append(kwargs)
            return Response()

    image = tmp_path / "meal.jpg"
    image.write_bytes(b"jpeg")
    session = Session()
    V1BackendClient(
        "https://backend.test",
        session=session,  # type: ignore[arg-type]
    ).analyze_meal(image, 250, "verified")
    headers = session.calls[0]["headers"]
    assert headers == {"X-Device-Token": "verified"}
    assert "Authorization" not in headers


@pytest.mark.parametrize("language", [Language.ENGLISH, Language.TAGALOG])
def test_sdl_dummy_renders_preview_confirmation_analyzing_and_error(
    tmp_path: Path, language: Language
) -> None:
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame = pytest.importorskip("pygame")
    pygame.init()
    try:
        surface = pygame.Surface(DISPLAY_SIZE)
        fonts = pygame_device_ui._Fonts(
            heading=pygame.font.Font(None, 48),
            subheading=pygame.font.Font(None, 34),
            body=pygame.font.Font(None, 28),
            small=pygame.font.Font(None, 20),
            button=pygame.font.Font(None, 32),
        )
        captured = tmp_path / "captured.jpg"
        pygame.image.save(pygame.Surface((1920, 1080)), captured)
        workflow = SimpleNamespace(
            language=language,
            screen=UIScreen.CAPTURE,
            simulated_camera=True,
            simulated_weight=True,
            captured_weight_grams=250.0,
            review_image=captured,
        )
        preview = pygame.Surface((420, 236))
        pygame_device_ui._render_capture(pygame, surface, fonts, workflow, preview)
        workflow.screen = UIScreen.REVIEW
        pygame_device_ui._render_review(
            pygame, surface, fonts, workflow, pygame_device_ui._UiImageCache()
        )
        workflow.screen = UIScreen.ANALYZING
        pygame_device_ui._render_analyzing(pygame, surface, fonts, workflow)
        pygame_device_ui._render_error(
            pygame, surface, fonts, "Camera preview is unavailable."
        )
        bounds = surface.get_bounding_rect(min_alpha=1)
        assert bounds.right <= 800 and bounds.bottom <= 480
    finally:
        pygame.quit()
