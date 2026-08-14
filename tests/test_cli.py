import pytest

from nutribox_pi import cli
from nutribox_pi.adapters.v1_backend import BackendError
from nutribox_pi.models import HealthResult


class FakeController:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def check_backend(self) -> HealthResult:
        if self.error:
            raise self.error
        return HealthResult(healthy=True, payload={})


def test_cli_health_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NUTRIBOX_API_BASE_URL", "https://backend.test")
    monkeypatch.setattr(cli, "_controller", lambda settings: FakeController())

    assert cli.main(["health"]) == 0
    assert capsys.readouterr().out == "{}\n"


def test_cli_health_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NUTRIBOX_API_BASE_URL", "https://backend.test")
    error = BackendError("unavailable")
    monkeypatch.setattr(cli, "_controller", lambda settings: FakeController(error))

    assert cli.main(["health"]) == 1
    assert "health check failed" in capsys.readouterr().err


def test_cli_reports_missing_required_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("NUTRIBOX_API_BASE_URL", raising=False)

    assert cli.main(["health"]) == 1
    assert "NUTRIBOX_API_BASE_URL is required" in capsys.readouterr().err
