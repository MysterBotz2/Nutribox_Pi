"""Lazy pygame adapter for the PI-1C touchscreen smoke test."""

from __future__ import annotations

import importlib
from contextlib import suppress
from typing import Any

from nutribox_pi.touchscreen import (
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    EXIT_RECTANGLE,
    TOUCH_TARGETS,
    TouchRect,
    TouchscreenCheckResult,
    TouchscreenProgress,
)

UNAVAILABLE = "Touchscreen check unavailable."
EXITED = "Touchscreen check exited."
PASSED = "Touchscreen check passed."


def run_touchscreen_check() -> TouchscreenCheckResult:
    try:
        pygame = importlib.import_module("pygame")
    except Exception:
        return TouchscreenCheckResult(False, UNAVAILABLE)

    try:
        pygame.init()
        pygame.display.init()
        if not pygame.display.get_init():
            return TouchscreenCheckResult(False, UNAVAILABLE)
        screen = pygame.display.set_mode(
            (DISPLAY_WIDTH, DISPLAY_HEIGHT), pygame.FULLSCREEN
        )
        if tuple(screen.get_size()) != (DISPLAY_WIDTH, DISPLAY_HEIGHT):
            return TouchscreenCheckResult(False, UNAVAILABLE)
        pygame.display.set_caption("Nutri-Box touchscreen check")
        title_font = pygame.font.Font(None, 52)
        body_font = pygame.font.Font(None, 38)
        target_font = pygame.font.Font(None, 40)
        progress = TouchscreenProgress()

        while True:
            _draw_screen(
                pygame,
                screen,
                progress,
                title_font,
                body_font,
                target_font,
            )
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return TouchscreenCheckResult(False, EXITED)
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    return TouchscreenCheckResult(False, EXITED)
                point = _activation_point(pygame, event)
                if point is None:
                    continue
                x, y = point
                if EXIT_RECTANGLE.contains(x, y):
                    return TouchscreenCheckResult(False, EXITED)
                if progress.activate(x, y) and progress.complete:
                    _draw_pass(pygame, screen, title_font)
                    pygame.time.wait(900)
                    return TouchscreenCheckResult(True, PASSED)
    except Exception:
        return TouchscreenCheckResult(False, UNAVAILABLE)
    finally:
        with suppress(Exception):
            pygame.quit()


def _activation_point(pygame: Any, event: Any) -> tuple[float, float] | None:
    if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
        return float(event.pos[0]), float(event.pos[1])
    if event.type == pygame.FINGERUP:
        return event.x * DISPLAY_WIDTH, event.y * DISPLAY_HEIGHT
    return None


def _draw_screen(
    pygame: Any,
    screen: Any,
    progress: TouchscreenProgress,
    title_font: Any,
    body_font: Any,
    target_font: Any,
) -> None:
    screen.fill((8, 15, 28))
    _draw_text(screen, title_font, "Nutri-Box Touch Test", (400, 48), (255, 255, 255))
    _draw_text(
        screen,
        body_font,
        f"Target {progress.completed_count + 1} of {len(TOUCH_TARGETS)}",
        (400, 92),
        (190, 220, 255),
    )
    pygame.draw.rect(screen, (190, 30, 45), EXIT_RECTANGLE.as_tuple(), border_radius=12)
    _draw_text(screen, body_font, "EXIT", (705, 56), (255, 255, 255))
    target = progress.active_target
    if target is not None:
        pygame.draw.rect(
            screen,
            (255, 205, 0),
            target.rectangle.as_tuple(),
            border_radius=18,
        )
        _draw_text(
            screen,
            target_font,
            target.label,
            _center(target.rectangle),
            (10, 10, 10),
        )
    pygame.display.flip()


def _draw_pass(pygame: Any, screen: Any, title_font: Any) -> None:
    screen.fill((0, 85, 45))
    pygame.draw.rect(screen, (190, 30, 45), EXIT_RECTANGLE.as_tuple(), border_radius=12)
    _draw_text(screen, title_font, "PASS", (400, 240), (255, 255, 255))
    pygame.display.flip()


def _draw_text(
    screen: Any,
    font: Any,
    text: str,
    center: tuple[int, int],
    color: tuple[int, int, int],
) -> None:
    rendered = font.render(text, True, color)
    screen.blit(rendered, rendered.get_rect(center=center))


def _center(rectangle: TouchRect) -> tuple[int, int]:
    return (
        rectangle.x + rectangle.width // 2,
        rectangle.y + rectangle.height // 2,
    )
