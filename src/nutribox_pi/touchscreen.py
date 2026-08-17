"""Hardware-independent PI-1C touchscreen smoke-test state."""

from __future__ import annotations

from dataclasses import dataclass

DISPLAY_WIDTH = 800
DISPLAY_HEIGHT = 480


@dataclass(frozen=True, slots=True)
class TouchRect:
    x: int
    y: int
    width: int
    height: int

    def contains(self, x: float, y: float) -> bool:
        return self.x <= x < self.x + self.width and self.y <= y < self.y + self.height

    def as_tuple(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.width, self.height


@dataclass(frozen=True, slots=True)
class TouchTarget:
    label: str
    rectangle: TouchRect


TOUCH_TARGETS = (
    TouchTarget("TOP LEFT", TouchRect(40, 120, 220, 130)),
    TouchTarget("CENTER", TouchRect(290, 175, 220, 130)),
    TouchTarget("BOTTOM RIGHT", TouchRect(540, 320, 220, 120)),
)
EXIT_RECTANGLE = TouchRect(640, 20, 130, 72)


class TouchscreenProgress:
    def __init__(self) -> None:
        self._target_index = 0

    @property
    def complete(self) -> bool:
        return self._target_index == len(TOUCH_TARGETS)

    @property
    def completed_count(self) -> int:
        return self._target_index

    @property
    def active_target(self) -> TouchTarget | None:
        if self.complete:
            return None
        return TOUCH_TARGETS[self._target_index]

    def activate(self, x: float, y: float) -> bool:
        target = self.active_target
        if target is None or not target.rectangle.contains(x, y):
            return False
        self._target_index += 1
        return True


@dataclass(frozen=True, slots=True)
class TouchscreenCheckResult:
    ok: bool
    message: str

