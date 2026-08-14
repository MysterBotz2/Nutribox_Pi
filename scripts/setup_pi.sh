#!/usr/bin/env bash

set -eu

die() {
    printf 'Nutri-Box setup error: %s\n' "$1" >&2
    exit 1
}

[ "$(uname -s 2>/dev/null || true)" = "Linux" ] ||
    die "this setup script requires Linux"

command -v python3 >/dev/null 2>&1 ||
    die "python3 is required but was not found"

PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)" ||
    die "could not resolve the project directory"
VENV_DIR="$PROJECT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"

if [ ! -d "$VENV_DIR" ]; then
    printf 'Creating project environment at .venv\n'
    python3 -m venv "$VENV_DIR" ||
        die "could not create .venv; ensure Python venv support is installed"
elif [ ! -x "$VENV_PYTHON" ]; then
    die "existing .venv is incomplete; move it aside and run setup again"
else
    printf 'Reusing existing project environment at .venv\n'
fi

printf 'Installing the local Nutri-Box project\n'
"$VENV_PYTHON" -m pip install "$PROJECT_DIR" ||
    die "local project installation failed"

printf 'Setup complete. Create .env from .env.example, then run:\n'
printf '  scripts/run_diagnostics.sh\n'
