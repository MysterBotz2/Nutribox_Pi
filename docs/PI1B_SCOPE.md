# PI-1B Camera Foundation Scope

## Purpose and binding boundary

PI-1B establishes still-JPEG camera support for the standalone Nutri-Box
Raspberry Pi client. It adds a hardware-independent camera port, deterministic
simulation for PC/CI, a lazy Picamera2 adapter for the confirmed Raspberry Pi,
local camera diagnostics, explicit capture, and a manual hardware smoke test.

PI-1B preserves PI-0 and PI-1A. The backend remains a separate network service.
Camera commands must never contact the backend or any network endpoint, and
must not require backend configuration.

## Confirmed target environment

- Raspberry Pi 4 Model B
- Raspberry Pi Camera Module 3, detected by the `rpicam` tools
- Raspberry Pi OS / Debian 13 Trixie
- arm64 / aarch64
- Python 3.13.5
- System Python imports the OS-managed Picamera2 package
- The existing isolated project `.venv` does not import Picamera2

Picamera2 and libcamera remain OS-managed. They must not be listed in
`pyproject.toml`, installed or changed with pip, vendored, or copied into the
repository. PC and CI must import and test the project without Raspberry
Pi-only libraries.

## Deliverables

PI-1B is limited to:

1. A hardware-independent `Camera` port and result models.
2. A deterministic simulated camera adapter for PC/CI.
3. A Raspberry Pi adapter with lazy, optional Picamera2 imports.
4. Still JPEG capture at exactly 1920 x 1080.
5. Local camera availability, capture, validation, and cleanup diagnostics.
6. Manual Pi camera setup and smoke-test scripts and documentation.
7. A non-destructive `.venv-pi` migration path.
8. Normalized errors using the closed codes in this document.
9. Hardware-free automated tests and manual target-hardware verification.

## Camera-only configuration

Camera commands use a dedicated camera-only settings loader. They must not call
`Settings.from_env()` and must not read, validate, or require
`NUTRIBOX_API_BASE_URL`.

The required key is `NUTRIBOX_CAMERA_ADAPTER`. Its closed values are:

- `simulated`
- `picamera2`

There is no implicit default for a camera command. A missing, empty, or unknown
value produces `invalid_configuration` and exit 1. PC/CI tests explicitly set
`simulated`; the Pi smoke workflow explicitly sets `picamera2`.

## Hardware-independent camera port

The port exposes operations equivalent to:

- `availability() -> CameraAvailability`
- `capture(output_path: Path, overwrite: bool = False) -> CaptureResult`

No Picamera2, libcamera, camera-control, request, metadata, or enum type may
cross the port. Port models contain only standard-library types, paths, strings,
integers, booleans, and the authoritative error codes.

`availability()` lazily imports the selected adapter dependency and enumerates
cameras. It must not open, configure, capture from, or reserve a camera.

`CameraAvailability` always contains exactly:

- `available: bool`
- `code`: one authoritative code
- `message`: one fixed safe message
- `picamera2_version: str`
- `libcamera_version: str`

The real adapter supplies sanitized version identifiers or `unknown`. The
simulated adapter supplies `not-applicable` for both version fields.
Diagnostics receive this metadata only through the `Camera` port.

`CaptureResult` always contains exactly:

- `ok: bool`
- `code`: one authoritative code
- `message`: one fixed safe message
- `published: bool`
- `output_path: Path | None`
- `format: str | None`
- `width: int | None`
- `height: int | None`
- `byte_size: int | None`

On success, `ok` is true, code is `ok`, `published` is true,
`output_path` is the caller-owned destination, format is `jpeg`, width is
1920, height is 1080, and byte size is from 1 through 20 MiB inclusive.

On failure before publication, `ok` and `published` are false and
`output_path`, format, width, height, and byte size are all `None`.

On post-publication staging-cleanup failure, `ok` is false, code is
`cleanup_failed`, `published` is true, and `output_path` plus the validated
image metadata remain populated. Serializers still omit every path and
image-metadata field from the fixed failure JSON.

