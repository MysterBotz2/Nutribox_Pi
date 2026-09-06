#!/usr/bin/env bash

set -eu

die() {
    printf 'Nutri-Box autostart error: %s\n' "$1" >&2
    exit 1
}

[ "$(uname -s 2>/dev/null || true)" = "Linux" ] ||
    die "this script requires Linux"

PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)" ||
    die "could not resolve the project directory"
LAUNCHER="$PROJECT_DIR/scripts/run_device_ui.sh"
[ -f "$LAUNCHER" ] || die "the device UI launcher is unavailable"

CONFIG_ROOT="${XDG_CONFIG_HOME:-$HOME/.config}"
LABWC_DIR="$CONFIG_ROOT/labwc"
AUTOSTART_PATH="$LABWC_DIR/autostart"
MANAGED_START="# >>> Nutri-Box Pi managed autostart >>>"
MANAGED_END="# <<< Nutri-Box Pi managed autostart <<<"

UNIT_DIR="$CONFIG_ROOT/systemd/user"
UNIT_NAME="nutribox-pi-ui.service"
UNIT_PATH="$UNIT_DIR/$UNIT_NAME"
DEFAULT_WANTS_PATH="$UNIT_DIR/default.target.wants/$UNIT_NAME"
LEGACY_WANTS_PATH="$UNIT_DIR/graphical-session.target.wants/$UNIT_NAME"

shell_quote() {
    QUOTED_VALUE="${1//\'/\'\\\'\'}"
    printf "'%s'" "$QUOTED_VALUE"
}

remove_managed_labwc_entry() {
    [ -e "$AUTOSTART_PATH" ] || return 0
    TEMP_PATH="$(mktemp "$LABWC_DIR/.nutribox-autostart.XXXXXX")" ||
        die "could not prepare the Labwc autostart update"
    if ! awk -v start="$MANAGED_START" -v end="$MANAGED_END" '
        $0 == start {
            if (inside || seen_start) exit 2
            inside = 1
            seen_start = 1
            next
        }
        $0 == end {
            if (!inside || seen_end) exit 3
            inside = 0
            seen_end = 1
            next
        }
        !inside { print }
        END {
            if (inside || seen_start != seen_end) exit 4
        }
    ' "$AUTOSTART_PATH" >"$TEMP_PATH"; then
        rm -f -- "$TEMP_PATH"
        die "the managed Labwc autostart entry is malformed"
    fi
    mv -f -- "$TEMP_PATH" "$AUTOSTART_PATH" ||
        die "could not update the Labwc autostart file"
}

remove_legacy_systemd_unit() {
    if command -v systemctl >/dev/null 2>&1; then
        systemctl --user disable --now "$UNIT_NAME" >/dev/null 2>&1 || true
    fi
    rm -f -- "$DEFAULT_WANTS_PATH" "$LEGACY_WANTS_PATH" "$UNIT_PATH" ||
        die "could not remove the obsolete UI service"
    if command -v systemctl >/dev/null 2>&1; then
        systemctl --user daemon-reload >/dev/null 2>&1 || true
    fi
}

case "${1:-enable}" in
    enable)
        mkdir -p "$LABWC_DIR" || die "could not create the Labwc directory"
        chmod u+x "$LAUNCHER" || die "could not make the device launcher executable"
        remove_managed_labwc_entry
        remove_legacy_systemd_unit
        QUOTED_LAUNCHER="$(shell_quote "$LAUNCHER")"
        {
            printf '%s\n' "$MANAGED_START"
            printf '%s &\n' "$QUOTED_LAUNCHER"
            printf '%s\n' "$MANAGED_END"
        } >>"$AUTOSTART_PATH" || die "could not write the Labwc autostart entry"
        printf 'Nutri-Box Labwc autostart is enabled.\n'
        ;;
    disable)
        [ ! -d "$LABWC_DIR" ] || remove_managed_labwc_entry
        remove_legacy_systemd_unit
        printf 'Nutri-Box Labwc autostart is disabled.\n'
        ;;
    *)
        die "usage: scripts/configure_ui_autostart.sh [enable|disable]"
        ;;
esac
