"""HTTP adapter for the two known v1 backend endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

from nutribox_pi.models import AnalysisResult, AnalysisStatus, HealthResult
from nutribox_pi.validation import (
    validate_api_base_url,
    validate_timeout,
    validate_weight,
)


class BackendError(RuntimeError):
    """Raised when the v1 backend cannot provide a valid response."""


class V1BackendClient:
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
            raise BackendError(str(exc)) from exc
        self._session = session or requests.Session()

    def health(self) -> HealthResult:
        self._request("GET", "/api/health")
        return HealthResult(healthy=True, payload={})

    def analyze_meal(self, image_path: Path, weight_grams: float) -> AnalysisResult:
        try:
            weight_grams = validate_weight(weight_grams)
        except ValueError as exc:
            raise BackendError(str(exc)) from exc

        filename = image_path.name
        if "\r" in filename or "\n" in filename:
            raise BackendError("image filename must not contain CR or LF characters")

        try:
            with image_path.open("rb") as image:
                response = self._request(
                    "POST",
                    "/api/meals/analyze",
                    files={"file": (filename, image)},
                    data={"weight_grams": f"{weight_grams:g}"},
                )
        except OSError as exc:
            raise BackendError(f"cannot read image file: {image_path}") from exc

        payload = self._json_object(response)
        try:
            status = AnalysisStatus(payload["status"])
        except (KeyError, ValueError) as exc:
            message = "backend returned an unsupported analysis status"
            raise BackendError(message) from exc
        return AnalysisResult(status=status, payload=payload)

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        try:
            response = self._session.request(
                method,
                f"{self._base_url}{path}",
                timeout=self._timeout,
                **kwargs,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise BackendError("backend request failed") from exc
        if not 200 <= response.status_code < 300:
            raise BackendError(f"backend returned HTTP {response.status_code}")
        return response

    @staticmethod
    def _json_object(response: requests.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except requests.exceptions.JSONDecodeError as exc:
            raise BackendError("backend returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise BackendError("backend JSON response must be an object")
        return payload