The adapter owns camera initialization, configuration, autofocus, capture,
validation, publication staging, and camera-resource release. A published
explicit capture belongs to the caller. Every staging file belongs to the
adapter, and its removal is attempted in the required cleanup path unless
publication already consumed its staging name. A normalized cleanup failure is
possible under the rules below. Only one operation may use an adapter instance
at a time; callers serialize camera operations.

## Capture format and encoded-JPEG validation

Output is JPEG at exactly **1920 x 1080 pixels**. PI-1B uses the
distribution-provided Picamera2 defaults for JPEG quality and color behavior
and does not override them.

The encoded staging file itself must be validated with a bounded,
standard-library JPEG-header inspector. Validation must not trust Picamera2
configuration, camera metadata, a result object, an extension, or a filename.

Validation requires:

- SOI marker
- EOI marker
- A recognized dimension-bearing Start of Frame marker: `0xC0`, `0xC1`,
  `0xC2`, `0xC3`, `0xC5`, `0xC6`, `0xC7`, `0xC9`, `0xCA`, `0xCB`, `0xCD`,
  `0xCE`, or `0xCF`
- Encoded width exactly 1920
- Encoded height exactly 1080
- Nonzero content
- Total encoded size no greater than 20 MiB

The inspector rejects files larger than 20 MiB, examines at most 1 MiB of
header data before locating a valid SOF marker, and processes at most 512
markers or segments. It validates every segment length before advancing and
reads the final two bytes separately to verify EOI. An exceeded bound,
malformed segment, missing SOI, SOF, or EOI, unsupported SOF, incorrect
dimensions, or empty data produces `invalid_image`.

No free-disk-space preflight is performed. Filesystem write and ENOSPC failures
are normalized without raw exception text.

## Camera Module 3 autofocus

Every real capture uses single-shot autofocus and a monotonic five-second
deadline:

1. Configure the 1920 x 1080 still stream.
2. Start the camera.
3. Trigger one autofocus cycle.
4. Poll autofocus state at least every 100 ms; no polling interval may be
   slower than 100 ms.
5. Treat `Focused` as success.
6. Treat `Scanning` as retryable progress until the deadline.
7. Treat `Idle` before or immediately after triggering as retryable until the
   deadline.
8. Treat `Failed` as terminal `autofocus_failed`.
9. Fail closed on any unknown state as `autofocus_failed`.
10. Return `autofocus_timeout` when the monotonic deadline expires.
11. Capture only after `Focused`.
12. Stop and close camera resources in guaranteed cleanup.

PI-1B permits no fixed-lens-position or manual-focus fallback. Autofocus failure
or timeout prevents capture and publication.

Camera resource release must finish before image validation or publication.
Camera stop or close failure maps to `cleanup_failed` with `Camera resource
cleanup failed.` and prevents publication. If capture and camera cleanup both
fail, `cleanup_failed` takes precedence. If camera cleanup and staging cleanup
both fail, the result is `cleanup_failed` with `Camera and private temporary
cleanup failed.` No destination is caller-owned in these cases because
publication has not occurred. Diagnostic temporary-file cleanup remains a
separate camera-check cleanup operation.

## Output-path validation

All validation occurs before camera initialization:

- Reject every path component containing a Unicode character in category `Cc`
  or `Cf`. This includes NUL, carriage return, line feed, escape,
  terminal-control, bidirectional-control, and invisible formatting characters.
- Require a leaf name ending in `.jpg` or `.jpeg`, case-insensitively.
- Require an existing writable parent directory; never create parents.
- Reject a symbolic link in every existing path component, including the
  destination.
- Reject an existing destination that is not a regular file.
- With `overwrite=False`, refuse every existing destination.
- With `overwrite=True`, replace only an existing regular, non-symlink file;
  an absent destination is also allowed.

Parent-component symlink checks are pre-publication validation for a trusted,
single-user appliance. PI-1B does not claim resistance to an adversary
concurrently replacing parent directories. Destination no-clobber behavior
must nevertheless remain race-safe.

Relative paths are interpreted from the caller's current working directory.
No repository, home, or username path is hard-coded. Safe results, errors,
serializers, and logs do not include directories, resolved absolute paths, or
temporary paths. Human output renders a successful basename using deterministic
JSON-string escaping and quotation. JSON output uses normal JSON escaping.

