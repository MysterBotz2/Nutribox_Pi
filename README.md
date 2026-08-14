# Nutri-Box Pi

PI-0 is the online-only Python foundation for the Nutri-Box Raspberry Pi 4
client. It provides replaceable hardware/network boundaries, simulated weight
and temperature readings, the existing v1 backend integration, and a minimal
backend health-check CLI.

See [docs/PI0_SCOPE.md](docs/PI0_SCOPE.md) for the binding scope and unresolved
requirements.

## Development

Requires Python 3.11 or newer.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
pytest
ruff check .
```

The application reads environment variables directly; `.env` is an example
convention and is not loaded automatically.

## Health check

```bash
NUTRIBOX_API_BASE_URL=https://api.example.invalid python -m nutribox_pi health
```

The command calls `GET /api/health` and exits nonzero when the backend cannot be
reached or does not return a successful HTTP response.

## Current adapters

- `SimulatedWeightSensor` returns a configured weight in grams.
- `SimulatedTemperatureSensor` returns a configured temperature in Celsius.
- `V1BackendClient` supports the known health and multipart meal-analysis
  endpoints. Analysis sends only `file` and `weight_grams`.

No real camera, touchscreen, GPIO, sensor, heater, profile, pairing, auth,
synchronization, telemetry, offline, or persistence behavior is implemented.
