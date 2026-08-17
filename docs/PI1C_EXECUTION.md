# PI-1C Touchscreen Foundation

PI-1C validates the verified 800 x 480 WaveShare touchscreen through pygame on
Raspberry Pi OS `graphical.target`. It does not access the backend, network,
camera, application data, or any retained touch history.

## Prepare the Pi environment

Use the existing `.venv-pi`, which must expose system site packages. Install
the current local project without installing pygame from pip, then verify the
OS-managed pygame package:

```bash
.venv-pi/bin/python -m pip install .
.venv-pi/bin/python -c "import pygame; print(pygame.version.ver)"
```

The verified target uses pygame 2.6.1, an 800 x 480 display, and the WaveShare
WS170120 touch controller. PySide6 is not required.

## Run the smoke test

From a local graphical terminal or an SSH session owned by the same logged-in
desktop user, run:

```bash
scripts/run_touchscreen_smoke_test.sh
```

The launcher uses only `.venv-pi`. When graphical variables are absent during
SSH use, it selects a Wayland socket only from the invoking user's existing
runtime directory. It exits safely if no graphical session is available.

Touch the highlighted top-left, center, and bottom-right targets in order. A
touch outside the highlighted target does not advance. Completion shows PASS
briefly and exits 0. The always-visible Exit button, Escape, or window close
exits 1.

This is a manual foundation check only. It does not configure autostart,
systemd, kiosk mode, final screens, navigation, or integrations.