## Atomic publication and temporary ownership

The adapter creates a unique staging file with mode 0600 in the destination's
parent directory so staging and destination are on the same filesystem. For an
adapter-owned writable stream, the exact order is write, flush, fsync, then
close. For Picamera2 path-based capture, the adapter waits for `capture_file`
to complete and release its writer, reopens the staging file without following
symlinks, fsyncs the reopened descriptor, closes it, and only then validates
and publishes.

On Linux, fsync of the completed staging file is mandatory before publication.
On other supported PC/CI platforms, fsync is used when supported. Any
pre-publication open, flush, fsync, or close failure maps to
`publication_failed`, prevents validation and publication, and leaves no
caller-owned destination.

For `overwrite=False`:

1. Publish with `os.link(staging, destination, follow_symlinks=False)`.
2. The destination immediately becomes caller-owned after the link succeeds.
3. Unlink the private staging name after the link succeeds.
4. If unlinking fails, make one bounded additional attempt to remove only the
   staging name. Never delete or roll back the published destination.
5. If that attempt also fails, return `cleanup_failed` with `Image was
   published, but private temporary cleanup failed.` The requested destination
   exists even though the CLI exits 1; neither path is printed.
6. Map `EEXIST` to `output_exists`.
7. If hard-link publication is unsupported, return `publication_failed`.
8. Never weaken no-clobber behavior with a precheck followed by `os.replace`.

For `overwrite=True`, publish the validated staging file with `os.replace`.
After it succeeds, the staging name no longer exists and requires no staging
unlink. For failures before publication, no destination becomes caller-owned,
staging cleanup is attempted in a `finally` path, and cleanup failure uses
`Private temporary cleanup failed.` Publication failure leaves an existing
destination unchanged except for the explicitly permitted atomic replacement
case.

PI-1B does not fsync the parent directory and does not promise survival across
sudden power loss immediately after publication. It guarantees atomic
visibility, not full crash durability. No post-publication directory-fsync
failure can occur.

Linux capture files must be mode 0600 and private temporary directories mode
0700. On other PC/CI platforms, numeric POSIX modes are not required where
unsupported; the destination must be a regular non-symlink file, temporary
resources must be cleaned, and publication and overwrite semantics still hold.

The creator owns every temporary artifact:

- The adapter owns its staging file and performs the bounded cleanup attempts
  defined above.
- Camera-check owns and cleans its diagnostic image and private directory.
- The caller owns only a successfully published explicit capture.
- Cleanup failure maps to `cleanup_failed`, fails the operation or diagnostic,
  and never reveals a path.

No persistent image history is permitted.

## Camera diagnostics

The command is `nutribox-pi camera-check [--json]`. Camera-check is entirely
local and must not instantiate a backend adapter, call `GET /api/health`, call
`POST /api/meals/analyze`, or contact any network service.

Camera-check:

1. Creates a private mode-0700 temporary directory.
2. Calls `availability()`.
3. Passes a nonexistent `capture.jpg` inside that directory to
   `capture(..., overwrite=False)`.
4. Exercises initialization, five-second autofocus, capture, and encoded-JPEG
   validation.
5. Independently verifies the encoded dimensions using the same bounded
   standard-library inspector.
6. Deletes the image and temporary directory before reporting success.

Availability failure skips capture but still runs cleanup reporting. Any image
or directory cleanup failure produces `cleanup_failed` and a failed result.
Camera-check never reports a temporary path and never retains an image.

The fixed JSON contract is:

```json
{
  "command": "camera-check",
  "ok": true,
  "camera_stack": {
    "picamera2_version": "unknown",
    "libcamera_version": "unknown"
  },
  "checks": [
    {
      "name": "availability",
      "status": "pass",
      "code": "ok",
      "message": "Camera is available."
    },
    {
      "name": "capture",
      "status": "pass",
      "code": "ok",
      "message": "Camera capture passed."
    },
    {
      "name": "cleanup",
      "status": "pass",
      "code": "ok",
      "message": "Temporary image cleanup passed."
    }
  ]
}
```

