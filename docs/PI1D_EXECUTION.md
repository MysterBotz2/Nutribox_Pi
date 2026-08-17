# PI-1D Local Meal-Capture UI

PI-1D is a local-only, touch-operated capture workflow for the verified
800 x 480 Raspberry Pi display. It uses the existing Camera port and the exact
light-theme tokens in `nutribox_design_system_spec.md`. It does not contact the
backend or network, analyze food, upload images, or retain capture history.

## Prepare the existing Pi environment

Use the existing `.venv-pi`; do not create another environment. Install the
current local project, verify the OS-managed packages, and select the real
camera adapter in the existing `.env`:

```bash
.venv-pi/bin/python -m pip install .
.venv-pi/bin/python -c "import pygame, picamera2"
```

```dotenv
NUTRIBOX_CAMERA_ADAPTER=picamera2
```

`NUTRIBOX_API_BASE_URL` is not required by the UI.

## Run the single manual validation

From a local graphical terminal or an SSH session owned by the logged-in
desktop user, run:

```bash
scripts/run_device_ui.sh
```

The launcher uses only `.venv-pi` and the invoking user's existing Wayland
session. It does not use sudo or configure startup behavior.

Validate Home, Capture, visible Capturing, Review, Retake, Done, Back, Retry,
and Exit behavior. Confirm that review images preserve their aspect ratio and
that no meal image remains after leaving Review or exiting the UI.
