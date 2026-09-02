import math
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import requests

from nutribox_pi.adapters.v1_backend import (
    BackendError,
    MalformedBackendResponseError,
    V1BackendClient,
)
from nutribox_pi.continuation import (
    ContinuationState,
    MealAnalysisContinuationWorkflow,
)
from nutribox_pi.models import (
    AnalysisStatus,
    CalculatedResponse,
    FoodNotRecognizedResponse,
    MealAnalysisResponse,
    MealAnalysisSelection,
    NutritionReferenceNotFoundResponse,
    RequiresFoodSelectionResponse,
)


class FakeResponse:
    def __init__(
        self,
        payload: object = None,
        error: requests.RequestException | None = None,
        status_code: int = 200,
    ) -> None:
        self.payload = payload
        self.error = error
        self.status_code = status_code
        self.json_called = False

    def raise_for_status(self) -> None:
        if self.error:
            raise self.error

    def json(self) -> object:
        self.json_called = True
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeSession:
    def __init__(
        self,
        response: FakeResponse | None = None,
        error: requests.RequestException | None = None,
    ) -> None:
        self.response = response or FakeResponse()
        self.error = error
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((method, url, kwargs))
        if self.error:
            raise self.error
        return self.response


def test_health_accepts_any_successful_body_without_parsing() -> None:
    response = FakeResponse(payload=AssertionError("health body was parsed"))
    session = FakeSession(response)

    result = V1BackendClient(
        "https://backend.test/",
        2,
        session=session,  # type: ignore[arg-type]
    ).health()

    assert result.healthy is True
    assert result.payload == {}
    assert response.json_called is False
    assert session.calls == [("GET", "https://backend.test/api/health", {"timeout": 2})]


def _payload(status: AnalysisStatus) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": status.value,
        "recognized_foods": [{"name": "Rice"}],
        "recognition_source": "simulated",
    }
    if status is AnalysisStatus.CALCULATED:
        payload["nutrition"] = {
            "calories": "123.4",
            "protein_g": "5.0",
            "carbohydrates_g": "20.1",
            "fat_g": "0",
            "fiber_g": "2",
            "sodium_mg": None,
        }
        payload["weight_grams"] = "123.5"
    return payload


def _portion_nutrition() -> dict[str, str]:
    return {
        "calories": "100",
        "protein_g": "2",
        "carbohydrates_g": "20",
        "fat_g": "1",
        "fiber_g": "3",
    }


def test_leftover_routes_use_only_device_header_and_exact_scan_body() -> None:
    scan = {
        "id": 8,
        "meal_id": 3,
        "analysis_session_id": 9,
        "original_weight_grams": "120",
        "remaining_weight_grams": "40",
        "consumed_weight_grams": "80",
        "consumed_portion_percentage": "66.7",
        "remaining_nutrition": _portion_nutrition(),
        "estimated_consumed_nutrition": _portion_nutrition(),
        "comparison_warnings": [],
        "created_at": "2026-09-02T00:00:00Z",
    }
    session = FakeSession(FakeResponse(scan, status_code=201))
    client = V1BackendClient("https://backend.test", 2, session=session)  # type: ignore[arg-type]

    result = client.create_leftover_scan(3, 9, "verified-device-token")

    assert result.remaining_weight_grams == "40"
    assert session.calls == [
        (
            "POST",
            "https://backend.test/api/meals/3/leftover-scans",
            {
                "timeout": 2,
                "json": {"analysis_session_id": 9},
                "headers": {"X-Device-Token": "verified-device-token"},
            },
        )
    ]


def test_saved_meal_list_requires_verified_credential_before_http() -> None:
    session = FakeSession()
    client = V1BackendClient("https://backend.test", 2, session=session)  # type: ignore[arg-type]
    with pytest.raises(BackendError, match="verified device credential"):
        client.list_saved_meals(4, 0)
    assert session.calls == []


