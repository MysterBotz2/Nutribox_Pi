from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import replace

import pytest

from nutribox_pi.continuation import (
    RETRYABLE_ERROR_MESSAGE,
    ContinuationError,
    ContinuationState,
    MealAnalysisContinuationWorkflow,
)
from nutribox_pi.controller import NutriBoxController
from nutribox_pi.models import (
    AnalysisStatus,
    FoodNotRecognizedResponse,
    IngredientCandidateSelection,
    IngredientVerification,
    IngredientVerificationItem,
    MealAnalysisCandidate,
    MealAnalysisComponent,
    MealAnalysisResponse,
    MealAnalysisSelection,
    PersonalRecipeMatch,
    PersonalRecipeSelection,
    RecognitionSource,
    RecognizedFood,
    RequiresFoodSelectionResponse,
    RequiresIngredientVerificationResponse,
    RequiresRecipeConfirmationResponse,
    SuggestedIngredient,
)
from nutribox_pi.ports import DeviceAuthenticationFailure, RetryableBackendFailure

COMPONENT_ID = "123e4567-e89b-12d3-a456-426614174000"
INGREDIENT_ID = "123e4567-e89b-12d3-a456-426614174001"
CANDIDATE_ID = "123e4567-e89b-12d3-a456-426614174002"
OTHER_CANDIDATE_ID = "123e4567-e89b-12d3-a456-426614174003"


class InlineExecutor:
    def __init__(self) -> None:
        self.closed = False

    def submit(
        self, function: Callable[[], MealAnalysisResponse]
    ) -> Future[MealAnalysisResponse]:
        future: Future[MealAnalysisResponse] = Future()
        try:
            future.set_result(function())
        except BaseException as exc:
            future.set_exception(exc)
        return future

    def shutdown(self, **_: object) -> None:
        self.closed = True


class _RunningFuture(Future[MealAnalysisResponse]):
    def cancel(self) -> bool:
        return False


class DeferredExecutor(InlineExecutor):
    def __init__(self) -> None:
        super().__init__()
        self.action: Callable[[], MealAnalysisResponse] | None = None
        self.future: _RunningFuture | None = None

    def submit(
        self, function: Callable[[], MealAnalysisResponse]
    ) -> Future[MealAnalysisResponse]:
        self.action = function
        self.future = _RunningFuture()
        return self.future

    def complete(self) -> None:
        assert self.action is not None and self.future is not None
        self.future.set_result(self.action())


class CredentialProvider:
    def __init__(self, token: str | None = None) -> None:
        self.token = token
        self.calls = 0
        self.revoked = False

    def get_verified_device_token(self) -> str | None:
        self.calls += 1
        return self.token

    def confirm_revocation(self) -> None:
        self.revoked = True
        self.token = None


class Backend:
    def __init__(self, response: MealAnalysisResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, tuple[object, ...], str | None]] = []
        self.failure: Exception | None = None

    def _call(
        self, name: str, *values: object, device_token: str | None = None
    ) -> MealAnalysisResponse:
        self.calls.append((name, values, device_token))
        if self.failure is not None:
            raise self.failure
        return self.response

    def health(self) -> object:
        raise AssertionError("not used")

    def analyze_meal(self, *_: object, **__: object) -> MealAnalysisResponse:
        return self.response

    def select_food_component(
        self, *values: object, device_token: str | None = None
    ) -> MealAnalysisResponse:
        return self._call("food", *values, device_token=device_token)

    def update_ingredients(
        self, *values: object, device_token: str | None = None
    ) -> MealAnalysisResponse:
        return self._call("ingredients", *values, device_token=device_token)

    def select_ingredient_candidate(
        self, *values: object, device_token: str | None = None
    ) -> MealAnalysisResponse:
        return self._call("candidate", *values, device_token=device_token)

    def use_recipe(
        self, *values: object, device_token: str | None = None
    ) -> MealAnalysisResponse:
        return self._call("use_recipe", *values, device_token=device_token)

    def review_recipe(
        self, *values: object, device_token: str | None = None
    ) -> MealAnalysisResponse:
        return self._call("review_recipe", *values, device_token=device_token)

    def analyze_component_as_new(
        self, *values: object, device_token: str | None = None
    ) -> MealAnalysisResponse:
        return self._call("analyze_new", *values, device_token=device_token)


class Sensor:
    def read_grams(self) -> float:
        return 250

    def read_celsius(self) -> float:
        return 25


