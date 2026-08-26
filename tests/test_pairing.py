from __future__ import annotations

import os
from concurrent.futures import Future
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from nutribox_pi.adapters import pygame_device_ui
from nutribox_pi.adapters.device_pairing import (
    DEVICE_AUTH_FAILED,
    PAIRING_NOT_FOUND,
    PAIRING_UNAVAILABLE,
    DevicePairingClient,
    PairingError,
)
from nutribox_pi.device_ui import UIAction, UIScreen, buttons_for
from nutribox_pi.models import DeviceIdentity, PairingSession, PairingStatus
from nutribox_pi.pairing import (
    REVOKED_MESSAGE,
    VERIFY_INTERVAL_SECONDS,
    CredentialError,
    DeviceCredentialStore,
    PairingState,
    PairingWorkflow,
    format_countdown,
)


class Response:
    def __init__(self, status: int, payload: object) -> None:
        self.status_code, self.payload = status, payload

    def json(self) -> object:
        return self.payload


class Session:
    def __init__(self, response: Response) -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def request(self, method: str, url: str, **kwargs: object) -> Response:
        self.calls.append((method, url, kwargs))
        return self.response


def test_pairing_requests_and_strict_statuses() -> None:
    session = Session(
        Response(
            201,
            {
                "session_id": "s",
                "pairing_code": "123456",
                "device_token": "secret",
                "expires_at": "2026-01-01T00:00:00Z",
            },
        )
    )
    client = DevicePairingClient("https://backend.test", session=session)  # type: ignore[arg-type]
    result = client.start("NutriBox Pi")
    assert result.pairing_code == "123456"
    assert session.calls == [
        (
            "POST",
            "https://backend.test/api/device-pairing/start",
            {"timeout": 10.0, "json": {"device_name": "NutriBox Pi"}},
        )
    ]
    for value in ("pending", "expired", "paired"):
        session.response = Response(
            200, {"status": value, "device_id": 1 if value == "paired" else None}
        )
        assert client.status("s", "secret").status is PairingStatus(value)
    session.response = Response(200, {"status": "unknown", "device_id": None})
    with pytest.raises(PairingError):
        client.status("s", "secret")


@pytest.mark.parametrize(
    "status,message",
    [(404, PAIRING_NOT_FOUND), (503, PAIRING_UNAVAILABLE), (401, DEVICE_AUTH_FAILED)],
)
def test_pairing_http_errors_are_safe(status: int, message: str) -> None:
    client = DevicePairingClient(
        "https://backend.test", session=Session(Response(status, {}))
    )  # type: ignore[arg-type]
    with pytest.raises(PairingError, match=message) as error:
        client.device_me("secret-token")
    assert "secret-token" not in str(error.value)


def test_private_atomic_credential_store_and_symlink_rejection(tmp_path: Path) -> None:
    store = DeviceCredentialStore(tmp_path)
    store.save("secret")
    assert store.load() == "secret"
    if os.name == "posix":
        assert store.path.stat().st_mode & 0o777 == 0o600
        assert store.path.parent.stat().st_mode & 0o777 == 0o700
    store.path.unlink()
    store.path.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(CredentialError):
        store.save("secret")


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (300, "Expires in 5:00"),
        (61, "Expires in 1:01"),
        (1, "Expires in 0:01"),
        (0, "Expires in 0:00"),
    ],
)
def test_countdown_formatting(seconds: int, expected: str) -> None:
    assert format_countdown(seconds) == expected


class PairingFake:
    def start(self, name: str) -> PairingSession:
        raise AssertionError

    def status(self, session: str, token: str):  # type: ignore[no-untyped-def]
        raise AssertionError

    def device_me(self, token: str) -> DeviceIdentity:
        raise AssertionError


class ManualExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[object, tuple[object, ...], Future[object]]] = []
        self.closed = False

    def submit(self, function, *args):  # type: ignore[no-untyped-def]
        future: Future[object] = Future()
        self.calls.append((function, args, future))
        return future

    def shutdown(self, **kwargs: object) -> None:
        self.closed = True


def _future(value: object) -> Future[object]:
    future: Future[object] = Future()
    future.set_result(value)
    return future


def _session() -> PairingSession:
    return PairingSession("session", "123456", "token", "2030-01-01T00:05:00Z")


def test_cancelled_start_and_late_result_cannot_restore_pairing(tmp_path: Path) -> None:
    workflow = PairingWorkflow(PairingFake(), DeviceCredentialStore(tmp_path))
    workflow.state = PairingState.REQUESTING
    late = _future(_session())
    workflow._future = late
    workflow.cancel()
    workflow.tick()
    assert workflow.state is PairingState.UNPAIRED
    assert workflow.code is workflow.expires_at is None
    assert workflow._session is None