@pytest.mark.parametrize(
    ("status", "response_type"),
    [
        (AnalysisStatus.CALCULATED, CalculatedResponse),
        (AnalysisStatus.FOOD_NOT_RECOGNIZED, FoodNotRecognizedResponse),
        (AnalysisStatus.REQUIRES_FOOD_SELECTION, RequiresFoodSelectionResponse),
        (
            AnalysisStatus.NUTRITION_REFERENCE_NOT_FOUND,
            NutritionReferenceNotFoundResponse,
        ),
    ],
)
def test_analyze_accepts_exactly_documented_statuses(
    tmp_path: Path, status: AnalysisStatus, response_type: type[object]
) -> None:
    session = FakeSession(FakeResponse(_payload(status)))
    image = tmp_path / "meal.jpg"
    image.write_bytes(b"jpeg-data")

    result = V1BackendClient(
        "https://backend.test",
        2,
        session=session,  # type: ignore[arg-type]
    ).analyze_meal(image, 123.5)

    method, url, kwargs = session.calls[0]
    assert result.status is status
    assert isinstance(result, response_type)
    if status is AnalysisStatus.CALCULATED:
        assert isinstance(result, CalculatedResponse)
        assert result.nutrition.values["sodium_mg"] is None
    assert method == "POST"
    assert url == "https://backend.test/api/meals/analyze"
    assert kwargs["data"] == {"weight_grams": "123.5"}
    assert set(kwargs["files"]) == {"file"}
    filename, file_object, mime_type = kwargs["files"]["file"]
    assert filename == "meal.jpg"
    assert mime_type == "image/jpeg"
    assert file_object.closed is True
    assert "headers" not in kwargs
    assert "user_id" not in repr(kwargs)
    assert "confidence" not in repr(kwargs)


@pytest.mark.parametrize("status", ["unknown", "", None])
def test_analyze_rejects_undocumented_status(tmp_path: Path, status: object) -> None:
    session = FakeSession(
        FakeResponse(
            {
                "status": status,
                "recognized_foods": ["Rice"],
                "recognition_source": "simulated",
            }
        )
    )
    image = tmp_path / "meal.jpg"
    image.write_bytes(b"image")

    with pytest.raises(BackendError, match="invalid analysis response"):
        V1BackendClient(
            "https://backend.test",
            2,
            session=session,  # type: ignore[arg-type]
        ).analyze_meal(image, 10)


@pytest.mark.parametrize("weight", [-1, 5001, math.inf, math.nan])
def test_backend_rejects_invalid_weight(tmp_path: Path, weight: float) -> None:
    image = tmp_path / "meal.jpg"
    image.write_bytes(b"image")

    with pytest.raises(BackendError, match="weight"):
        V1BackendClient("https://backend.test").analyze_meal(image, weight)


def test_analyze_normalizes_missing_image_error(tmp_path: Path) -> None:
    with pytest.raises(BackendError, match="cannot read image"):
        V1BackendClient("https://backend.test").analyze_meal(
            tmp_path / "missing.jpg", 10
        )


def test_analyze_rejects_crlf_in_basename(tmp_path: Path) -> None:
    image = tmp_path / "meal\nname.jpg"
    image.write_bytes(b"image")

    with pytest.raises(BackendError, match="CR or LF"):
        V1BackendClient("https://backend.test").analyze_meal(image, 10)


def test_request_error_is_normalized() -> None:
    session = FakeSession(error=requests.Timeout("late"))

    with pytest.raises(BackendError, match="request failed"):
        V1BackendClient(
            "https://backend.test",
            session=session,  # type: ignore[arg-type]
        ).health()


def test_health_rejects_non_2xx_response() -> None:
    session = FakeSession(FakeResponse(status_code=302))

    with pytest.raises(BackendError, match="HTTP 302"):
        V1BackendClient(
            "https://backend.test",
            session=session,  # type: ignore[arg-type]
        ).health()


