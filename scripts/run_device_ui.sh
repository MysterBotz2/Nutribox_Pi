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
READY_TIMEOUT_SECONDS=30
READY_POLL_SECONDS=1

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

"$VENV_PYTHON" -m nutribox_pi preflight >/dev/null 2>&1 ||
    die "device configuration is invalid"

wait_for_wayland_session() {
    READY_ELAPSED=0
    while [ "$READY_ELAPSED" -lt "$READY_TIMEOUT_SECONDS" ]; do
        if [ -z "${XDG_RUNTIME_DIR:-}" ]; then
            RUNTIME_CANDIDATE="/run/user/$(id -u)"
            if [ -d "$RUNTIME_CANDIDATE" ] && [ -O "$RUNTIME_CANDIDATE" ]; then
                XDG_RUNTIME_DIR="$RUNTIME_CANDIDATE"
                export XDG_RUNTIME_DIR
            fi
        fi

        if [ -n "${XDG_RUNTIME_DIR:-}" ] && [ -d "$XDG_RUNTIME_DIR" ] &&
            [ -O "$XDG_RUNTIME_DIR" ]; then
            if [ -n "${WAYLAND_DISPLAY:-}" ] &&
                [ -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ]; then
                return 0
            fi
            if [ -z "${WAYLAND_DISPLAY:-}" ]; then
                for CANDIDATE in "$XDG_RUNTIME_DIR"/wayland-*; do
                    if [ -S "$CANDIDATE" ]; then
                        WAYLAND_DISPLAY="${CANDIDATE##*/}"
                        export WAYLAND_DISPLAY
                        SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-wayland}"
                        export SDL_VIDEODRIVER
                        return 0
                    fi
                done
            fi
        fi

        sleep "$READY_POLL_SECONDS"
        READY_ELAPSED=$((READY_ELAPSED + READY_POLL_SECONDS))
    done
    return 1
}

if [ -z "${WAYLAND_DISPLAY:-}" ] && [ -z "${DISPLAY:-}" ]; then
    wait_for_wayland_session ||
        die "the graphical session did not become ready before the timeout"
fi

if [ -n "${WAYLAND_DISPLAY:-}" ]; then
    [ -n "${XDG_RUNTIME_DIR:-}" ] ||
        die "Wayland is selected but its runtime directory is unavailable"
    [ -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ] ||
        die "the selected Wayland session socket is unavailable"
fi

command -v flock >/dev/null 2>&1 ||
    die "flock is required to prevent duplicate UI processes"
[ -n "${XDG_RUNTIME_DIR:-}" ] ||
    die "no safe runtime directory is available for the UI process lock"
[ -d "$XDG_RUNTIME_DIR" ] && [ -O "$XDG_RUNTIME_DIR" ] ||
    die "the UI runtime directory is unavailable or unsafe"
LOCK_FILE="$XDG_RUNTIME_DIR/nutribox-pi-ui.lock"
exec 9>"$LOCK_FILE" || die "could not create the UI process lock"
flock -n 9 || die "another Nutri-Box UI process is already running"

exec "$VENV_PYTHON" -m nutribox_pi ui
