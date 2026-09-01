"""Hardware-independent PI-2B pairing state and credential ownership."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from nutribox_pi.adapters.device_pairing import DEVICE_AUTH_FAILED, PairingError
from nutribox_pi.models import DeviceIdentity, PairingSession, PairingStatus
from nutribox_pi.ports import DevicePairing

POLL_INTERVAL_SECONDS = 3.0
VERIFY_INTERVAL_SECONDS = 5.0
PAIRING_ERROR = "Device pairing is unavailable."
REVOKED_MESSAGE = "Device pairing was revoked."


class PairingState(StrEnum):
    UNPAIRED = "unpaired"
    REQUESTING = "requesting"
    WAITING = "waiting"
    PAIRED = "paired"
    EXPIRED = "expired"
    ERROR = "error"


class VerificationReason(StrEnum):
    STARTUP = "startup"
    NEW_PAIRING = "new_pairing"
    PERIODIC = "periodic"


class CredentialError(RuntimeError):
    pass


class DeviceCredentialStore:
    """Stores only a verified device token, never pending pairing material."""

    def __init__(self, root: Path | None = None) -> None:
        base = root or Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
        self._directory = base / "nutribox-pi"
        self._path = self._directory / "device-token.json"

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> str | None:
        try:
            if not self._path.exists():
                return None
            if self._path.is_symlink() or not self._path.is_file():
                raise CredentialError
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            token = payload.get("device_token") if isinstance(payload, dict) else None
            if not isinstance(token, str) or not token:
                raise CredentialError
            return token
        except (OSError, ValueError, CredentialError) as exc:
            raise CredentialError("Credential storage is unavailable.") from exc

    def save(self, token: str) -> None:
        if not isinstance(token, str) or not token:
            raise CredentialError("Credential storage is unavailable.")
        try:
            self._directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            if (
                self._directory.is_symlink()
                or not self._directory.is_dir()
                or self._path.is_symlink()
            ):
                raise CredentialError
            if os.name == "posix":
                os.chmod(self._directory, 0o700)
            fd, temporary = tempfile.mkstemp(
                prefix=".device-token-", dir=self._directory
            )
            try:
                if os.name == "posix":
                    os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump({"device_token": token}, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self._path)
            finally:
                Path(temporary).unlink(missing_ok=True)
        except (OSError, CredentialError) as exc:
            raise CredentialError("Credential storage is unavailable.") from exc

    def remove(self) -> None:
        try:
            if self._path.is_symlink():
                raise CredentialError
            self._path.unlink(missing_ok=True)
        except OSError as exc:
            raise CredentialError("Credential storage is unavailable.") from exc


@dataclass(slots=True)
class PairingWorkflow:
    client: DevicePairing
    store: DeviceCredentialStore
    clock: callable = datetime.now
    monotonic: callable = __import__("time").monotonic
    state: PairingState = PairingState.UNPAIRED
    code: str | None = None
    expires_at: datetime | None = None
    device: DeviceIdentity | None = None
    error_message: str | None = None
    executor_factory: Callable[[], ThreadPoolExecutor] | None = None
    _executor: ThreadPoolExecutor = field(init=False, repr=False)
    _future: Future[object] | None = field(init=False, default=None, repr=False)
    _session: PairingSession | None = field(init=False, default=None, repr=False)
    _verification_token: str | None = field(init=False, default=None, repr=False)
    _next_poll: float = field(init=False, default=0.0, repr=False)
    _generation: int = field(init=False, default=0, repr=False)
    _verified_token: str | None = field(init=False, default=None, repr=False)
    _next_verify: float = field(init=False, default=0.0, repr=False)
    _closed: bool = field(init=False, default=False, repr=False)
    greeting: str | None = field(init=False, default=None)
    _verification_reason: VerificationReason | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self._executor = (
            self.executor_factory()
            if self.executor_factory is not None
            else ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="nutribox-pairing"
            )
        )

    def start(self) -> bool:
        if self.state in {
            PairingState.REQUESTING,
            PairingState.WAITING,
            PairingState.PAIRED,
        }:
            return False
        self._reset_pending()
        self.state = PairingState.REQUESTING
        self._future = self._executor.submit(self.client.start, "NutriBox Pi")
        return True

    def startup_verify(self) -> None:
        try:
            token = self.store.load()
        except CredentialError:
            self._error(PAIRING_ERROR)
            return
        if token is not None:
            self._verification_token = token
            self._verification_reason = VerificationReason.STARTUP
            self.state = PairingState.REQUESTING
            self._future = self._executor.submit(self.client.device_me, token)

    def tick(self) -> None:
        if (
            self.expires_at is not None
            and self._now() >= self.expires_at
            and self.state is PairingState.WAITING
        ):
            self._reset_pending()
            self.state = PairingState.EXPIRED
            return
        future = self._future
        if future is not None and future.done():
            self._future = None
            try:
                result = future.result()
            except PairingError as exc:
                if str(exc) == DEVICE_AUTH_FAILED and (
                    self._verification_token is not None
                    or self._verified_token is not None
                ):
                    try:
                        self.store.remove()
                    except CredentialError:
                        self._error(PAIRING_ERROR)
                        return
                    self.device = None
                    self.greeting = None
                    self._clear_transient()
                    self._verified_token = None
                    self.state = PairingState.UNPAIRED
                    self.error_message = REVOKED_MESSAGE
                elif self.state is PairingState.PAIRED:
                    self.device = None
                    self.greeting = None
                    self._next_verify = self.monotonic() + VERIFY_INTERVAL_SECONDS
                else:
                    self._error(str(exc))
                return
            except Exception:
                self._error(PAIRING_ERROR)
                return
            if self.state is PairingState.REQUESTING and isinstance(
                result, PairingSession
            ):
                self._session = result
                self.code = result.pairing_code
                self.expires_at = _parse_time(result.expires_at)
                if self.expires_at is None:
                    self._error(PAIRING_ERROR)
                    return
                self.state = PairingState.WAITING
                self._next_poll = self.monotonic()
                return
            if self.state is PairingState.REQUESTING and isinstance(
                result, DeviceIdentity
            ):
                if self._verification_token is not None:
                    try:
                        self.store.save(self._verification_token)
                    except CredentialError:
                        self._error(PAIRING_ERROR)
                        return
                self.device = result
                self.state = PairingState.PAIRED
                self._verified_token = self._verification_token
                self.greeting = (
                    f"Welcome back, {result.owner_first_name}!"
                    if self._verification_reason is VerificationReason.STARTUP
                    else f"Hello, {result.owner_first_name}!"
                )
                self._clear_transient()
                self._next_verify = self.monotonic() + VERIFY_INTERVAL_SECONDS
                return
            if self.state is PairingState.PAIRED and isinstance(result, DeviceIdentity):
                self.device = result
                self.greeting = None
                self._next_verify = self.monotonic() + VERIFY_INTERVAL_SECONDS
                return
            if self.state is PairingState.WAITING and isinstance(result, PairingStatus):
                if result is PairingStatus.EXPIRED:
                    self._reset_pending()
                    self.state = PairingState.EXPIRED
                elif result is PairingStatus.PAIRED:
                    assert self._session is not None
                    self._verification_token = self._session.device_token
                    self._verification_reason = VerificationReason.NEW_PAIRING
                    self.state = PairingState.REQUESTING
                    self._future = self._executor.submit(
                        self.client.device_me, self._verification_token
                    )
        if (
            self.state is PairingState.WAITING
            and self._future is None
            and self.monotonic() >= self._next_poll
        ):
            self._next_poll = self.monotonic() + POLL_INTERVAL_SECONDS
            self._future = self._executor.submit(self._poll)
        if (
            self.state is PairingState.PAIRED
            and self._future is None
            and self._verified_token is not None
            and self.monotonic() >= self._next_verify
        ):
            self._next_verify = self.monotonic() + VERIFY_INTERVAL_SECONDS
            self._future = self._executor.submit(
                self.client.device_me, self._verified_token
            )
            self._verification_reason = VerificationReason.PERIODIC

    def _poll(self) -> PairingStatus:
        assert self._session is not None
        return self.client.status(
            self._session.session_id, self._session.device_token
        ).status

    def cancel(self) -> None:
        self._generation += 1
        self._reset_pending()
        self.state = PairingState.UNPAIRED
        self.error_message = None

    def remaining_seconds(self) -> int:
        if self.expires_at is None:
            return 0
        return max(0, int((self.expires_at - self._now()).total_seconds()))

    def close(self) -> None:
        self.cancel()
        self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)

    def get_verified_device_token(self) -> str | None:
        if self._closed or self.state is not PairingState.PAIRED or self.device is None:
            return None
        return self._verified_token

    def confirm_revocation(self) -> None:
        """Apply a backend-confirmed device-authentication revocation."""
        try:
            self.store.remove()
        except CredentialError:
            self._error(PAIRING_ERROR)
            return
        self._reset_pending()
        self.device = None
        self.greeting = None
        self.state = PairingState.UNPAIRED
        self.error_message = REVOKED_MESSAGE

    def unpair(self) -> None:
        try:
            self.store.remove()
        except CredentialError:
            self._error(PAIRING_ERROR)
            return
        self._reset_pending()
        self.device = None
        self.greeting = None
        self.state = PairingState.UNPAIRED
        self.error_message = None

    def _reset_pending(self) -> None:
        self._clear_transient()
        self._verified_token = None

    def _clear_transient(self) -> None:
        self._future = None
        self._session = None
        self._verification_token = None
        self._verification_reason = None
        self.code = None
        self.expires_at = None

    def _error(self, message: str) -> None:
        self._reset_pending()
        self.state = PairingState.ERROR
        self.error_message = (
            message
            if message
            in {
                PAIRING_ERROR,
                "Pairing session was not found.",
                "Device pairing is not configured.",
            }
            else PAIRING_ERROR
        )

    def _now(self) -> datetime:
        try:
            return self.clock(UTC)
        except TypeError:
            return self.clock()


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None


def format_countdown(seconds: int) -> str:
    safe_seconds = max(0, seconds)
    return f"Expires in {safe_seconds // 60}:{safe_seconds % 60:02d}"
