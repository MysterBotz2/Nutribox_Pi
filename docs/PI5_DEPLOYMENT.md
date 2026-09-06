# NutriBox Pi release-candidate deployment

This guide covers the standalone Raspberry Pi 4 application. The Pi communicates
with the backend only over the configured network API; no backend or Web
Companion code is installed on the device.

## Install and configure

Clone the Pi repository, then create `.env` from `.env.example`; never commit
`.env`. Configure a production HTTPS backend URL, `NUTRIBOX_CAMERA_ADAPTER=picamera2`,
and the mounted JC5 5 kg load cell as `NUTRIBOX_WEIGHT_ADAPTER=hx711` with BCM
data pin 5 and clock pin 6. BCM values are not physical header-pin numbers.

Run `scripts/setup_pi_camera.sh`. It creates or reuses `.venv-pi` with the
Raspberry Pi OS-managed Picamera2 and Pygame packages. Do not pip-install
Picamera2. Run `nutribox-pi preflight` before starting the UI; it reports only a
safe valid/invalid configuration result.

## Hardware validation

Run `scripts/run_camera_smoke_test.sh` and `scripts/run_touchscreen_smoke_test.sh`.
With the empty scale, run `nutribox-pi weight-tare`; then calibrate using a
verified reference mass with `nutribox-pi weight-calibrate --known-grams <grams>`.
Confirm `nutribox-pi weight-check --json` is stable. Calibration stores only
offset, factor, and schema version under the current user's private
configuration directory; it is not a repository file.

## Start the UI

Manual launch remains supported from the graphical-session user:

```bash
nutribox-pi ui
```

`scripts/run_device_ui.sh` is the graphical launcher. It uses the existing
Wayland session, validates configuration first, and takes a per-user runtime
lock so a second UI process cannot start.

For a reversible graphical-session autostart, run:

```bash
scripts/configure_ui_autostart.sh enable
```

This writes a user-level systemd unit under the invoking user's configuration
directory and enables it from `default.target`, which is the reliable active
Pi OS user target after reboot. The unit orders itself after the graphical and
network-online targets; the launcher waits at most 30 seconds for the existing
Wayland session before failing safely. It uses no sudo and does not hard-code a
username, display number, backend URL, or credential. Disable it with
`scripts/configure_ui_autostart.sh disable`; this also removes links created by
older graphical-session-target installs. Restart and inspect safe service logs
with:

```bash
systemctl --user restart nutribox-pi-ui.service
systemctl --user status nutribox-pi-ui.service
journalctl --user -u nutribox-pi-ui.service
```

## Supported workflows and privacy

Guests can capture, analyze, select or confirm food/ingredient/recipe results,
and view nutrition but cannot save meals. A verified paired device additionally
supports explicit Save Meal and Portion Analysis for saved meals. Pairing
revocation returns the Pi to guest mode and removes the device credential.
Navigation never saves a meal. The Pi stores no user bearer token; it never
renders credentials, identifiers, response bodies, or capture paths. Meal JPEGs
are temporary and are deleted after the workflow completes.

The instructional video remains unavailable unless an approved local media asset
is supplied. Reheating, user-profile editing, new analysis logic, backend
endpoints, and Web Companion changes are excluded from this Pi release.