`command`, `ok`, `camera_stack`, and `checks` are exactly the four
top-level fields; no optional or additional top-level fields are permitted.
`camera_stack` contains exactly `picamera2_version` and
`libcamera_version`. Check order is fixed as `availability`, `capture`,
`cleanup`. Each check always contains exactly
`name`, `status`, `code`, and `message`. Status is one of `pass`,
`fail`, or `skipped`; code is from the authoritative set. A skipped check
uses `skipped`. Human output is rendered from this same result and preserves
the same order, status, code, and fixed message.

Both adapters use `Camera is available.` for `availability/pass/ok`. Camera
capability and enumeration, not version metadata, determine availability.
Picamera2 and libcamera version identifiers are diagnostic metadata only. A
safe identifier is ASCII, 1 through 64 characters, and contains only letters,
digits, period, underscore, plus, hyphen, tilde, or colon. A missing,
unavailable, or unsafe identifier becomes the literal `unknown` and does not
make an otherwise working camera unavailable. Raw module values, object
representations, exceptions, and filesystem information are never substituted.
The simulated adapter supplies the literal `not-applicable` for both fields.

The exact success and skip messages are:

- availability/pass/`ok`: `Camera is available.`
- capture/pass/`ok`: `Camera capture passed.`
- cleanup/pass/`ok`: `Temporary image cleanup passed.`
- capture/skipped/`skipped`: `Capture skipped because camera availability failed.`
- cleanup/skipped/`skipped`: `Cleanup skipped because no temporary resources were created.`

Transitions are fixed:

1. Configuration, dependency, enumeration, or availability failure makes
   availability `fail` with its authoritative code, capture `skipped`, and
   cleanup `skipped`.
2. If availability passes but private temporary-resource creation fails,
   capture is `fail`/`capture_failed` and cleanup is `skipped`.
3. Once temporary resources exist, cleanup is always attempted regardless of
   capture success or failure. Capture may fail with its applicable
   authoritative code.
4. Successful cleanup after failed capture is cleanup `pass`/`ok`, but
   top-level `ok` remains false. Cleanup failure is
   `fail`/`cleanup_failed`.
5. Top-level `ok` is true only when all three checks pass. Any failed or
   causally skipped check makes it false.

Human-readable camera-check output uses exactly this order, capitalization,
spacing, separators, and line structure. Values inside double quotes use
deterministic JSON-string escaping:

```text
Nutri-Box camera check
Camera stack:
- picamera2_version: "<escaped value>"
- libcamera_version: "<escaped value>"
Checks:
- availability: PASS|FAIL|SKIPPED [<code>] - <message>
- capture: PASS|FAIL|SKIPPED [<code>] - <message>
- cleanup: PASS|FAIL|SKIPPED [<code>] - <message>
Overall: PASS|FAIL
```

## Explicit camera capture

The command is:

- `nutribox-pi camera-capture OUTPUT [--overwrite] [--json]`

On success, JSON is exactly:

```json
{
  "command": "camera-capture",
  "ok": true,
  "code": "ok",
  "message": "Image captured.",
  "file_name": "meal.jpg",
  "format": "jpeg",
  "width": 1920,
  "height": 1080
}
```

`file_name` is the safe basename only. The corresponding failure object is:

```json
{
  "command": "camera-capture",
  "ok": false,
  "code": "capture_failed",
  "message": "Camera capture failed."
}
```

Failure objects contain exactly `command`, `ok`, `code`, and `message`. `code`
is an authoritative non-`ok` code and `message` is its fixed safe message. They
never contain `file_name`, output or temporary paths, format, width, height, raw
exceptions, or optional fields. Human output is generated from the same result.
Successful human output is exactly:

```text
Nutri-Box camera capture
Status: PASS
Code: ok
Message: Image captured.
File: "<escaped basename>"
Format: jpeg
Dimensions: 1920x1080
```

Runtime failure human output is exactly:

```text
Nutri-Box camera capture
Status: FAIL
Code: <authoritative code>
Message: <fixed message>
```

Failure output never contains a filename or path. CLI usage errors remain on
stderr with exit code 2.

## CLI exit behavior

- Exit 0 means camera-check, including cleanup, completely passed or an explicit
  capture was validated and atomically published.