def component() -> MealAnalysisComponent:
    return MealAnalysisComponent(
        component_id=COMPONENT_ID,
        recognized_name="rice",
        raw_estimated_proportion="1",
        normalized_proportion="1",
        estimated_weight_grams="250",
        weight_source="manual",
        resolution_status="pending",
        nutrition_source=None,
        resolved_reference=None,
        candidates=(MealAnalysisCandidate("rice", CANDIDATE_ID),),
        nutrition=None,
        suggested_ingredients=(
            SuggestedIngredient(
                ingredient_id=INGREDIENT_ID,
                name="rice",
                suggested_proportion="1",
                ingredient_source="suggested",
                included=True,
                weight_source="manual",
                resolution_status="pending",
                candidates=(MealAnalysisCandidate("rice", OTHER_CANDIDATE_ID),),
            ),
        ),
        recipe_matches=(PersonalRecipeMatch(7, "rice bowl", "personal"),),
    )


def response(status: AnalysisStatus) -> MealAnalysisResponse:
    types = {
        AnalysisStatus.REQUIRES_FOOD_SELECTION: RequiresFoodSelectionResponse,
        AnalysisStatus.REQUIRES_INGREDIENT_VERIFICATION: (
            RequiresIngredientVerificationResponse
        ),
        AnalysisStatus.REQUIRES_RECIPE_CONFIRMATION: RequiresRecipeConfirmationResponse,
        AnalysisStatus.FOOD_NOT_RECOGNIZED: FoodNotRecognizedResponse,
    }
    response_type = types.get(status, MealAnalysisResponse)
    return response_type(
        status=status,
        recognized_foods=(RecognizedFood("rice"),),
        recognition_source=RecognitionSource.SIMULATED,
        analysis_session_id=42,
        components=(component(),),
    )


def workflow(
    status: AnalysisStatus = AnalysisStatus.REQUIRES_FOOD_SELECTION,
    token: str | None = "verified-token",
) -> tuple[
    MealAnalysisContinuationWorkflow, Backend, CredentialProvider, InlineExecutor
]:
    backend = Backend(response(status))
    credential = CredentialProvider(token)
    controller = NutriBoxController(backend, Sensor(), Sensor(), credential)
    executor = InlineExecutor()
    flow = MealAnalysisContinuationWorkflow(controller, lambda: executor)
    flow.accept_initial_response(response(status))
    return flow, backend, credential, executor


@pytest.mark.parametrize("status", list(AnalysisStatus))
def test_every_backend_outcome_has_an_explicit_orchestration_state(
    status: AnalysisStatus,
) -> None:
    flow, *_ = workflow(status)
    assert flow.state.value == status.value


def test_food_selection_uses_current_candidate_and_verified_token() -> None:
    flow, backend, credential, _ = workflow()

    assert flow.select_food_component(MealAnalysisSelection(COMPONENT_ID, CANDIDATE_ID))
    flow.tick()

    assert backend.calls == [
        (
            "food",
            (42, MealAnalysisSelection(COMPONENT_ID, CANDIDATE_ID)),
            "verified-token",
        )
    ]
    assert credential.calls == 1


def test_illegal_or_stale_selection_is_rejected_before_http() -> None:
    flow, backend, *_ = workflow()

    with pytest.raises(ContinuationError):
        flow.select_food_component(
            MealAnalysisSelection(COMPONENT_ID, OTHER_CANDIDATE_ID)
        )
    flow.home()
    with pytest.raises(ContinuationError):
        flow.select_food_component(MealAnalysisSelection(COMPONENT_ID, CANDIDATE_ID))

    assert backend.calls == []


@pytest.mark.parametrize(
    ("status", "action", "expected"),
    [
        (
            AnalysisStatus.REQUIRES_INGREDIENT_VERIFICATION,
            lambda flow: flow.update_ingredients(
                COMPONENT_ID,
                IngredientVerification(
                    (IngredientVerificationItem("rice", True, INGREDIENT_ID),)
                ),
            ),
            "ingredients",
        ),
        (
            AnalysisStatus.REQUIRES_INGREDIENT_VERIFICATION,
            lambda flow: flow.select_ingredient_candidate(
                COMPONENT_ID,
                IngredientCandidateSelection(INGREDIENT_ID, OTHER_CANDIDATE_ID),
            ),
            "candidate",
        ),
        (
            AnalysisStatus.REQUIRES_RECIPE_CONFIRMATION,
            lambda flow: flow.use_recipe(COMPONENT_ID, PersonalRecipeSelection(7)),
            "use_recipe",
        ),
        (
            AnalysisStatus.REQUIRES_RECIPE_CONFIRMATION,
            lambda flow: flow.review_recipe(COMPONENT_ID, PersonalRecipeSelection(7)),
            "review_recipe",
        ),
        (
            AnalysisStatus.REQUIRES_RECIPE_CONFIRMATION,
            lambda flow: flow.analyze_component_as_new(COMPONENT_ID),
            "analyze_new",
        ),
    ],
)
def test_legal_typed_continuations(
    status: AnalysisStatus,
    action: Callable[[MealAnalysisContinuationWorkflow], bool],
    expected: str,
) -> None:
    flow, backend, *_ = workflow(status)
    assert action(flow)
    flow.tick()
    assert backend.calls[0][0] == expected


