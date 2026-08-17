import json
from pathlib import Path

import pytest

from nutribox_pi import cli
from nutribox_pi.adapters.v1_backend import BackendError
from nutribox_pi.diagnostics import (
    DeviceInformation,
    DiagnosticCheck,
    DiagnosticReport,
)
from nutribox_pi.models import HealthResult


class FakeController:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def check_backend(self) -> HealthResult:
        if self.error:
            raise self.error
        return HealthResult(healthy=True, payload={})


class FakeDiagnosticsService:
    def __init__(self, passed: bool) -> None:
        self.passed = passed

    def run(self) -> DiagnosticReport:
        return DiagnosticReport(
            device=DeviceInformation(
                application_version="1.2.3",
                python_version="3.11.9",
                operating_system="Linux",
                machine_architecture="aarch64",
                hostname="nutribox-device",
            ),
            checks=(
                DiagnosticCheck(
                    name="configuration",
                    passed=self.passed,
                    message="safe message",
                ),
            ),
        )


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


def test_cli_diagnostics_human_output_and_success_exit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        cli, "_diagnostics_service", lambda: FakeDiagnosticsService(True)
    )

    assert cli.main(["diagnostics"]) == 0
    output = capsys.readouterr().out
    assert "Nutri-Box device diagnostics" in output
    assert "Overall: PASS" in output


def test_cli_diagnostics_json_output_and_failure_exit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        cli, "_diagnostics_service", lambda: FakeDiagnosticsService(False)
    )

    assert cli.main(["diagnostics", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is False
    assert payload["device"]["hostname"] == "nutribox-device"


def test_cli_camera_check_does_not_require_backend(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("NUTRIBOX_API_BASE_URL", raising=False)
    monkeypatch.setenv("NUTRIBOX_CAMERA_ADAPTER", "simulated")

    assert cli.main(["camera-check", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["command"] == "camera-check"


def test_cli_camera_capture_exact_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("NUTRIBOX_API_BASE_URL", raising=False)
    monkeypatch.setenv("NUTRIBOX_CAMERA_ADAPTER", "simulated")
    output = tmp_path / "meal.jpg"

    assert cli.main(["camera-capture", str(output), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "command": "camera-capture",
        "ok": True,
        "code": "ok",
        "message": "Image captured.",
        "file_name": "meal.jpg",
        "format": "jpeg",
        "width": 1920,
        "height": 1080,
    }


def test_cli_camera_capture_missing_configuration_is_safe(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("NUTRIBOX_CAMERA_ADAPTER", raising=False)
    output = tmp_path / "secret-name.jpg"

    assert cli.main(["camera-capture", str(output), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "command": "camera-capture",
        "ok": False,
        "code": "invalid_configuration",
        "message": "Camera configuration is invalid.",
    }