def test_invalid_analysis_json_is_normalized(tmp_path: Path) -> None:
    decode_error = requests.exceptions.JSONDecodeError("bad", "x", 0)
    session = FakeSession(FakeResponse(decode_error))
    image = tmp_path / "meal.jpg"
    image.write_bytes(b"image")

    with pytest.raises(BackendError, match="invalid JSON"):
        V1BackendClient(
            "https://backend.test",
            session=session,  # type: ignore[arg-type]
        ).analyze_meal(image, 10)


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "calculated"},
        {
            "status": "calculated",
            "recognized_foods": ["Rice"],
            "recognition_source": "mock",
            "nutrition": {
                "calories": "1",
                "protein": "1",
                "carbohydrates": "1",
                "fat": "1",
                "fiber": "1",
            },
        },
        {
            "status": "calculated",
            "recognized_foods": ["Rice"],
            "recognition_source": "gemini",
            "nutrition": {
                "calories": 1,
                "protein": "1",
                "carbohydrates": "1",
                "fat": "1",
                "fiber": "1",
            },
        },
    ],
)
def test_analyze_rejects_invalid_typed_response(
    tmp_path: Path, payload: dict[str, object]
) -> None:
    image = tmp_path / "meal.jpg"
    image.write_bytes(b"jpeg")
    with pytest.raises(BackendError, match="invalid analysis response"):
        V1BackendClient(
            "https://backend.test",
            session=FakeSession(FakeResponse(payload)),  # type: ignore[arg-type]
        ).analyze_meal(image, 10)


def test_nutrition_reference_not_found_accepts_recognized_food_object(
    tmp_path: Path,
) -> None:
    payload = {
        "recognized_foods": [{"name": "chicken adobo"}],
        "recognition_source": "simulated",
        "status": "nutrition_reference_not_found",
    }
    image = tmp_path / "meal.jpg"
    image.write_bytes(b"jpeg")

    result = V1BackendClient(
        "https://backend.test",
        session=FakeSession(FakeResponse(payload)),  # type: ignore[arg-type]
    ).analyze_meal(image, 250)

    assert isinstance(result, NutritionReferenceNotFoundResponse)
    assert result.recognized_foods[0].name == "chicken adobo"
    assert result.recognition_source.value == "simulated"


_COMPONENT_ID = "123e4567-e89b-12d3-a456-426614174000"
_CANDIDATE_ID = "123e4567-e89b-12d3-a456-426614174001"


def _current_calculated_selection_payload() -> dict[str, object]:
    """Authoritative response shape from POST .../selections."""
    nutrition = {
        "calories": "100.000",
        "protein_g": "10.000",
        "carbohydrates_g": "20.000",
        "fat_g": "3.000",
        "fiber_g": "2.000",
        "saturated_fat_g": "1.000",
        "sugars_g": "4.000",
        "sodium_mg": "5.000",
        "cholesterol_mg": "6.000",
        "omega_3_g": "0.100",
        "omega_6_g": "0.200",
        "calcium_mg": "7.000",
        "potassium_mg": "8.000",
        "zinc_mg": "9.000",
        "iron_mg": "10.000",
        "magnesium_mg": "11.000",
        "energy_kj": "418.400",
        "phosphorus_mg": "12.000",
        "vitamin_b6_mg": "13.000",
        "niacin_mg": "14.000",
        "vitamin_a_mcg_rae": "15.000",
        "vitamin_b12_mcg": "16.000",
        "vitamin_c_mg": "17.000",
        "vitamin_d_mcg": "18.000",
        "folate_mcg_dfe": "19.000",
    }
    return {
        "status": "calculated",
        "recognized_foods": [{"name": "selected food"}],
        "recognition_source": "session",
        "analysis_session_id": 12,
        "analysis_session_expires_at": "2030-01-02T03:04:05Z",
        "measured_weight_grams": "250.000",
        "components": [
            {
                "component_id": _COMPONENT_ID,
                "recognized_name": "selected food",
                "raw_estimated_proportion": "1.000",
                "normalized_proportion": "1.000",
                "estimated_weight_grams": "250.000",
                "weight_source": "ai_estimate",
                "resolution_status": "resolved",
                "nutrition_source": "local_database",
                "resolved_reference": "food:42",
                "candidates": [],
                "nutrition": dict(nutrition),
                "composite_estimation": False,
                "suggested_ingredients": [],
                "recipe_matches": [],
            }
        ],
        "weight_grams": "250.000",
        "weight_source": "ai_estimate",
        "food": {"id": 42, "name": "selected food"},
        "nutrition": nutrition,
    }