- Exit 1 means normalized configuration, dependency, availability, contention,
  initialization, autofocus, path, capture, validation, publication, or cleanup
  failure.
- Exit 2 means an argparse usage error.

The existing `health`, `diagnostics`, and `diagnostics --json` commands,
outputs, network behavior, and exit codes remain unchanged.

## Authoritative error codes

The closed set is:

- `ok`
- `skipped`
- `invalid_configuration`
- `dependency_unavailable`
- `camera_unavailable`
- `camera_busy`
- `camera_initialization_failed`
- `autofocus_failed`
- `autofocus_timeout`
- `invalid_output`
- `output_exists`
- `capture_failed`
- `invalid_image`
- `publication_failed`
- `cleanup_failed`

Every configuration, import, feature-detection, enumeration, initialization,
contention, autofocus, path, capture, validation, publication, and cleanup
failure maps to exactly one code. No other code may be emitted. Messages use
these fixed templates and never include raw exception text,
configuration values, absolute paths, usernames, or device identifiers:

| Code | Message |
| --- | --- |
| `ok` for camera-check availability | `Camera is available.` |
| `ok` for camera-check capture | `Camera capture passed.` |
| `ok` for camera-check cleanup | `Temporary image cleanup passed.` |
| `ok` for explicit capture | `Image captured.` |
| `skipped` for camera-check capture | `Capture skipped because camera availability failed.` |
| `skipped` for camera-check cleanup | `Cleanup skipped because no temporary resources were created.` |
| `invalid_configuration` | `Camera configuration is invalid.` |
| `dependency_unavailable` | `Required camera support is unavailable.` |
| `camera_unavailable` | `Camera is unavailable.` |
| `camera_busy` | `Camera is busy.` |
| `camera_initialization_failed` | `Camera initialization failed.` |
| `autofocus_failed` | `Camera autofocus failed.` |
| `autofocus_timeout` | `Camera autofocus timed out.` |
| `invalid_output` | `Capture output is invalid.` |
| `output_exists` | `Capture output already exists.` |
| `capture_failed` | `Camera capture failed.` |
| `invalid_image` | `Captured image is invalid.` |
| `publication_failed` | `Image publication failed.` |
| `cleanup_failed` for camera resource release | `Camera resource cleanup failed.` |
| `cleanup_failed` for camera and staging cleanup | `Camera and private temporary cleanup failed.` |
| `cleanup_failed` for camera-check | `Temporary image cleanup failed.` |
| `cleanup_failed` before explicit-capture publication | `Private temporary cleanup failed.` |
| `cleanup_failed` after explicit-capture publication | `Image was published, but private temporary cleanup failed.` |

This table covers every authoritative code with its complete
operation-specific mapping. Adapter-supplied text is never passed through.

Mapping rules:

- Missing/invalid adapter configuration: `invalid_configuration`
- Missing Picamera2 or required API: `dependency_unavailable`
- Exception during camera enumeration: `camera_initialization_failed`
- Enumeration succeeds but finds no usable camera: `camera_unavailable`
- Camera is reserved or reports contention: `camera_busy`
- Open/configure/start failure: `camera_initialization_failed`
- Terminal/unknown focus state: `autofocus_failed`
- Five-second focus deadline: `autofocus_timeout`
- Invalid path, parent, extension, symlink, or file type: `invalid_output`
- Existing destination with no overwrite or publication `EEXIST`:
  `output_exists`
- Camera request or encoded write failure, including ENOSPC: `capture_failed`
- Invalid, oversized, or wrong-dimension JPEG: `invalid_image`
- Atomic link/replace/fsync publication failure: `publication_failed`
- Camera stop or close failure: `cleanup_failed`, with precedence over a
  capture failure and before validation or publication
- Camera and staging cleanup both fail: `cleanup_failed`, using the combined
  fixed message
- Temporary image, staging file, or directory removal failure:
  `cleanup_failed`

## Picamera2 compatibility and lazy imports

The real adapter supports the OS-managed Picamera2/libcamera versions supplied
by the confirmed Raspberry Pi OS Trixie arm64 target. It does not pin or
pip-install them.

