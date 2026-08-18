from pathlib import Path
from typing import Any

import pytest
import requests

from nutribox_pi.adapters.food_recognizer import (
    FoodRecognitionError,
    HttpFoodRecognizer,
)
from nutribox_pi.models import RecognitionSource


class FakeResponse:
    def __init__(
        self,
        payload: object,
        *,
        status_code: int = 200,
        error: requests.RequestException | None = None,
    ) -> None:
        self.payload = payload
        self.status_code = status_code
        self.error = error

    def raise_for_status(self) -> None:
        if self.error is not None:
            raise self.error

    def json(self) -> object:
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((method, url, kwargs))
        return self.response


def _image(tmp_path: Path) -> Path:
    image = tmp_path / "meal.jpg"
    image.write_bytes(b"jpeg")
    return image


@pytest.mark.parametrize(
    ("source", "names"),
    [
        ("simulated", ["Rice"]),
        ("gemini", ["Rice", "Vegetables"]),
        ("simulated", []),
        ("gemini", [f"Food {index}" for index in range(10)]),
    ],
)
def test_recognizer_validates_documented_response_and_sends_one_file(
    tmp_path: Path, source: str, names: list[str]
) -> None:
    session = FakeSession(
        FakeResponse({"foods": [{"name": name} for name in names], "source": source})
    )
    result = HttpFoodRecognizer(
        "https://backend.test", 2, session=session  # type: ignore[arg-type]
    ).recognize_food(_image(tmp_path))

    assert [food.name for food in result.foods] == names
    assert result.source is RecognitionSource(source)
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url == "https://backend.test/api/ai/recognize-food"
    assert kwargs["timeout"] == 2
    assert set(kwargs) == {"timeout", "files"}
    assert set(kwargs["files"]) == {"file"}
    filename, handle = kwargs["files"]["file"]
    assert filename == "meal.jpg"
    assert handle.closed is True
    assert "weight_grams" not in repr(kwargs)
    assert "user_id" not in repr(kwargs)
    assert "confidence" not in repr(kwargs)


@pytest.mark.parametrize(
    "payload",
    [
        {"foods": [{"name": "x"}] * 11, "source": "gemini"},
        {"foods": [{}], "source": "gemini"},
        {"foods": [{"name": ""}], "source": "gemini"},
        {"foods": [{"name": " "}], "source": "gemini"},
        {"foods": [{"name": "x" * 121}], "source": "gemini"},
        {"foods": [{"name": "x"}], "source": "unknown"},
        {"source": "gemini"},
        [],
    ],
)
def test_recognizer_rejects_invalid_schema(tmp_path: Path, payload: object) -> None:
    session = FakeSession(FakeResponse(payload))

    with pytest.raises(FoodRecognitionError, match="response is invalid"):
        HttpFoodRecognizer(
            "https://backend.test", session=session  # type: ignore[arg-type]
        ).recognize_food(_image(tmp_path))


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse({}, status_code=500),
        FakeResponse({}, error=requests.Timeout()),
        FakeResponse(requests.exceptions.JSONDecodeError("bad", "x", 0)),
    ],
)
def test_recognizer_normalizes_http_timeout_and_json_failures(
    tmp_path: Path, response: FakeResponse
) -> None:
    session = FakeSession(response)

    with pytest.raises(FoodRecognitionError):
        HttpFoodRecognizer(
            "https://backend.test", session=session  # type: ignore[arg-type]
        ).recognize_food(_image(tmp_path))


def test_recognizer_normalizes_image_read_failure(tmp_path: Path) -> None:
    with pytest.raises(FoodRecognitionError, match="image is unavailable"):
        HttpFoodRecognizer("https://backend.test").recognize_food(
            tmp_path / "missing.jpg"
        )
