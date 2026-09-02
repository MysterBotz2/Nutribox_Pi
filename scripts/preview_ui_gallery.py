#!/usr/bin/env python3
"""Render deterministic 800x480 UI reference states without device access.

This is a developer-only gallery.  It creates no controller, camera, network
client, credential store, GPIO object, or persistent image file.
"""

from __future__ import annotations

import argparse
import importlib
import os
from pathlib import Path

SCREENS = (
    "loading",
    "language",
    "instructions",
    "guest-home",
    "paired-home",
    "camera-preview",
    "capture-review",
    "food-selection",
    "ingredient-confirmation",
    "ingredient-editor",
    "recipe-confirmation",
    "calculated",
    "save-success",
    "profile-settings",
    "leftover-guest",
    "saved-meals",
    "leftover-review",
    "leftover-calculated",
    "recording",
    "leftover-summary",
    "leftover-retryable-error",
)


def _pygame() -> object:
    try:
        return importlib.import_module("pygame")
    except ModuleNotFoundError as exc:
        raise RuntimeError("Pygame is unavailable for the UI gallery.") from exc


def render(
    name: str,
    output: Path | None = None,
    *,
    language: str = "english",
    theme: str = "light",
) -> None:
    pygame = _pygame()
    pygame.init()
    screen = pygame.display.set_mode((800, 480))
    font = pygame.font.SysFont("sans", 30)
    small = pygame.font.SysFont("sans", 20)
    background = (255, 255, 255) if theme == "light" else (24, 28, 34)
    text_color = (9, 59, 125) if theme == "light" else (225, 234, 246)
    secondary = (96, 100, 108) if theme == "light" else (190, 200, 214)
    card = (240, 240, 243) if theme == "light" else (47, 53, 63)
    screen.fill(background)
    for x in range(0, 800, 20):
        pygame.draw.line(screen, (242, 247, 252), (x, 0), (x, 480))
    for y in range(0, 480, 20):
        pygame.draw.line(screen, (242, 247, 252), (0, y), (800, y))
    title = name.replace("-", " ").title()
    screen.blit(font.render(title, True, text_color), (38, 34))
    pygame.draw.rect(screen, card, (42, 95, 716, 250), border_radius=16)
    screen.blit(
        small.render(
            "Developer preview" if language == "english" else "Preview ng developer",
            True,
            secondary,
        ),
        (68, 125),
    )
    pygame.draw.rect(screen, (9, 59, 125), (260, 375, 280, 58), border_radius=12)
    screen.blit(small.render("Sample action", True, (255, 255, 255)), (340, 394))
    pygame.display.flip()
    if output is not None:
        output.mkdir(parents=True, exist_ok=True)
        pygame.image.save(screen, str(output / f"{name}-{language}-{theme}.png"))
    pygame.quit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screen", choices=SCREENS, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--language", choices=("english", "tagalog"), default="english")
    parser.add_argument("--theme", choices=("light", "dark"), default="light")
    args = parser.parse_args()
    # SDL dummy is deliberately supported for CI/Windows gallery checks.
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    try:
        render(
            args.screen,
            args.output_dir,
            language=args.language,
            theme=args.theme,
        )
    except RuntimeError as exc:
        print(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
