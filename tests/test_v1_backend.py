import math
from pathlib import Path
from typing import Any

import pytest
import requests

from nutribox_pi.adapters.v1_backend import BackendError, V1BackendClient
from nutribox_pi.models import (
    AnalysisStatus,
    CalculatedResponse,
    FoodNotRecognizedResponse,
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
        "https://backend.test/", 2, session=session  # type: ignore[arg-type]
    ).health()

    assert result.healthy is True
    assert result.payload == {}
    assert response.json_called is False
    assert session.calls == [
        ("GET", "https://backend.test/api/health", {"timeout": 2})
    ]


def _payload(status: AnalysisStatus) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": status.value,
        "recognized_foods": ["Rice"],
        "recognition_source": "simulated",
    }
    if status is AnalysisStatus.CALCULATED:
        payload["nutrition"] = {
            "calories": "123.4",
            "protein": "5.0",
            "carbohydrates": "20.1",
            "fat": None,
            "fiber": "2",
            "sodium": None,
        }
    return payload


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
        "https://backend.test", 2, session=session  # type: ignore[arg-type]
    ).analyze_meal(image, 123.5)

    method, url, kwargs = session.calls[0]
    assert result.status is status
    assert isinstance(result, response_type)
    if status is AnalysisStatus.CALCULATED:
        assert isinstance(result, CalculatedResponse)
        assert result.nutrition.values["sodium"] is None
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
def test_analyze_rejects_undocumented_status(
    tmp_path: Path, status: object
) -> None:
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
            "https://backend.test", 2, session=session  # type: ignore[arg-type]
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
            "https://backend.test", session=session  # type: ignore[arg-type]
        ).health()


def test_health_rejects_non_2xx_response() -> None:
    session = FakeSession(FakeResponse(status_code=302))

    with pytest.raises(BackendError, match="HTTP 302"):
        V1BackendClient(
            "https://backend.test", session=session  # type: ignore[arg-type]
        ).health()


def test_invalid_analysis_json_is_normalized(tmp_path: Path) -> None:
    decode_error = requests.exceptions.JSONDecodeError("bad", "x", 0)
    session = FakeSession(FakeResponse(decode_error))
    image = tmp_path / "meal.jpg"
    image.write_bytes(b"image")

    with pytest.raises(BackendError, match="invalid JSON"):
        V1BackendClient(
            "https://backend.test", session=session  # type: ignore[arg-type]
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
