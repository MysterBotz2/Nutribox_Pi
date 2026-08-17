#!/usr/bin/env bash

set -eu

die() {
    printf 'Nutri-Box camera setup error: %s\n' "$1" >&2
    exit 1
}

[ "$(uname -s 2>/dev/null || true)" = "Linux" ] ||
    die "this setup script requires Linux"

ARCHITECTURE="$(uname -m 2>/dev/null || true)"
case "$ARCHITECTURE" in
    aarch64|arm64) ;;
    *) die "this setup script requires arm64/aarch64" ;;
esac

command -v python3 >/dev/null 2>&1 ||
    die "python3 is required but was not found"
python3 -c 'import picamera2' >/dev/null 2>&1 ||
    die "system Python cannot import OS-managed Picamera2"

PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)" ||
    die "could not resolve the project directory"
VENV_DIR="$PROJECT_DIR/.venv-pi"
VENV_PYTHON="$VENV_DIR/bin/python"

if [ -x "$PROJECT_DIR/.venv/bin/python" ]; then
    if "$PROJECT_DIR/.venv/bin/python" -c 'import picamera2' >/dev/null 2>&1; then
        printf 'Existing .venv can import Picamera2; it remains unchanged.\n'
    else
        printf 'Existing .venv is isolated from Picamera2; it remains unchanged.\n'
    fi
elif [ -e "$PROJECT_DIR/.venv" ]; then
    printf 'Existing .venv is incomplete; it remains unchanged.\n'
fi

if [ ! -e "$VENV_DIR" ]; then
    printf 'Creating Pi camera environment at .venv-pi\n'
    python3 -m venv --system-site-packages "$VENV_DIR" ||
        die "could not create .venv-pi; ensure Python venv support is installed"
elif [ ! -d "$VENV_DIR" ]; then
    die "existing .venv-pi path is not a directory; move it aside manually"
else
    printf 'Reusing existing Pi camera environment at .venv-pi\n'
fi

[ -f "$VENV_DIR/pyvenv.cfg" ] ||
    die "existing .venv-pi is incomplete; move it aside manually"
[ -x "$VENV_PYTHON" ] ||
    die "existing .venv-pi has no usable interpreter; move it aside manually"
grep -Eq '^[[:space:]]*include-system-site-packages[[:space:]]*=[[:space:]]*true[[:space:]]*$' \
    "$VENV_DIR/pyvenv.cfg" ||
    die "existing .venv-pi does not expose system site packages"
"$VENV_PYTHON" -c 'import picamera2' >/dev/null 2>&1 ||
    die "existing .venv-pi cannot import OS-managed Picamera2"

printf 'Installing the local Nutri-Box project into .venv-pi\n'
"$VENV_PYTHON" -m pip install "$PROJECT_DIR" ||
    die "local project installation failed"
"$VENV_PYTHON" -c 'import nutribox_pi, picamera2' >/dev/null 2>&1 ||
    die "installed Pi camera environment failed import verification"

printf 'Camera setup complete. Configure NUTRIBOX_CAMERA_ADAPTER=picamera2.\n'
