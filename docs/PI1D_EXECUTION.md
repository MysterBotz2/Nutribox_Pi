# PI-1D / PI-2A Meal-Capture and Analysis UI

The touch-operated workflow uses the verified 800 x 480 Raspberry Pi display,
the existing Camera port, and the light-theme tokens in
`nutribox_design_system_spec.md`. PI-2A sends the reviewed temporary image and
simulated weight through the existing Controller and Backend ports. The UI does
not construct multipart requests or retain capture history.

## Prepare the existing Pi environment

Use the existing `.venv-pi`; do not create another environment. Install the
current local project, verify the OS-managed packages, and select the real
camera and backend settings in the existing `.env`:

```bash
.venv-pi/bin/python -m pip install .
.venv-pi/bin/python -c "import pygame, picamera2"
```

```dotenv
NUTRIBOX_CAMERA_ADAPTER=picamera2
NUTRIBOX_API_BASE_URL=http://backend-device-name-or-address:port
NUTRIBOX_HTTP_TIMEOUT_SECONDS=10
NUTRIBOX_SIMULATED_WEIGHT_GRAMS=250
```

Plain HTTP is permitted only for development on the controlled local network.
A production TLS policy remains unresolved and must be approved before
production deployment.

## Run the single manual validation

From a local graphical terminal or an SSH session owned by the logged-in
desktop user, run:

```bash
.venv-pi/bin/python -m nutribox_pi health
scripts/run_device_ui.sh
```

The launcher uses only `.venv-pi` and the invoking user's existing Wayland
session. It does not use sudo or configure startup behavior.

Validate Home, Capture, visible Capturing, Review, visible Analyzing, all four
documented result outcomes, Retake, Retry, Home, Back, and Exit behavior.
Confirm that the development simulated-weight notice is visible, review images
preserve their aspect ratio, and no meal image remains after analysis or exit.