Importing `nutribox_pi`, its ports, models, CLI, general diagnostics, or the
simulated adapter must not import Picamera2. Only construction or first use of
the explicitly selected real adapter may import it.

The adapter feature-detects every required Picamera2/libcamera API before camera
enumeration or initialization. Missing imports or required APIs produce
`dependency_unavailable`. Availability diagnostics record package/API version
identifiers only after the safe-identifier validation above; missing or
rejected values become `unknown`. They never record module paths, absolute
paths, raw object representations, or exception text. Manual target
verification remains required.

## Deterministic simulated adapter

The simulated adapter implements the identical port, path validation,
publication, ownership, permission, JPEG inspection, and cleanup contracts. It
uses a packaged synthetic, non-personal JPEG fixture whose encoded dimensions
are exactly 1920 x 1080 and whose bytes and result metadata are identical for
the same request on every supported PC/CI environment.

It imports no Raspberry Pi library, probes no device or service, uses no
network, and creates no persistent history.

## Pi environment setup and migration

The camera setup script is `scripts/setup_pi_camera.sh`. It:

1. Requires Linux and arm64/aarch64.
2. Verifies system Python imports Picamera2 before creating or installing
   anything.
3. Inspects an existing `.venv` only by running its Python in a subprocess;
   it reports compatibility without modifying, deleting, replacing, renaming,
   or installing into it.
4. Creates `.venv-pi` only with:

   ```bash
   python3 -m venv --system-site-packages .venv-pi
   ```

5. Reuses a compatible existing `.venv-pi`.
6. Requires an existing `.venv-pi/pyvenv.cfg` to state
   `include-system-site-packages = true`.
7. Stops with a fixed actionable failure when `.venv-pi` is incomplete,
   malformed, lacks its interpreter, lacks the required setting, or cannot
   import Picamera2. It never automatically deletes or recreates it.
8. Installs only the local Nutri-Box project and declared non-Pi dependencies.
9. Verifies `.venv-pi` imports both `nutribox_pi` and `picamera2`.

The script is idempotent for a compatible `.venv-pi`. It uses no `sudo`,
does not install Debian packages, never installs Picamera2 with pip, does not
modify global Python, and does not create or overwrite `.env`.

`.venv-pi/` and the exact repository-root rule `/.camera-smoke/` must be
added to `.gitignore`. Repository-hygiene tests apply to the documented
`.camera-smoke/` workflow, not to every arbitrary caller-selected JPEG.
Synthetic automated JPEG fixtures must not use the ignored smoke directory.
They may be generated in test temporary directories or stored in a non-JPEG
encoded representation such as Base64.

Existing PI-1A setup and diagnostic scripts keep their current behavior and
continue to use `.venv`. PC setup never creates `.venv-pi`.

## Manual smoke-test script and environment selection

The smoke-test script is `scripts/run_camera_smoke_test.sh`. It resolves the
repository relative to its own location so it works from any current directory.
It requires `.venv-pi/bin/python`, validates that environment, and never falls
back to `.venv`, system Python, or another interpreter.

It requires `NUTRIBOX_CAMERA_ADAPTER=picamera2`, either already exported or
loaded from the repository's existing `.env` without overwriting it. Missing
or different selection fails safely.

The documented manual sequence is:

1. Run `scripts/setup_pi_camera.sh`.
2. Configure `NUTRIBOX_CAMERA_ADAPTER=picamera2`.
3. Run `scripts/run_camera_smoke_test.sh` and require camera-check success.
4. Create the private smoke directory with
   `install -d -m 700 .camera-smoke`.
5. Capture with `.venv-pi/bin/nutribox-pi camera-capture
   .camera-smoke/pi1b-smoke.jpg`.
6. Verify success, JPEG format, encoded 1920 x 1080 dimensions, and Linux mode
   0600.
7. Repeat without `--overwrite` and require exit 1 with `output_exists`
   while preserving the original byte for byte.
8. Repeat with `--overwrite` and require exit 0 with a valid replacement.
9. Delete the image and `.camera-smoke` directory before recording completion.

The smoke workflow does not upload, analyze, retain, or transmit the image.

## Privacy and security

