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

## PI-3B2 capture confirmation

Desktop simulation and Raspberry Pi Camera Module 3 use the same explicit
sequence: Start Processing → live preview → Capture Meal → frozen Captured Meal
Preview → Yes → Analyzing → the existing backend-defined result. Windows uses
the existing simulated-camera adapter; it is labeled as simulated and is never
presented as live hardware footage. Raspberry Pi construction remains lazy and
continues through the existing Picamera2 adapter and preview-session port.

The validated read-only weight is sampled once after the JPEG is successfully
captured. That exact snapshot is displayed beside the frozen image and sent as
`weight_grams`; confirmation never rereads the sensor. There is no manual weight
entry and no HX711 support in this checkpoint.

No/Retake securely removes the rejected JPEG, clears its weight, and opens one
new preview session. Back stops preview, removes the owned temporary JPEG,
clears capture/analysis state, and returns to Start Processing. Home, Exit,
capture failure, malformed responses, successful analysis, and confirmed
device revocation apply the same ownership-aware cleanup. Retryable network
failures retain the frozen capture only until another explicit Retry/Confirm or
cleanup action; they never submit automatically.

Anonymous analysis sends no device header. Verified paired analysis sends only
the existing `X-Device-Token`; the renderer never receives it and no
`Authorization` header is used. Ingredient continuation UI and Save Meal
changes remain outside PI-3B2.

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

## PI-3B3-A1 continuation transport boundary

The typed backend boundary now recognizes exactly these initial-analysis
outcomes: `calculated`, `food_not_recognized`,
`nutrition_reference_not_found`, `requires_food_selection`,
`requires_ingredient_verification`, and `requires_recipe_confirmation`.

It integrates these continuation routes only at the adapter boundary:

- `POST /api/meals/analysis-sessions/{analysis_session_id}/selections`
- `PUT /api/meals/analysis-sessions/{analysis_session_id}/components/{component_id}/ingredients`
- `POST /api/meals/analysis-sessions/{analysis_session_id}/components/{component_id}/ingredients/selections`
- `POST /api/meals/analysis-sessions/{analysis_session_id}/components/{component_id}/use-recipe`
- `POST /api/meals/analysis-sessions/{analysis_session_id}/components/{component_id}/review-recipe`
- `POST /api/meals/analysis-sessions/{analysis_session_id}/components/{component_id}/analyze-as-new`

Paired requests use exactly `X-Device-Token`; anonymous requests omit that
header. The Pi never sends `Authorization` or Bearer credentials. Credentials
and analysis-session identifiers are kept in memory only and are never
rendered or logged. A device-authentication 401 remains distinguishable for
the future revocation transition. HTTP 503/504, timeouts, and network failures
remain retryable safe failures.

Ingredient UI remains deferred to PI-3B3-B, and explicit Save Meal remains a
later checkpoint.

## PI-3B3-A2 continuation orchestration

PI-3B3-A2 introduces a hardware-independent, in-memory continuation workflow.
It is the sole owner of the active typed analysis response and its backend
session data; the renderer receives no session, component, candidate, or
credential identifiers.  The workflow represents each of the six typed backend
outcomes explicitly, as well as idle, request-in-progress, retryable-error,
terminal-error, revoked, and cancelled orchestration states.

Typed food-selection, ingredient-update, ingredient-candidate, recipe-use,
recipe-review, and component-as-new actions are permitted only for the matching
current response and backend-issued identifiers.  They are fenced against
duplicate and stale completions.  Session state is memory-only and is cleared
on a new analysis, Home, Retake, cancellation, revocation, Exit, and terminal
completion where it is no longer needed.

Each continuation obtains the current verified device credential immediately
before its adapter request.  It is passed only as `X-Device-Token` and is never
stored with session state, rendered, or logged.  A confirmed 401 revokes the
pairing and clears the active continuation.  HTTP 503/504, timeout, and network
failures retain the typed pre-request response for one explicit safe Retry,
which obtains the credential again.  Pygame ingredient screens remain PI-3B3-B;
explicit Save Meal remains a later checkpoint.

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

## Explicit paired-meal saving

For a paired device, validate the complete path: Pair → Capture → Analyze →
Continue/Confirm → Calculate → Save Meal → verify the meal in Web Companion.
Save Meal is always explicit; navigation, Retake, Home, and Exit never save a
meal. Anonymous analysis cannot be saved to an account. The backend derives
ownership from `X-Device-Token`; the Pi stores no user bearer token. If saving
reports an uncertain status, check Web Companion before attempting another
save.
