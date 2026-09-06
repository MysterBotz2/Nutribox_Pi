# Nutri-Box Pi

PI-0 is the online-only Python foundation for the Nutri-Box Raspberry Pi 4
client. It provides replaceable hardware/network boundaries, simulated weight
and temperature readings, the existing v1 backend integration, and a minimal
backend health-check CLI.

See [docs/PI0_SCOPE.md](docs/PI0_SCOPE.md) for the binding scope and unresolved
requirements.

For manual Raspberry Pi setup and device diagnostics, see
[docs/PI1_DEPLOYMENT.md](docs/PI1_DEPLOYMENT.md).

For the current release-candidate Pi installation, hardware validation, and
reversible graphical-session autostart, see [docs/PI5_DEPLOYMENT.md](docs/PI5_DEPLOYMENT.md).

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

The release candidate supports the approved camera, touchscreen, HX711 load
cell, pairing, save, and paired leftover workflows. Reheating remains excluded.
