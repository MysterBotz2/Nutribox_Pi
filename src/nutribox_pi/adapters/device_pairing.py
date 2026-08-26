"""HTTP boundary for the limited PI-2B device-pairing contract."""

from __future__ import annotations

import re
from typing import Any

import requests

from nutribox_pi.models import (
    DeviceIdentity,
    PairingSession,
    PairingStatus,
    PairingStatusResponse,
)
from nutribox_pi.validation import validate_api_base_url, validate_timeout

PAIRING_NOT_FOUND = "Pairing session was not found."
PAIRING_UNAVAILABLE = "Device pairing is not configured."
DEVICE_AUTH_FAILED = "Device authentication failed."
PAIRING_FAILED = "Device pairing is unavailable."


class PairingError(RuntimeError):
    """A fixed, UI-safe pairing failure."""


class DevicePairingClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 10.0,
        *,
        session: requests.Session | None = None,
    ) -> None:
        try:
            self._base_url = validate_api_base_url(base_url)
            self._timeout = validate_timeout(timeout_seconds)
        except ValueError as exc:
            raise PairingError(PAIRING_FAILED) from exc
        self._session = session or requests.Session()

    def start(self, device_name: str) -> PairingSession:
        payload = self._json(
            "POST", "/api/device-pairing/start", json={"device_name": device_name}
        )
        try:
            session_id, code, token, expires = (
                payload["session_id"],
                payload["pairing_code"],
                payload["device_token"],
                payload["expires_at"],
            )
        except KeyError as exc:
            raise PairingError(PAIRING_FAILED) from exc
        if (
            not all(
                isinstance(value, str) and value
                for value in (session_id, code, token, expires)
            )
            or re.fullmatch(r"[0-9]{6}", code) is None
        ):
            raise PairingError(PAIRING_FAILED)
        return PairingSession(session_id, code, token, expires)

    def status(self, session_id: str, device_token: str) -> PairingStatusResponse:
        payload = self._json(
            "POST",
            "/api/device-pairing/status",
            json={"session_id": session_id, "device_token": device_token},
        )
        try:
            status = PairingStatus(payload["status"])
            device_id = payload["device_id"]
        except (KeyError, ValueError) as exc:
            raise PairingError(PAIRING_FAILED) from exc
        if not (device_id is None or isinstance(device_id, int)) or (
            status is PairingStatus.PAIRED
        ) != isinstance(device_id, int):
            raise PairingError(PAIRING_FAILED)
        return PairingStatusResponse(status, device_id)

    def device_me(self, device_token: str) -> DeviceIdentity:
        payload = self._json(
            "GET", "/api/device/me", headers={"X-Device-Token": device_token}
        )
        try:
            values = (
                payload["id"],
                payload["name"],
                payload["device_type"],
                payload["paired_at"],
                payload["last_seen_at"],
            )
        except KeyError as exc:
            raise PairingError(PAIRING_FAILED) from exc
        if (
            not isinstance(values[0], int)
            or not all(isinstance(value, str) and value for value in values[1:4])
            or not (values[4] is None or isinstance(values[4], str))
        ):
            raise PairingError(PAIRING_FAILED)
        return DeviceIdentity(*values)

    def _json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self._session.request(
                method, f"{self._base_url}{path}", timeout=self._timeout, **kwargs
            )
        except requests.RequestException as exc:
            raise PairingError(PAIRING_FAILED) from exc
        mappings = {
            404: PAIRING_NOT_FOUND,
            503: PAIRING_UNAVAILABLE,
            401: DEVICE_AUTH_FAILED,
        }
        if response.status_code in mappings:
            raise PairingError(mappings[response.status_code])
        if not 200 <= response.status_code < 300:
            raise PairingError(PAIRING_FAILED)
        try:
            payload = response.json()
        except (ValueError, requests.RequestException) as exc:
            raise PairingError(PAIRING_FAILED) from exc
        if not isinstance(payload, dict):
            raise PairingError(PAIRING_FAILED)
        return payload
