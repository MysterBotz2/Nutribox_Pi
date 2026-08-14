# PI-1A Manual Raspberry Pi Deployment

This guide prepares the hardware-independent Nutri-Box client on Raspberry Pi
OS for manual diagnostics. It does not install or configure a camera,
touchscreen UI, GPIO, sensors, heating, systemd, pairing, or authentication.

## Prerequisites

- Raspberry Pi 4 Model B running Raspberry Pi OS
- Git
- Python 3 with virtual-environment support
- Network access to the configured Nutri-Box backend

The setup script does not use `sudo` or install operating-system packages.

## Clone the repository

```bash
git clone <repository-url> nutrobox-pi
cd nutrobox-pi
```

## Configure the backend

Create the local environment file once:

```bash
cp .env.example .env
```

Edit `.env` and replace the example URL:

```dotenv
NUTRIBOX_API_BASE_URL=https://your-backend.example
```

The URL must include an `http` or `https` scheme and a hostname. Do not put
credentials, tokens, or usernames in the URL. The setup script never creates or
overwrites `.env`.

## Install the local project

```bash
scripts/setup_pi.sh
```

The script creates or reuses `.venv` and installs this repository into it. It
is safe to run again after local project updates.

## Run diagnostics

Human-readable output:

```bash
scripts/run_diagnostics.sh
```

JSON output:

```bash
scripts/run_diagnostics.sh --json
```

Both commands return exit code 0 when required configuration is valid and the
backend health endpoint is reachable. They return a nonzero exit code when
configuration is invalid or the backend cannot be reached.

Diagnostics report only the application and Python versions, operating system,
machine architecture, hostname, and safe pass/fail messages. They do not report
environment values, credentials, tokens, usernames, or network-interface
identifiers.

## Network boundary

The Raspberry Pi remains a standalone client. Diagnostics contact only the
configured backend through `GET /api/health`. No unrelated internet service is
probed, and the backend communicates with the Pi only through the network. No
backend code or database is installed on the device.

## Manual execution boundary

PI-1A intentionally uses manual setup and execution. Do not install a systemd
service yet; manual execution must be verified on the target Raspberry Pi first.