Meal images are sensitive. Explicit camera-capture files exist only at the
caller-selected destination and remain caller-owned. `CaptureResult` may carry
the path internally for ownership, but serializers and logs expose only a safe
basename on success and no destination on failure.

Camera-check images are private temporary data and are deleted before success.
No captured image may be logged, embedded in JSON, cached, indexed, uploaded,
added to telemetry, or retained as history. Automated fixtures are synthetic
and non-personal.

Output and logs must not expose:

- Raw Picamera2, libcamera, Python, or filesystem exceptions
- Absolute or temporary paths
- Usernames or home directories
- Configuration values, credentials, or tokens
- Camera serial numbers, MAC addresses, or network identifiers
- Captured bytes or image contents

Automated redaction tests inject secret-like exception messages and sensitive
paths into every failure category and assert they are absent from result
objects, JSON, human output, logs, stdout, and stderr.

Manual evidence is recorded only in `docs/PI1B_HARDWARE_VALIDATION.md`, and
only after the captured smoke image and `.camera-smoke` directory are deleted.
It contains only OS codename, architecture, Python version, sanitized Picamera2
version or `unknown`, sanitized libcamera version or `unknown`, sensor family
such as IMX708, camera-check pass/fail, capture pass/fail, encoded width and
height, no-overwrite pass/fail, overwrite pass/fail, and cleanup confirmation.
It never records captured images, absolute paths, usernames, hostnames, IP or
MAC addresses, tokens, credentials, or raw exceptions.

## Automated testing requirements

All automated tests run without camera hardware, Picamera2, libcamera, device
probing, or real network access. Tests cover:

- Camera port models containing no Raspberry Pi-specific types, exact
  `CameraAvailability` metadata, and exact `CaptureResult` invariants
- Required camera-only configuration and independence from backend settings
- Closed adapter values with no implicit default
- Deterministic simulated JPEG bytes and encoded 1920 x 1080 dimensions
- The exact 20 MiB file, 1 MiB header, and 512-marker JPEG-inspector bounds,
  including valid, malformed, truncated, oversized, wrong-marker, and
  wrong-dimension synthetic JPEGs
- Lazy Picamera2 import and required-API feature detection
- Availability enumeration without opening or reserving a camera, including
  deterministic exception and no-compatible-camera mappings
- Exact autofocus state transitions, 100 ms polling bound, five-second
  monotonic deadline, terminal failures, and no focus fallback
- Every output component, parent, symlink, type, extension, and overwrite rule
- Rejection of every `Cc` and `Cf` path character and deterministic quoted
  JSON-string escaping of the basename in human output
- Race-safe `os.link` no-clobber behavior, EEXIST, unsupported hard links, and
  existing-file preservation
- Atomic overwrite behavior; staging cleanup after every failure point; and
  the bounded second unlink attempt, caller ownership, exit 1, and fixed
  message after post-publication cleanup failure
- Camera stop/close completion before validation or publication, cleanup-code
  precedence, combined camera/staging cleanup failure, and no destination
  ownership in those cases
- Mandatory Linux staging-file fsync, supported-platform fsync behavior,
  pre-publication fsync failure, and absence of parent-directory fsync
- Exact Linux mode 0600 files and 0700 directories; on other platforms,
  regular-file, non-symlink, cleanup, publication, and overwrite behavior
- ENOSPC and all normalized error mappings
- Camera-check image/directory cleanup on success, failure, and cancellation
- Fixed JSON schemas, closed camera-check top-level fields, camera-stack
  metadata supplied only through the port, sanitization to `unknown`,
  simulated `not-applicable` values, every camera-check transition, exact
  human layouts, safe basename output, and CLI exit codes 0, 1, and 2
- Proof that camera commands instantiate no backend and make no network call
- Imports succeeding without Raspberry Pi libraries
- `.venv-pi` detection, idempotency, no fallback, and exact
  `/.camera-smoke/` repository hygiene
- Unchanged PI-0 and PI-1A commands, outputs, exit codes, and tests

## Acceptance criteria

PI-1B is accepted when:

- The hardware-independent port and simulated adapter satisfy this contract.
- `CameraAvailability` supplies camera-stack metadata only through the port,
  and `CaptureResult` satisfies its exact pre- and post-publication invariants.