def test_expiry_stops_polling_and_reports_zero(tmp_path: Path) -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    workflow = PairingWorkflow(
        PairingFake(),
        DeviceCredentialStore(tmp_path),
        clock=lambda: now,
        monotonic=lambda: 99,
    )
    workflow.state = PairingState.WAITING
    workflow.expires_at = now
    workflow._session = _session()
    workflow.tick()
    assert workflow.state is PairingState.EXPIRED
    assert format_countdown(workflow.remaining_seconds()) == "Expires in 0:00"
    assert workflow._future is None


def test_verified_home_preserves_credential_and_shutdown_clears_pending(
    tmp_path: Path,
) -> None:
    store = DeviceCredentialStore(tmp_path)
    store.save("saved")
    workflow = PairingWorkflow(PairingFake(), store)
    workflow.state = PairingState.PAIRED
    workflow.code = "123456"
    workflow.cancel()
    assert store.load() == "saved"
    assert workflow.state is PairingState.UNPAIRED
    assert workflow.code is None
    workflow.close()


def test_startup_verification_and_revocation(tmp_path: Path) -> None:
    store = DeviceCredentialStore(tmp_path)
    store.save("stored-token")
    executor = ManualExecutor()
    workflow = PairingWorkflow(
        PairingFake(),
        store,
        executor_factory=lambda: executor,  # type: ignore[arg-type]
    )
    workflow.startup_verify()
    assert executor.calls[0][1] == ("stored-token",)
    executor.calls[0][2].set_result(DeviceIdentity(1, "Kitchen Pi", "pi", "now", None))
    workflow.tick()
    assert workflow.state is PairingState.PAIRED and store.load() == "stored-token"
    executor = ManualExecutor()
    revoked = PairingWorkflow(
        PairingFake(),
        store,
        executor_factory=lambda: executor,  # type: ignore[arg-type]
    )
    revoked.startup_verify()
    executor.calls[0][2].set_exception(PairingError(DEVICE_AUTH_FAILED))
    revoked.tick()
    assert revoked.state is PairingState.UNPAIRED and store.load() is None


def test_ui_home_cancels_active_poll_and_late_result(tmp_path: Path) -> None:
    executor = ManualExecutor()
    pairing = PairingWorkflow(
        PairingFake(),
        DeviceCredentialStore(tmp_path),
        executor_factory=lambda: executor,  # type: ignore[arg-type]
    )
    pairing.state, pairing.code, pairing.expires_at, pairing._session = (
        PairingState.WAITING,
        "123456",
        datetime(2030, 1, 1, tzinfo=UTC),
        _session(),
    )
    pairing._future = _future(PairingStatus.PAIRED)
    ui = SimpleNamespace(screen=UIScreen.PAIR_WAITING, pairing=pairing)
    ui.cancel_pairing = lambda: (pairing.cancel(), setattr(ui, "screen", UIScreen.HOME))
    assert (
        pygame_device_ui._apply_action(object(), object(), object(), ui, UIAction.HOME)
        is None
    )
    pairing.tick()
    assert ui.screen is UIScreen.HOME and pairing.state is PairingState.UNPAIRED
    assert pairing.code is pairing.expires_at is pairing._session is None


def test_pairing_transition_renders_only_verified_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor = ManualExecutor()
    pairing = PairingWorkflow(
        PairingFake(),
        DeviceCredentialStore(tmp_path),
        executor_factory=lambda: executor,  # type: ignore[arg-type]
    )
    pairing.start()
    executor.calls[0][2].set_result(_session())
    pairing.tick()
    assert pairing.state is PairingState.WAITING and pairing.code == "123456"
    pairing._future = _future(PairingStatus.PAIRED)
    pairing.tick()
    executor.calls[-1][2].set_result(DeviceIdentity(1, "Kitchen Pi", "pi", "now", None))
    pairing.tick()
    drawn: list[str] = []
    monkeypatch.setattr(
        pygame_device_ui, "_draw_text", lambda *args: drawn.append(args[2])
    )
    monkeypatch.setattr(pygame_device_ui, "_draw_card", lambda *args: None)
    pygame_device_ui._render_pairing(
        object(),
        object(),
        SimpleNamespace(subheading=object(), body=object(), small=object()),
        SimpleNamespace(pairing=pairing, screen=UIScreen.PAIR_PAIRED),
    )
    output = " ".join(drawn)
    assert pairing.state is PairingState.PAIRED and "Kitchen Pi" in output
    assert "session" not in output and "token" not in output


