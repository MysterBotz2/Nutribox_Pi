"""Minimal PI-0 command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from nutribox_pi import __version__
from nutribox_pi.adapters import (
    BackendError,
    DevicePairingClient,
    SimulatedTemperatureSensor,
    V1BackendClient,
    WeightSensorUnavailable,
)
from nutribox_pi.adapters.pygame_device_ui import run_device_ui
from nutribox_pi.adapters.pygame_touchscreen import run_touchscreen_check
from nutribox_pi.camera_diagnostics import (
    CameraDiagnosticsService,
    capture_as_dict,
    format_camera_capture,
    format_camera_check,
)
from nutribox_pi.camera_factory import camera_from_env
from nutribox_pi.config import ConfigurationError, Settings
from nutribox_pi.controller import NutriBoxController
from nutribox_pi.device_ui import ANALYSIS_ERROR
from nutribox_pi.diagnostics import DiagnosticsService, format_human_report
from nutribox_pi.pairing import DeviceCredentialStore, PairingWorkflow
from nutribox_pi.weight_factory import weight_from_env


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nutribox-pi")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("health", help="check the v1 backend health endpoint")
    diagnostics_parser = subparsers.add_parser(
        "diagnostics", help="run safe device diagnostics"
    )
    diagnostics_parser.add_argument(
        "--json", action="store_true", help="emit machine-readable JSON"
    )
    camera_check_parser = subparsers.add_parser(
        "camera-check", help="run local camera diagnostics"
    )
    camera_check_parser.add_argument("--json", action="store_true")
    camera_capture_parser = subparsers.add_parser(
        "camera-capture", help="capture one JPEG image"
    )
    camera_capture_parser.add_argument("output")
    camera_capture_parser.add_argument("--overwrite", action="store_true")
    camera_capture_parser.add_argument("--json", action="store_true")
    weight_check_parser = subparsers.add_parser(
        "weight-check", help="read the configured local weight sensor"
    )
    weight_check_parser.add_argument("--json", action="store_true")
    subparsers.add_parser("weight-tare", help="tare the configured HX711 sensor")
    weight_calibrate_parser = subparsers.add_parser(
        "weight-calibrate", help="calibrate the configured HX711 sensor"
    )
    weight_calibrate_parser.add_argument("--known-grams", required=True, type=float)
    subparsers.add_parser(
        "touchscreen-check", help="run the local touchscreen smoke test"
    )
    subparsers.add_parser("ui", help="run the local meal-capture interface")
    args = parser.parse_args(argv)

    if args.command == "ui":
        try:
            settings = Settings.from_env()
            pairing = PairingWorkflow(
                DevicePairingClient(
                    settings.api_base_url, settings.http_timeout_seconds
                ),
                DeviceCredentialStore(),
            )
            pairing.startup_verify()
            weight_sensor = weight_from_env()
            controller = _controller(settings, pairing)
        except (BackendError, ConfigurationError, ValueError):
            print(ANALYSIS_ERROR)
            return 1
        result = run_device_ui(
            controller=controller,
            simulated_weight=bool(getattr(weight_sensor, "is_simulated", False)),
            pairing=pairing,
        )
        print(result.message)
        return 0 if result.ok else 1

    if args.command == "touchscreen-check":
        result = run_touchscreen_check()
        print(result.message)
        return 0 if result.ok else 1

    if args.command == "camera-check":
        report = CameraDiagnosticsService(camera_from_env()).run()
        print(
            json.dumps(report.as_dict(), sort_keys=True)
            if args.json
            else format_camera_check(report)
        )
        return 0 if report.ok else 1

    if args.command == "camera-capture":
        result = camera_from_env().capture(Path(args.output), overwrite=args.overwrite)
        print(
            json.dumps(capture_as_dict(result), sort_keys=True)
            if args.json
            else format_camera_capture(result)
        )
        return 0 if result.ok else 1

    if args.command in {"weight-check", "weight-tare", "weight-calibrate"}:
        sensor = weight_from_env()
        try:
            if args.command == "weight-check":
                grams = sensor.read_grams()
                if args.json:
                    print(json.dumps({"ok": True, "weight_grams": grams}))
                else:
                    print(f"Weight: {grams:g} g")
            elif args.command == "weight-tare":
                tare = getattr(sensor, "tare", None)
                if not callable(tare):
                    raise WeightSensorUnavailable()
                tare()
                print("Weight sensor tared.")
            else:
                if not 0 < args.known_grams <= 5000:
                    raise WeightSensorUnavailable()
                calibrate = getattr(sensor, "calibrate", None)
                if not callable(calibrate):
                    raise WeightSensorUnavailable()
                calibrate(args.known_grams)
                print("Weight sensor calibrated.")
        except (AttributeError, ValueError, WeightSensorUnavailable):
            print("Weight sensor unavailable.", file=sys.stderr)
            return 1
        return 0

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


def _controller(
    settings: Settings,
    credential_provider: object | None = None,
    weight_sensor: object | None = None,
) -> NutriBoxController:
    return NutriBoxController(
        backend=V1BackendClient(
            settings.api_base_url, timeout_seconds=settings.http_timeout_seconds
        ),
        weight_sensor=weight_sensor or weight_from_env(),
        temperature_sensor=SimulatedTemperatureSensor(settings.simulated_temperature_c),
        credential_provider=credential_provider,  # type: ignore[arg-type]
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
