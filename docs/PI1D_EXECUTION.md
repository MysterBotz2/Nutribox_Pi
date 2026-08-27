# PI-1D / PI-2A Meal-Capture and Analysis UI

## PI-3B1 desktop simulation and startup shell

The client now uses an exact 800 x 480 logical canvas. Native Windows runs in
an 800 x 480 window; Raspberry Pi/Linux retains fullscreen mode. For Windows,
use the repository's `.venv-windows` environment and install Pygame there:

```powershell
.\.venv-windows\Scripts\python.exe -m pip install pygame
.\.venv-windows\Scripts\python.exe -m nutribox_pi ui
```

Mouse input follows the same action and stale-event fencing as touchscreen
input. The startup flow displays real local loading milestones, always asks for
English or Tagalog, optionally shows the instructional shell, and then opens
Start Processing. PI-3B1 provides only a navigable media-unavailable shell; it
does not decode or play video.

UI preferences are stored atomically in
`~/.config/nutribox-pi/ui-preferences.json` (the corresponding user profile
directory on Windows). The allowlist contains only schema version, language,
and the show-intro boolean. It contains no device credential, owner identity,
backend URL, image, or meal data and is separate from `device-token.json`.

The touch-operated workflow uses the verified 800 x 480 Raspberry Pi display,
the existing Camera and preview-session ports, and the light-theme tokens in
`nutribox_design_system_spec.md`. The active UI sends the reviewed temporary
JPEG and the controller-provided measured weight to `POST /api/meals/analyze`
through the existing Backend/Controller boundary. The UI does not construct
multipart requests or retain capture history. The dedicated FoodRecognizer
adapter remains available only for future identification-only use and is not
called by Analyze Meal.

On the Capture screen, the Camera Module 3 provides a local 640 x 360 live
preview. The preview is not recorded, streamed, or written to disk. The same
camera session performs the bounded autofocus and 1920 x 1080 JPEG still
capture when Capture is pressed.

Analysis displays the four documented result variants. Calculated results show
the matched food, measured weight, returned primary nutrition values, and a
clear simulated-recognition label when applicable. A simulated-weight notice
is shown only when the supplied weight adapter is simulated. Food-selection
results list the returned candidates without inventing nutrition.

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

Validate Home, then tap Analyze Meal and confirm a live, proportional preview
appears before capture. Confirm Back stops the preview, Capture shows its
visible Capturing state, and Review follows the 1920 x 1080 still capture.
Confirm Retake starts a new preview session. Then validate visible Analyzing,
all four analysis outcomes, source labeling, Home, and Exit behavior. Review
images preserve their aspect ratio, and no meal image remains after analysis
or exit.
