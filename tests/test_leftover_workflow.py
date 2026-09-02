from __future__ import annotations

from datetime import UTC, datetime

from nutribox_pi.leftover import LeftoverState, LeftoverWorkflow
from nutribox_pi.models import (
    LeftoverScanResponse,
    NutritionValues,
    SavedMealListItem,
    SavedMealPage,
)
from nutribox_pi.ports import DeviceAuthenticationFailure, RetryableBackendFailure


def _nutrition() -> NutritionValues:
    return NutritionValues("1", "1", "1", "1", "1")


class _Controller:
    def __init__(self) -> None:
        self.page = SavedMealPage(
            (SavedMealListItem(3, datetime.now(UTC), ("Safe meal",), "120"),), 4, 0
        )
        self.recorded: tuple[int, int] | None = None
        self.failure: Exception | None = None

    def list_saved_meals(self, limit: int, offset: int) -> SavedMealPage:
        if self.failure:
            raise self.failure
        assert (limit, offset) == (4, 0)
        return self.page

    def create_leftover_scan(
        self, meal_id: int, session_id: int
    ) -> LeftoverScanResponse:
        if self.failure:
            raise self.failure
        self.recorded = meal_id, session_id
        return LeftoverScanResponse(
            7,
            meal_id,
            session_id,
            "120",
            "40",
            "80",
            "66.7",
            _nutrition(),
            _nutrition(),
            (),
            datetime.now(UTC),
        )


def test_guest_suppresses_all_leftover_requests() -> None:
    controller = _Controller()
    workflow = LeftoverWorkflow(controller)  # type: ignore[arg-type]
    workflow.open(False)
    assert workflow.state is LeftoverState.GUEST
    assert controller.recorded is None


def test_saved_meal_ordinal_is_private_and_record_body_state_is_explicit() -> None:
    controller = _Controller()
    workflow = LeftoverWorkflow(controller)  # type: ignore[arg-type]
    workflow.open(True)
    assert workflow.state is LeftoverState.SELECTING
    assert workflow.selection_view.names == ("Safe meal",)
    assert workflow.select(0)
    workflow.record(9)
    assert controller.recorded == (3, 9)
    assert workflow.state is LeftoverState.SUMMARY
    assert workflow.summary is not None


def test_retryable_failure_retains_no_unsafe_state_and_revocation_clears() -> None:
    controller = _Controller()
    workflow = LeftoverWorkflow(controller)  # type: ignore[arg-type]
    controller.failure = RetryableBackendFailure("backend request failed")
    workflow.open(True)
    assert workflow.state is LeftoverState.RETRYABLE_ERROR
    controller.failure = DeviceAuthenticationFailure("device authentication failed")
    workflow.open(True)
    assert workflow.state is LeftoverState.REVOKED
    assert workflow.selected_meal_id is None
    assert workflow.summary is None
