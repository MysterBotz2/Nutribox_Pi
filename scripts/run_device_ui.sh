#!/usr/bin/env bash

set -eu

die() {
    printf 'Nutri-Box device UI error: %s\n' "$1" >&2
    exit 1
}

PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)" ||
    die "could not resolve the project directory"
VENV_PYTHON="$PROJECT_DIR/.venv-pi/bin/python"
ENV_FILE="$PROJECT_DIR/.env"

[ -x "$VENV_PYTHON" ] ||
    die ".venv-pi is missing or has no usable interpreter"
"$VENV_PYTHON" -c 'import nutribox_pi, pygame, picamera2' >/dev/null 2>&1 ||
    die ".venv-pi cannot import the project and OS-managed UI/camera support"

if { [ -z "${NUTRIBOX_CAMERA_ADAPTER:-}" ] ||
    [ -z "${NUTRIBOX_API_BASE_URL:-}" ]; } && [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE" || die "could not load .env"
    set +a
fi
[ "${NUTRIBOX_CAMERA_ADAPTER:-}" = "picamera2" ] ||
    die "NUTRIBOX_CAMERA_ADAPTER must be picamera2"

if [ -z "${XDG_RUNTIME_DIR:-}" ]; then
    RUNTIME_CANDIDATE="/run/user/$(id -u)"
    if [ -d "$RUNTIME_CANDIDATE" ] && [ -O "$RUNTIME_CANDIDATE" ]; then
        XDG_RUNTIME_DIR="$RUNTIME_CANDIDATE"
        export XDG_RUNTIME_DIR
    fi
fi

if [ -z "${WAYLAND_DISPLAY:-}" ] && [ -z "${DISPLAY:-}" ]; then
    [ -n "${XDG_RUNTIME_DIR:-}" ] ||
        die "no graphical session is available for this user"
    [ -d "$XDG_RUNTIME_DIR" ] && [ -O "$XDG_RUNTIME_DIR" ] ||
        die "the graphical runtime directory is unavailable or unsafe"
    WAYLAND_SOCKET=""
    for CANDIDATE in "$XDG_RUNTIME_DIR"/wayland-*; do
        if [ -S "$CANDIDATE" ]; then
            WAYLAND_SOCKET="$CANDIDATE"
            break
        fi
    done
    [ -n "$WAYLAND_SOCKET" ] ||
        die "no Wayland session socket is available for this user"
    WAYLAND_DISPLAY="${WAYLAND_SOCKET##*/}"
    export WAYLAND_DISPLAY
    SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-wayland}"
    export SDL_VIDEODRIVER
fi

if [ -n "${WAYLAND_DISPLAY:-}" ]; then
    [ -n "${XDG_RUNTIME_DIR:-}" ] ||
        die "Wayland is selected but its runtime directory is unavailable"
    [ -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ] ||
        die "the selected Wayland session socket is unavailable"
fi

exec "$VENV_PYTHON" -m nutribox_pi ui