- PC/CI imports and tests pass without Picamera2 or camera hardware.
- Camera commands require valid camera-only configuration and never require
  backend configuration.
- Camera commands instantiate no backend and make no network request.
- Picamera2 is imported only when `picamera2` is explicitly selected.
- Missing imports/APIs fail safely with `dependency_unavailable`.
- Encoded automated fixtures and manually captured images independently verify
  as JPEG, 1920 x 1080, nonempty, and no larger than 20 MiB.
- Real Camera Module 3 capture passes the exact autofocus state/deadline rules.
- Output validation, race-safe no-clobber, atomic overwrite, permissions,
  failure preservation, defined cleanup attempts, and cleanup-failure behavior
  pass.
- Camera-check removes its image and directory before returning success.
- Every failure uses exactly one authoritative code and fixed redacted message.
- Enumeration and camera-resource cleanup use the exact mapping, precedence,
  ownership, and publication-prevention rules.
- Camera-stack metadata uses safe identifiers or `unknown` without affecting
  otherwise successful camera availability.
- Human and JSON output satisfy the fixed contracts and matching exit codes.
- `scripts/setup_pi_camera.sh` non-destructively creates or reuses a compatible
  `.venv-pi` and never changes `.venv` or OS-managed Picamera2.
- `scripts/run_camera_smoke_test.sh` uses only `.venv-pi` with no fallback.
- Manual target verification records only the allowlisted fields in
  `docs/PI1B_HARDWARE_VALIDATION.md` and only after smoke-artifact deletion.
- Existing PI-0 and PI-1A behavior and tests remain unchanged.
- No excluded feature is introduced.

Required automated verification:

```bash
pytest
ruff check .
bash -n scripts/setup_pi.sh
bash -n scripts/run_diagnostics.sh
bash -n scripts/setup_pi_camera.sh
bash -n scripts/run_camera_smoke_test.sh
git diff --check
```

Required manual Raspberry Pi verification:

```bash
rpicam-hello --list-cameras
python3 -c "import picamera2"
scripts/setup_pi_camera.sh
.venv-pi/bin/python -c "import nutribox_pi, picamera2"
NUTRIBOX_CAMERA_ADAPTER=picamera2 .venv-pi/bin/python -m nutribox_pi camera-check
NUTRIBOX_CAMERA_ADAPTER=picamera2 .venv-pi/bin/python -m nutribox_pi camera-check --json
scripts/run_camera_smoke_test.sh
```

The smoke-test documentation must include camera-capture commands for
no-overwrite, expected refusal, explicit overwrite, encoded-dimension
inspection, permission inspection, and explicit deletion.

## PI-0 and PI-1A compatibility

- Existing backend ports and HTTP endpoints are unchanged.
- Camera commands do not use the backend port or backend settings.
- Existing `health`, `diagnostics`, and `diagnostics --json` output and
  exits are unchanged.
- Existing `.venv`, `scripts/setup_pi.sh`, and
  `scripts/run_diagnostics.sh` behavior is unchanged.
- Existing tests remain and must pass.
- Picamera2 remains absent from project dependencies and general import paths.
- No trusted `user_id` or recognition-confidence concept is introduced.

## Explicit exclusions

PI-1B does not include:

- Touchscreen UI or image preview
- Video capture or continuous streaming
- Food recognition, nutrition inference, or AI on the Pi
- Automatic backend upload or analysis calls
- Persistent image history
- GPIO, load cells, temperature sensors, or heating
- Pairing, authentication, profiles, synchronization, or telemetry
- systemd services or automatic startup
- Backend, database, or companion-application changes

## Remaining non-blocking decisions

No unresolved decision may alter PI-1B implementation. The following are
explicitly deferred beyond PI-1B and do not change this milestone:

- Product-specific exposure, lighting, rotation, and visual-quality tuning
- Reassessment of resolution after representative meal-image research
- A future UI-controlled restricted output root
- Retention and upload policy for a future, separately scoped backend workflow
- Adding camera status to the general PI-1A diagnostics command

PI-1B uses distribution JPEG defaults, 1920 x 1080, separate camera commands,
local-only images, and the contracts above regardless of those future choices.
