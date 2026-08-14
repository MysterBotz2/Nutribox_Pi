"""Minimal PI-0 command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from nutribox_pi import __version__
from nutribox_pi.adapters import (
    BackendError,
    SimulatedTemperatureSensor,
    SimulatedWeightSensor,
    V1BackendClient,
)
from nutribox_pi.config import ConfigurationError, Settings
from nutribox_pi.controller import NutriBoxController
from nutribox_pi.diagnostics import DiagnosticsService, format_human_report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nutribox-pi")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "health", help="check the v1 backend health endpoint"
    )
    diagnostics_parser = subparsers.add_parser(
        "diagnostics", help="run safe device diagnostics"
    )
    diagnostics_parser.add_argument(
        "--json", action="store_true", help="emit machine-readable JSON"
    )
    args = parser.parse_args(argv)

    if args.command == "diagnostics":
        report = _diagnostics_service().run()
        if args.json:
            print(json.dumps(report.as_dict(), sort_keys=True))
        else:
            print(format_human_report(report))
        return 0 if report.passed else 1

    try:
        settings = Settings.from_env()
        controller = _controller(settings)
        if args.command == "health":
            result = controller.check_backend()
            print(json.dumps(result.payload, sort_keys=True))
            return 0 if result.healthy else 1
    except (BackendError, ConfigurationError) as exc:
        print(f"health check failed: {exc}", file=sys.stderr)
        return 1
    return 2


def _controller(settings: Settings) -> NutriBoxController:
    return NutriBoxController(
        backend=V1BackendClient(
            settings.api_base_url, timeout_seconds=settings.http_timeout_seconds
        ),
        weight_sensor=SimulatedWeightSensor(settings.simulated_weight_grams),
        temperature_sensor=SimulatedTemperatureSensor(
            settings.simulated_temperature_c
        ),
    )


def _diagnostics_service() -> DiagnosticsService:
    return DiagnosticsService(
        configuration_loader=Settings.from_env,
        backend_factory=lambda settings: V1BackendClient(
            settings.api_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        ),
        application_version=__version__,
    )