def test_verified_pairing_refuses_new_session_and_home_preserves_state(
    tmp_path: Path,
) -> None:
    store = DeviceCredentialStore(tmp_path)
    store.save("verified-token")
    executor = ManualExecutor()
    pairing = PairingWorkflow(
        PairingFake(),
        store,
        executor_factory=lambda: executor,  # type: ignore[arg-type]
    )
    pairing.state = PairingState.PAIRED
    pairing.device = DeviceIdentity(1, "Kitchen Pi", "pi", "now", None)
    assert pairing.start() is False
    assert executor.calls == []
    ui = SimpleNamespace(screen=UIScreen.PAIR_PAIRED, pairing=pairing)
    ui.cancel_pairing = lambda: pytest.fail("paired Home must not cancel")
    ui.home = lambda: setattr(ui, "screen", UIScreen.HOME)
    assert (
        pygame_device_ui._apply_action(object(), object(), object(), ui, UIAction.HOME)
        is None
    )
    assert pairing.state is PairingState.PAIRED and store.load() == "verified-token"


def test_startup_verification_refuses_new_pairing(tmp_path: Path) -> None:
    store = DeviceCredentialStore(tmp_path)
    store.save("verified-token")
    executor = ManualExecutor()
    pairing = PairingWorkflow(
        PairingFake(),
        store,
        executor_factory=lambda: executor,  # type: ignore[arg-type]
    )
    pairing.startup_verify()
    assert pairing.state is PairingState.REQUESTING
    assert pairing.start() is False and len(executor.calls) == 1


def test_live_verification_is_bounded_and_handles_revocation(tmp_path: Path) -> None:
    clock = [0.0]
    store = DeviceCredentialStore(tmp_path)
    store.save("verified-token")
    executor = ManualExecutor()
    pairing = PairingWorkflow(
        PairingFake(),
        store,
        monotonic=lambda: clock[0],
        executor_factory=lambda: executor,  # type: ignore[arg-type]
    )
    pairing.state = PairingState.PAIRED
    pairing.device = DeviceIdentity(1, "Kitchen Pi", "pi", "now", None)
    pairing._verified_token = "verified-token"
    pairing._next_verify = VERIFY_INTERVAL_SECONDS
    pairing.tick()
    assert executor.calls == []
    clock[0] = VERIFY_INTERVAL_SECONDS
    pairing.tick()
    assert len(executor.calls) == 1 and executor.calls[0][1] == ("verified-token",)
    pairing.tick()
    assert len(executor.calls) == 1
    executor.calls[0][2].set_result(
        DeviceIdentity(1, "Updated Pi", "pi", "later", None)
    )
    pairing.tick()
    assert pairing.state is PairingState.PAIRED and pairing.device.name == "Updated Pi"
    clock[0] += VERIFY_INTERVAL_SECONDS
    pairing.tick()
    executor.calls[-1][2].set_exception(PairingError(DEVICE_AUTH_FAILED))
    pairing.tick()
    assert pairing.state is PairingState.UNPAIRED and store.load() is None
    assert pairing.error_message == REVOKED_MESSAGE


def test_transient_live_verification_failure_retains_credential(tmp_path: Path) -> None:
    executor = ManualExecutor()
    store = DeviceCredentialStore(tmp_path)
    store.save("verified-token")
    pairing = PairingWorkflow(
        PairingFake(),
        store,
        monotonic=lambda: 30.0,
        executor_factory=lambda: executor,  # type: ignore[arg-type]
    )
    pairing.state = PairingState.PAIRED
    pairing.device = DeviceIdentity(1, "Kitchen Pi", "pi", "now", None)
    pairing._verified_token, pairing._next_verify = "verified-token", 0.0
    pairing.tick()
    executor.calls[0][2].set_exception(PairingError("Device pairing is unavailable."))
    pairing.tick()
    assert pairing.state is PairingState.PAIRED and store.load() == "verified-token"


def test_home_pairing_control_is_disabled_while_checking_or_paired() -> None:
    def pairing_button(state: PairingState) -> object:
        return next(
            button
            for button in buttons_for(UIScreen.HOME, state)
            if button.action is UIAction.PAIR_DEVICE
        )

    assert pairing_button(PairingState.REQUESTING).enabled is False
    assert pairing_button(PairingState.PAIRED).label == "Device paired"
    assert pairing_button(PairingState.PAIRED).enabled is False
    assert pairing_button(PairingState.UNPAIRED).label == "Pair Device"
