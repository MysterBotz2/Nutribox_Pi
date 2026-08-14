#!/usr/bin/env bash

set -eu

die() {
    printf 'Nutri-Box diagnostics error: %s\n' "$1" >&2
    exit 1
}

PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)" ||
    die "could not resolve the project directory"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
ENV_FILE="$PROJECT_DIR/.env"

[ -x "$VENV_PYTHON" ] ||
    die "project environment is missing; run scripts/setup_pi.sh first"
[ -f "$ENV_FILE" ] ||
    die ".env is missing; copy .env.example to .env and configure it"

set -a
# shellcheck disable=SC1090
. "$ENV_FILE" || die "could not load .env"
set +a

exec "$VENV_PYTHON" -m nutribox_pi diagnostics "$@"
