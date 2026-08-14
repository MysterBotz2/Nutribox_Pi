import json

from nutribox_pi.config import ConfigurationError, Settings
from nutribox_pi.diagnostics import (
    DeviceInformation,
    DiagnosticsService,
    format_human_report,
)
from nutribox_pi.models import HealthResult

DEVICE_INFORMATION = DeviceInformation(
    application_version="1.2.3",
    python_version="3.11.9",
    operating_system="Linux",
    machine_architecture="aarch64",
    hostname="nutribox-device",
)


class BackendStub:
    def __init__(self, healthy: bool = True, error: Exception | None = None) -> None:
        self.healthy = healthy
        self.error = error
        self.calls = 0

    def health(self) -> HealthResult:
        self.calls += 1
        if self.error:
            raise self.error
        return HealthResult(healthy=self.healthy, payload={})


def settings() -> Settings:
    return Settings(api_base_url="https://backend.test")


def device_information_loader(version: str) -> DeviceInformation:
    assert version == "1.2.3"
    return DEVICE_INFORMATION


def test_successful_diagnostics() -> None:
    backend = BackendStub()
    report = DiagnosticsService(
        configuration_loader=settings,
        backend_factory=lambda configuration: backend,
        application_version="1.2.3",
        device_information_loader=device_information_loader,
    ).run()

    assert report.passed is True
    assert [check.passed for check in report.checks] == [True, True]
    assert backend.calls == 1
    assert report.device == DEVICE_INFORMATION


def test_invalid_configuration_skips_backend_and_is_safely_reported() -> None:
    backend_factory_called = False

    def invalid_configuration() -> Settings:
        raise ConfigurationError("secret-token-value")

    def backend_factory(configuration: Settings) -> BackendStub:
        nonlocal backend_factory_called
        backend_factory_called = True
        return BackendStub()

    report = DiagnosticsService(
        configuration_loader=invalid_configuration,
        backend_factory=backend_factory,
        application_version="1.2.3",
        device_information_loader=device_information_loader,
    ).run()

    assert report.passed is False
    assert backend_factory_called is False
    assert "secret-token-value" not in json.dumps(report.as_dict())
    assert report.checks[1].message.startswith("Backend check skipped")


def test_backend_failure_is_normalized_and_redacted() -> None:
    backend = BackendStub(error=RuntimeError("token=do-not-report"))
    report = DiagnosticsService(
        configuration_loader=settings,
        backend_factory=lambda configuration: backend,
        application_version="1.2.3",
        device_information_loader=device_information_loader,
    ).run()

    rendered = json.dumps(report.as_dict())
    assert report.passed is False
    assert report.checks[0].passed is True
    assert report.checks[1].message == "Backend is unreachable."
    assert "do-not-report" not in rendered


def test_human_report_is_readable_and_contains_no_secret() -> None:
    backend = BackendStub(error=RuntimeError("password=hidden"))
    report = DiagnosticsService(
        configuration_loader=settings,
        backend_factory=lambda configuration: backend,
        application_version="1.2.3",
        device_information_loader=device_information_loader,
    ).run()

    output = format_human_report(report)
    assert "Nutri-Box device diagnostics" in output
    assert "Application version: 1.2.3" in output
    assert "configuration: PASS" in output
    assert "backend: FAIL" in output
    assert "Overall: FAIL" in output
    assert "hidden" not in output
