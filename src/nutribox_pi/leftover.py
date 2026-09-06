"""Hardware-independent state for an explicit paired-device leftover scan."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from nutribox_pi.controller import NutriBoxController
from nutribox_pi.models import LeftoverScanResponse, SavedMealPage
from nutribox_pi.ports import DeviceAuthenticationFailure, RetryableBackendFailure


class LeftoverState(StrEnum):
    IDLE = "idle"
    GUEST = "guest"
    LOADING = "loading"
    SELECTING = "selecting"
    EMPTY = "empty"
    RETRYABLE_ERROR = "retryable_error"
    RECORDING = "recording"
    SUMMARY = "summary"
    ERROR = "error"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class SavedMealSelectionView:
    names: tuple[str, ...]
    timestamps: tuple[str, ...]
    weights: tuple[str, ...]
    page: int
    has_next: bool
    selected_index: int | None


class LeftoverWorkflow:
    """Owns opaque saved-meal/session identifiers; renderers see ordinals only."""

    page_size = 4

    def __init__(self, controller: NutriBoxController) -> None:
        self._controller = controller
        self.state = LeftoverState.IDLE
        self._page: SavedMealPage | None = None
        self._selected_meal_id: int | None = None
        self._summary: LeftoverScanResponse | None = None
        self._generation = 0

    @property
    def selected_meal_id(self) -> int | None:
        return self._selected_meal_id

    @property
    def has_selection(self) -> bool:
        return self._selected_meal_id is not None

    @property
    def summary(self) -> LeftoverScanResponse | None:
        return self._summary

    @property
    def selection_view(self) -> SavedMealSelectionView:
        page = self._page
        if page is None:
            return SavedMealSelectionView((), (), (), 0, False, None)
        meals = page.meals[: self.page_size]
        return SavedMealSelectionView(
            tuple(" · ".join(meal.food_names) for meal in meals),
            tuple(meal.recorded_at.date().isoformat() for meal in meals),
            tuple(meal.weight_grams for meal in meals),
            page.offset // self.page_size,
            len(page.meals) > self.page_size,
            next(
                (
                    index
                    for index, meal in enumerate(meals)
                    if meal.id == self._selected_meal_id
                ),
                None,
            ),
        )

    def open(self, paired: bool) -> None:
        self._generation += 1
        self._page = None
        self._selected_meal_id = None
        self._summary = None
        if not paired:
            self.state = LeftoverState.GUEST
            return
        self.load(0)

    def load(self, offset: int) -> None:
        self.state = LeftoverState.LOADING
        try:
            # One extra row is a private pagination lookahead.  It prevents the
            # renderer from offering Next when no further saved meal exists.
            page = self._controller.list_saved_meals(self.page_size + 1, offset)
        except DeviceAuthenticationFailure:
            self._clear(LeftoverState.REVOKED)
        except RetryableBackendFailure:
            self.state = LeftoverState.RETRYABLE_ERROR
        except Exception:
            self.state = LeftoverState.ERROR
        else:
            self._page = page
            self.state = (
                LeftoverState.EMPTY if not page.meals else LeftoverState.SELECTING
            )

    def select(self, ordinal: int) -> bool:
        page = self._page
        if self.state is not LeftoverState.SELECTING or page is None:
            return False
        if isinstance(ordinal, bool) or not isinstance(ordinal, int):
            return False
        if not 0 <= ordinal < min(len(page.meals), self.page_size):
            return False
        self._selected_meal_id = page.meals[ordinal].id
        return True

    def select_saved_meal_id(self, meal_id: int) -> bool:
        if isinstance(meal_id, bool) or not isinstance(meal_id, int) or meal_id <= 0:
            return False
        self._selected_meal_id = meal_id
        return True

    def record(self, analysis_session_id: int) -> None:
        if self.state is LeftoverState.RECORDING or self._selected_meal_id is None:
            return
        self.state = LeftoverState.RECORDING
        try:
            self._summary = self._controller.create_leftover_scan(
                self._selected_meal_id, analysis_session_id
            )
        except DeviceAuthenticationFailure:
            self._clear(LeftoverState.REVOKED)
        except RetryableBackendFailure:
            self.state = LeftoverState.RETRYABLE_ERROR
        except Exception:
            self.state = LeftoverState.ERROR
        else:
            self.state = LeftoverState.SUMMARY

    def clear(self) -> None:
        self._clear(LeftoverState.IDLE)

    def _clear(self, state: LeftoverState) -> None:
        self._generation += 1
        self._page = None
        self._selected_meal_id = None
        self._summary = None
        self.state = state