def test_anonymous_continuation_omits_token_and_does_not_cache_credentials() -> None:
    flow, backend, credential, _ = workflow(token=None)
    assert flow.select_food_component(MealAnalysisSelection(COMPONENT_ID, CANDIDATE_ID))
    flow.tick()
    assert backend.calls[0][2] is None
    assert credential.calls == 1
    assert "verified-token" not in repr(flow)


def test_retry_requeries_current_credential_and_replaces_response_atomically() -> None:
    flow, backend, credential, _ = workflow()
    old = flow.response
    backend.failure = RetryableBackendFailure()
    assert flow.select_food_component(MealAnalysisSelection(COMPONENT_ID, CANDIDATE_ID))
    flow.tick()
    assert flow.state is ContinuationState.RETRYABLE_ERROR
    assert flow.response is old and flow.error_message == RETRYABLE_ERROR_MESSAGE
    backend.failure = None
    backend.response = response(AnalysisStatus.REQUIRES_RECIPE_CONFIRMATION)
    credential.token = "new-token"
    assert flow.retry()
    assert flow.retry() is False
    flow.tick()
    assert flow.response is backend.response
    assert flow.state is ContinuationState.REQUIRES_RECIPE_CONFIRMATION
    assert backend.calls[-1][2] == "new-token"


@pytest.mark.parametrize(
    "failure", [DeviceAuthenticationFailure(), RetryableBackendFailure()]
)
def test_authentication_and_transient_failures_have_distinct_safe_lifecycles(
    failure: Exception,
) -> None:
    flow, backend, credential, _ = workflow()
    backend.failure = failure
    assert flow.select_food_component(MealAnalysisSelection(COMPONENT_ID, CANDIDATE_ID))
    flow.tick()
    if isinstance(failure, DeviceAuthenticationFailure):
        assert credential.revoked and flow.state is ContinuationState.REVOKED
        assert flow.response is None
    else:
        assert not credential.revoked and flow.retry_available
        assert flow.response is not None


@pytest.mark.parametrize("method", ["home", "retake", "cancel", "close"])
def test_lifecycle_actions_clear_owned_session_state(method: str) -> None:
    flow, _, _, executor = workflow()
    getattr(flow, method)()
    assert flow.response is None and not flow.retry_available
    if method == "close":
        assert executor.closed


def test_new_initial_response_replaces_old_response_without_data_leakage() -> None:
    flow, *_ = workflow()
    old = flow.response
    fresh = replace(response(AnalysisStatus.FOOD_NOT_RECOGNIZED), components=None)
    flow.accept_initial_response(fresh)
    assert flow.response is not old
    assert flow.response is not None
    assert flow.response.status is AnalysisStatus.FOOD_NOT_RECOGNIZED
    assert flow.response.components is None
    assert flow.response.analysis_session_id is None


@pytest.mark.parametrize("clear", ["home", "revoke"])
def test_stale_completion_cannot_restore_a_cleared_session(clear: str) -> None:
    backend = Backend(response(AnalysisStatus.REQUIRES_RECIPE_CONFIRMATION))
    controller = NutriBoxController(backend, Sensor(), Sensor(), CredentialProvider())
    executor = DeferredExecutor()
    flow = MealAnalysisContinuationWorkflow(controller, lambda: executor)
    flow.accept_initial_response(response(AnalysisStatus.REQUIRES_FOOD_SELECTION))
    assert flow.select_food_component(MealAnalysisSelection(COMPONENT_ID, CANDIDATE_ID))
    getattr(flow, clear)()
    executor.complete()
    flow.tick()
    expected = (
        ContinuationState.REVOKED if clear == "revoke" else ContinuationState.IDLE
    )
    assert flow.state is expected and flow.response is None
