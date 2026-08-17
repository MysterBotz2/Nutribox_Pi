from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from nutribox_pi.adapters import pygame_touchscreen
from nutribox_pi.touchscreen import TOUCH_TARGETS, TouchscreenProgress


def _center(index: int) -> tuple[int, int]:
    rectangle = TOUCH_TARGETS[index].rectangle
    return (
        rectangle.x + rectangle.width // 2,
        rectangle.y + rectangle.height // 2,
    )


def test_three_target_progression_is_sequential() -> None:
    progress = TouchscreenProgress()

    for index in range(3):
        assert progress.active_target == TOUCH_TARGETS[index]
        assert progress.activate(*_center(index)) is True

    assert progress.complete is True
    assert progress.active_target is None


def test_tap_outside_active_target_does_not_advance() -> None:
    progress = TouchscreenProgress()

    assert progress.activate(799, 479) is False
    assert progress.completed_count == 0
    assert progress.active_target == TOUCH_TARGETS[0]


class FakeRenderedText:
    def get_rect(self, **kwargs: object) -> object:
        return kwargs


class FakeFont:
    def render(self, text: str, antialias: bool, color: object) -> FakeRenderedText:
        return FakeRenderedText()


class FakeScreen:
    def __init__(self, resolution: tuple[int, int]) -> None:
        self.resolution = resolution

    def get_size(self) -> tuple[int, int]:
        return self.resolution

    def fill(self, color: object) -> None:
        pass

    def blit(self, rendered: object, rectangle: object) -> None:
        pass


class FakeDisplay:
    def __init__(
        self,
        resolution: tuple[int, int],
        *,
        initialization_error: Exception | None = None,
    ) -> None:
        self.resolution = resolution
        self.initialization_error = initialization_error
        self.initialized = False
        self.mode_request: tuple[tuple[int, int], int] | None = None

    def init(self) -> None:
        if self.initialization_error is not None:
            raise self.initialization_error
        self.initialized = True

    def get_init(self) -> bool:
        return self.initialized

    def set_mode(self, size: tuple[int, int], flags: int) -> FakeScreen:
        self.mode_request = (size, flags)
        return FakeScreen(self.resolution)

    def set_caption(self, caption: str) -> None:
        pass

    def flip(self) -> None:
        pass


class FakePygame:
    FULLSCREEN = 1
    QUIT = 2
    KEYDOWN = 3
    K_ESCAPE = 4
    MOUSEBUTTONUP = 5
    FINGERUP = 6

    def __init__(
        self,
        events: list[object],
        *,
        resolution: tuple[int, int] = (800, 480),
        initialization_error: Exception | None = None,
        display_error: Exception | None = None,
    ) -> None:
        self.events = events
        self.initialization_error = initialization_error
        self.display = FakeDisplay(
            resolution, initialization_error=display_error
        )
        self.font = SimpleNamespace(Font=lambda name, size: FakeFont())
        self.draw = SimpleNamespace(rect=lambda *args, **kwargs: None)
        self.event = SimpleNamespace(get=self._events)
        self.time = SimpleNamespace(wait=lambda milliseconds: None)
        self.quit_called = False

    def init(self) -> None:
        if self.initialization_error is not None:
            raise self.initialization_error

    def quit(self) -> None:
        self.quit_called = True

    def _events(self) -> list[object]:
        events, self.events = self.events, []
        return events


def _mouse_event(position: tuple[int, int]) -> object:
    return SimpleNamespace(type=FakePygame.MOUSEBUTTONUP, button=1, pos=position)


def _run_with_fake(
    monkeypatch: pytest.MonkeyPatch, pygame: FakePygame
) -> pygame_touchscreen.TouchscreenCheckResult:
    monkeypatch.setattr(
        pygame_touchscreen.importlib,
        "import_module",
        lambda name: pygame,
    )
    return pygame_touchscreen.run_touchscreen_check()


def test_runtime_completes_three_targets_and_exits_successfully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pygame = FakePygame(
        [
            _mouse_event((799, 479)),
            _mouse_event(_center(0)),
            _mouse_event(_center(1)),
            _mouse_event(_center(2)),
        ]
    )

    result = _run_with_fake(monkeypatch, pygame)

    assert result.ok is True
    assert result.message == "Touchscreen check passed."
    assert pygame.display.mode_request == ((800, 480), pygame.FULLSCREEN)
    assert pygame.quit_called is True


@pytest.mark.parametrize(
    "event",
    [
        SimpleNamespace(type=FakePygame.QUIT),
        SimpleNamespace(type=FakePygame.KEYDOWN, key=FakePygame.K_ESCAPE),
        _mouse_event((705, 56)),
    ],
)
def test_runtime_early_exit_returns_failure(
    monkeypatch: pytest.MonkeyPatch, event: object
) -> None:
    result = _run_with_fake(monkeypatch, FakePygame([event]))

    assert result.ok is False
    assert result.message == "Touchscreen check exited."


def test_runtime_rejects_incorrect_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _run_with_fake(
        monkeypatch, FakePygame([], resolution=(1024, 768))
    )

    assert result.ok is False
    assert result.message == "Touchscreen check unavailable."


@pytest.mark.parametrize("failure_location", ["pygame", "display"])
def test_runtime_normalizes_initialization_failures(
    monkeypatch: pytest.MonkeyPatch, failure_location: str
) -> None:
    error = RuntimeError("secret display details")
    pygame = FakePygame(
        [],
        initialization_error=error if failure_location == "pygame" else None,
        display_error=error if failure_location == "display" else None,
    )

    result = _run_with_fake(monkeypatch, pygame)

    assert result.ok is False
    assert result.message == "Touchscreen check unavailable."
    assert "secret" not in result.message


def test_missing_pygame_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(name: str) -> Any:
        raise ImportError("secret pygame path")

    monkeypatch.setattr(pygame_touchscreen.importlib, "import_module", missing)

    result = pygame_touchscreen.run_touchscreen_check()

    assert result.ok is False
    assert result.message == "Touchscreen check unavailable."


def test_touchscreen_launcher_is_executable_and_uses_only_pi_environment() -> None:
    script = Path("scripts/run_touchscreen_smoke_test.sh")
    text = script.read_text()

    assert script.stat().st_mode & 0o111
    assert ".venv-pi/bin/python" in text
    assert "sudo" not in text
    assert "/run/user/$(id -u)" in text
    assert 'exec "$VENV_PYTHON" -m nutribox_pi touchscreen-check' in text
    assert "NUTRIBOX_API_BASE_URL" not in text
