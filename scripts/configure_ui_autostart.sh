#!/usr/bin/env bash

set -eu

die() {
    printf 'Nutri-Box autostart error: %s\n' "$1" >&2
    exit 1
}

[ "$(uname -s 2>/dev/null || true)" = "Linux" ] ||
    die "this script requires Linux"
command -v systemctl >/dev/null 2>&1 ||
    die "systemctl is required"

PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)" ||
    die "could not resolve the project directory"
LAUNCHER="$PROJECT_DIR/scripts/run_device_ui.sh"
[ -x "$LAUNCHER" ] || die "the device UI launcher is unavailable"

CONFIG_ROOT="${XDG_CONFIG_HOME:-$HOME/.config}"
UNIT_DIR="$CONFIG_ROOT/systemd/user"
UNIT_PATH="$UNIT_DIR/nutribox-pi-ui.service"
UNIT_NAME="nutribox-pi-ui.service"
DEFAULT_WANTS_PATH="$UNIT_DIR/default.target.wants/$UNIT_NAME"
LEGACY_WANTS_PATH="$UNIT_DIR/graphical-session.target.wants/$UNIT_NAME"

case "${1:-enable}" in
    enable)
        mkdir -p "$UNIT_DIR" || die "could not create the user unit directory"
        # A previous release installed this unit under graphical-session.target.
        # Pi OS does not reliably activate that target, so remove only that
        # exact legacy link before enabling the default-target unit below.
        rm -f -- "$LEGACY_WANTS_PATH" ||
            die "could not remove the legacy graphical-session link"
        # ExecStart accepts a quoted systemd argument. Escape the only
        # characters that are significant to that syntax; percent must also be
        # doubled to avoid systemd specifier expansion.
        ESCAPED_LAUNCHER="${LAUNCHER//\\/\\\\}"
        ESCAPED_LAUNCHER="${ESCAPED_LAUNCHER//\"/\\\"}"
        ESCAPED_LAUNCHER="${ESCAPED_LAUNCHER//%/%%}"
        case "$ESCAPED_LAUNCHER" in
            *$'\n'* | *$'\r'*) die "the project path is unsafe for a user unit" ;;
        esac
        {
            printf '[Unit]\n'
            printf 'Description=Nutri-Box Pi touchscreen UI\n'
            printf 'After=graphical-session.target network-online.target\n'
            printf 'Wants=network-online.target\n\n'
            printf '[Service]\n'
            printf 'Type=simple\n'
            printf 'ExecStart="%s"\n' "$ESCAPED_LAUNCHER"
            printf 'Restart=on-failure\n'
            printf 'RestartSec=3\n\n'
            printf '[Install]\n'
            printf 'WantedBy=default.target\n'
        } >"$UNIT_PATH" || die "could not write the user unit"
        systemctl --user daemon-reload || die "could not reload user services"
        systemctl --user enable --now "$UNIT_NAME" ||
            die "could not enable the UI service"
        printf 'Nutri-Box UI autostart is enabled.\n'
        ;;
    disable)
        systemctl --user disable --now "$UNIT_NAME" >/dev/null 2>&1 || true
        # `systemctl disable` follows the current [Install] section. Remove
        # both known links explicitly so disable also cleans up older installs.
        rm -f -- "$DEFAULT_WANTS_PATH" "$LEGACY_WANTS_PATH" ||
            die "could not remove the UI service links"
        rm -f -- "$UNIT_PATH" || die "could not remove the user unit"
        systemctl --user daemon-reload || die "could not reload user services"
        printf 'Nutri-Box UI autostart is disabled.\n'
        ;;
    *)
        die "usage: scripts/configure_ui_autostart.sh [enable|disable]"
        ;;
esac
