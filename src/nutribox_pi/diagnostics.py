"""Safe, hardware-independent device diagnostics."""

from __future__ import annotations

import platform
import socket
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from nutribox_pi.config import Settings
from nutribox_pi.ports import Backend


@dataclass(frozen=True, slots=True)
class DeviceInformation:
    application_version: str
    python_version: str
    operating_system: str
    machine_architecture: str
    hostname: str


@dataclass(frozen=True, slots=True)
class DiagnosticCheck:
    name: str
    passed: bool
    message: str


@dataclass(frozen=True, slots=True)
class DiagnosticReport:
    device: DeviceInformation
    checks: tuple[DiagnosticCheck, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "device": asdict(self.device),
            "checks": [asdict(check) for check in self.checks],
        }


class DiagnosticsService:
    def __init__(
        self,
        configuration_loader: Callable[[], Settings],
        backend_factory: Callable[[Settings], Backend],
        application_version: str,
        device_information_loader: Callable[[str], DeviceInformation] | None = None,
    ) -> None:
        self._configuration_loader = configuration_loader
        self._backend_factory = backend_factory
        self._application_version = application_version
        self._device_information_loader = (
            device_information_loader or load_device_information
        )

    def run(self) -> DiagnosticReport:
        device = self._safe_device_information()
        try:
            settings = self._configuration_loader()
        except Exception:
            return DiagnosticReport(
                device=device,
                checks=(
                    DiagnosticCheck(
                        name="configuration",
                        passed=False,
                        message="Required configuration is invalid.",
                    ),
                    DiagnosticCheck(
                        name="backend",
                        passed=False,
                        message=(
                            "Backend check skipped because configuration is invalid."
                        ),
                    ),
                ),
            )

        configuration_check = DiagnosticCheck(
            name="configuration",
            passed=True,
            message="Required configuration is valid.",
        )
        try:
            result = self._backend_factory(settings).health()
            backend_passed = result.healthy
        except Exception:
            backend_passed = False

        backend_check = DiagnosticCheck(
            name="backend",
            passed=backend_passed,
            message=(
                "Backend is reachable." if backend_passed else "Backend is unreachable."
            ),
        )
        return DiagnosticReport(
            device=device,
            checks=(configuration_check, backend_check),
        )

    def _safe_device_information(self) -> DeviceInformation:
        try:
            return self._device_information_loader(self._application_version)
        except Exception:
            return DeviceInformation(
                application_version=self._application_version,
                python_version="unavailable",
                operating_system="unavailable",
                machine_architecture="unavailable",
                hostname="unavailable",
            )


def load_device_information(application_version: str) -> DeviceInformation:
    return DeviceInformation(
        application_version=application_version,
        python_version=platform.python_version() or sys.version.split()[0],
        operating_system=platform.system() or "unavailable",
        machine_architecture=platform.machine() or "unavailable",
        hostname=socket.gethostname() or "unavailable",
    )


def format_human_report(report: DiagnosticReport) -> str:
    device = report.device
    lines = [
        "Nutri-Box device diagnostics",
        f"Application version: {device.application_version}",
        f"Python version: {device.python_version}",
        f"Operating system: {device.operating_system}",
        f"Machine architecture: {device.machine_architecture}",
        f"Hostname: {device.hostname}",
        "Checks:",
    ]
    for check in report.checks:
        status = "PASS" if check.passed else "FAIL"
        lines.append(f"- {check.name}: {status} — {check.message}")
    lines.append(f"Overall: {'PASS' if report.passed else 'FAIL'}")
    return "\n".join(lines)
