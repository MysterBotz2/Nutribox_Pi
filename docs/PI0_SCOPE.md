# Nutri-Box Raspberry Pi — PI-0 Scope

## Binding boundary

PI-0 establishes an online-only Python foundation for a standalone Nutri-Box
client running on a Raspberry Pi 4 Model B. The available device hardware is a
Camera Module 3 and a touchscreen. They are documented targets only in PI-0;
no camera or touchscreen implementation is included.

The v1 backend is the only external system used by PI-0:

- `GET /api/health`
- `POST /api/meals/analyze`, multipart form data containing exactly `file` and
  `weight_grams`

The supported analysis statuses are:

- `calculated`
- `food_not_recognized`
- `requires_food_selection`
- `nutrition_reference_not_found`

The device must not fabricate, request, validate, or depend on a recognition-
confidence score. It must never submit a trusted `user_id`.

PI-0 includes configuration, hardware and network ports, simulated weight and
temperature adapters, an HTTP adapter for the two known v1 endpoints, a small
controller, and a CLI backend-health check.

## Explicitly excluded

- Picamera2 and camera capture
- Touchscreen or other graphical UI
- GPIO and real sensor drivers
- Heating control
- User profiles
- Pairing and authentication
- Synchronization and telemetry
- Meal persistence or offline queues
- Offline operation

Known future heating choices are 60, 65, 70, 75, and 80 °C, with timers of 5,
10, 15, and 20 minutes. These values are requirements context only. Heating and
GPIO must not be implemented until approved electrical and thermal safety
specifications exist.

## Ownership boundary

The Pi owns local orchestration and presentation around simulated measurements
in PI-0. The backend owns health reporting, food recognition, food-selection
decisions, nutrition-reference resolution, and nutrition calculation. The Pi
passes only the meal image and measured weight to analysis and interprets only
the documented statuses.

## Unresolved decisions

The following decisions are intentionally not guessed:

- Backend deployment URL, TLS requirements, and production timeout policy.
- Exact health-response and meal-analysis response schemas beyond HTTP success
  and the four documented analysis statuses.
- Meaning and response workflow for `requires_food_selection`, including the
  endpoint used to submit a selection.
- Backend error-envelope schema and whether responses use stable error codes.
- Maximum image size, accepted image formats, and multipart filename rules.
- Retry and idempotency policy for meal analysis.
- Camera capture, preview, orientation, resolution, and image-quality rules.
- Touchscreen resolution, kiosk lifecycle, navigation, and accessibility rules.
- Real load-cell and temperature-sensor models, calibration, accuracy, sampling,
  and failure behavior.
- GPIO allocation and electrical interface specifications.
- Heater switching hardware, independent thermal cutoff, maximum operating
  temperature, watchdogs, interlocks, emergency stop, and all other safety
  requirements.
- Whether temperature is informational before heating is implemented and where
  it will eventually be displayed.
- Device identity and any future account association. A device-originated
  `user_id` must never be treated as trusted.
- Data privacy, retention, and deletion rules for uploaded meal images.