def test_selection_calculated_response_parses_current_authoritative_schema() -> None:
    session = FakeSession(FakeResponse(_current_calculated_selection_payload()))
    client = V1BackendClient(
        "https://backend.test",
        session=session,  # type: ignore[arg-type]
    )

    result = client.select_food_component(
        12,
        MealAnalysisSelection(_COMPONENT_ID, _CANDIDATE_ID),
        "verified-device-token",
    )

    assert isinstance(result, CalculatedResponse)
    assert isinstance(result, MealAnalysisResponse)
    assert result.recognition_source.value == "session"
    assert result.weight_grams == "250.000"
    assert (
        result.nutrition.values == _current_calculated_selection_payload()["nutrition"]
    )
    assert result.nutrition.values["energy_kj"] == "418.400"
    assert result.nutrition.values["phosphorus_mg"] == "12.000"
    assert result.nutrition.values["vitamin_b6_mg"] == "13.000"
    assert result.nutrition.values["niacin_mg"] == "14.000"
    assert result.components is not None
    assert result.components[0].nutrition is not None
    assert result.components[0].nutrition.values == result.nutrition.values
    assert session.calls[0][1].endswith("/api/meals/analysis-sessions/12/selections")

    workflow = MealAnalysisContinuationWorkflow(object())  # type: ignore[arg-type]
    try:
        workflow.accept_initial_response(result)
        assert workflow.state is ContinuationState.CALCULATED
    finally:
        workflow.close()


@pytest.mark.parametrize(
    "field",
    [
        "energy_kj",
        "phosphorus_mg",
        "vitamin_b6_mg",
        "niacin_mg",
        "sodium_mg",
        "vitamin_a_mcg_rae",
    ],
)
def test_calculated_selection_accepts_nullable_expanded_nutrients(field: str) -> None:
    payload = _current_calculated_selection_payload()
    payload["nutrition"][field] = None  # type: ignore[index]
    payload["components"][0]["nutrition"][field] = None  # type: ignore[index]

    result = V1BackendClient._analysis_response(payload)

    assert isinstance(result, CalculatedResponse)
    assert result.nutrition.values[field] is None


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload["nutrition"].pop("fiber_g"),
        lambda payload: payload["nutrition"].__setitem__("energy_kj", 418.4),
        lambda payload: payload["nutrition"].__setitem__("phosphorus_mg", "-1"),
        lambda payload: payload["nutrition"].__setitem__("vitamin_b6_mg", "NaN"),
        lambda payload: payload["nutrition"].__setitem__("sodium", "5"),
        lambda payload: payload.pop("weight_grams"),
    ],
)
def test_calculated_selection_rejects_invalid_or_legacy_nutrition(
    mutation: Any,
) -> None:
    payload = deepcopy(_current_calculated_selection_payload())
    mutation(payload)

    with pytest.raises(MalformedBackendResponseError) as error:
        V1BackendClient._analysis_response(payload)

    assert str(error.value) == "backend returned an invalid analysis response"
    assert "selected food" not in str(error.value)
    assert "verified-device-token" not in str(error.value)


@pytest.mark.parametrize("status", list(AnalysisStatus))
def test_all_authoritative_analysis_outcomes_parse_for_continuations(
    status: AnalysisStatus,
) -> None:
    payload: dict[str, object]
    if status is AnalysisStatus.CALCULATED:
        payload = _current_calculated_selection_payload()
    else:
        payload = {
            "status": status.value,
            "recognized_foods": [{"name": "selected food"}],
            "recognition_source": "session",
            "analysis_session_id": 12,
            "analysis_session_expires_at": "2030-01-02T03:04:05Z",
            "measured_weight_grams": "250.000",
            "components": [],
        }

    result = V1BackendClient._analysis_response(payload)

    assert result.status is status
