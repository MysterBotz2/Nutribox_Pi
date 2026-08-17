#!/usr/bin/env bash

set -eu

die() {
    printf 'Nutri-Box camera smoke-test error: %s\n' "$1" >&2
    exit 1
}

PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)" ||
    die "could not resolve the project directory"
VENV_PYTHON="$PROJECT_DIR/.venv-pi/bin/python"
ENV_FILE="$PROJECT_DIR/.env"

[ -x "$VENV_PYTHON" ] ||
    die ".venv-pi is missing; run scripts/setup_pi_camera.sh first"
"$VENV_PYTHON" -c 'import nutribox_pi, picamera2' >/dev/null 2>&1 ||
    die ".venv-pi is incompatible with the camera workflow"

if [ -n "${NUTRIBOX_CAMERA_ADAPTER:-}" ]; then
    [ "$NUTRIBOX_CAMERA_ADAPTER" = "picamera2" ] ||
        die "NUTRIBOX_CAMERA_ADAPTER must be picamera2"
else
    if [ -f "$ENV_FILE" ]; then
        set -a
        # shellcheck disable=SC1090
        . "$ENV_FILE" || die "could not load .env"
        set +a
    fi
fi

[ "${NUTRIBOX_CAMERA_ADAPTER:-}" = "picamera2" ] ||
    die "NUTRIBOX_CAMERA_ADAPTER must be picamera2"

exec "$VENV_PYTHON" -m nutribox_pi camera-check "$@"
