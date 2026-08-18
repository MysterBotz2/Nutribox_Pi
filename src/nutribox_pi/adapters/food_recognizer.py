"""HTTP adapter for the verified food-recognition endpoint."""

from __future__ import annotations

from pathlib import Path

import requests

from nutribox_pi.models import (
    FoodRecognitionResult,
    RecognitionSource,
    RecognizedFood,
)
from nutribox_pi.validation import validate_api_base_url, validate_timeout


class FoodRecognitionError(RuntimeError):
    """Raised when food recognition cannot return a valid safe result."""


class HttpFoodRecognizer:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 10.0,
        session: requests.Session | None = None,
    ) -> None:
        try:
            self._base_url = validate_api_base_url(base_url)
            self._timeout = validate_timeout(timeout_seconds)
        except ValueError as exc:
            raise FoodRecognitionError(
                "food recognition configuration is invalid"
            ) from exc
        self._session = session or requests.Session()

    def recognize_food(self, image_path: Path) -> FoodRecognitionResult:
        filename = image_path.name
        if not filename or "\r" in filename or "\n" in filename:
            raise FoodRecognitionError("food recognition image is invalid")
        try:
            with image_path.open("rb") as image:
                response = self._session.request(
                    "POST",
                    f"{self._base_url}/api/ai/recognize-food",
                    timeout=self._timeout,
                    files={"file": (filename, image)},
                )
                response.raise_for_status()
        except OSError as exc:
            raise FoodRecognitionError("food recognition image is unavailable") from exc
        except requests.RequestException as exc:
            raise FoodRecognitionError("food recognition request failed") from exc
        if not 200 <= response.status_code < 300:
            raise FoodRecognitionError("food recognition request failed")
        return self._parse_response(response)

    @staticmethod
    def _parse_response(response: requests.Response) -> FoodRecognitionResult:
        try:
            payload = response.json()
        except (requests.exceptions.JSONDecodeError, ValueError) as exc:
            raise FoodRecognitionError("food recognition response is invalid") from exc
        if not isinstance(payload, dict):
            raise FoodRecognitionError("food recognition response is invalid")
        foods = payload.get("foods")
        source = payload.get("source")
        if not isinstance(foods, list) or len(foods) > 10:
            raise FoodRecognitionError("food recognition response is invalid")
        recognized: list[RecognizedFood] = []
        for food in foods:
            if not isinstance(food, dict) or not isinstance(food.get("name"), str):
                raise FoodRecognitionError("food recognition response is invalid")
            name = food["name"].strip()
            if not 1 <= len(name) <= 120:
                raise FoodRecognitionError("food recognition response is invalid")
            recognized.append(RecognizedFood(name))
        try:
            recognized_source = RecognitionSource(source)
        except (TypeError, ValueError) as exc:
            raise FoodRecognitionError("food recognition response is invalid") from exc
        return FoodRecognitionResult(tuple(recognized), recognized_source)
