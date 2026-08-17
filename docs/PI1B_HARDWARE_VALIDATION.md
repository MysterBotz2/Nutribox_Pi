# PI-1B Hardware Validation

Run this manual workflow from the repository root on the supported Raspberry
Pi. Do not copy command output containing disallowed data into this document.

```bash
rpicam-hello --list-cameras
python3 -c "import picamera2"
scripts/setup_pi_camera.sh
.venv-pi/bin/python -c "import nutribox_pi, picamera2"
NUTRIBOX_CAMERA_ADAPTER=picamera2 .venv-pi/bin/python -m nutribox_pi camera-check
NUTRIBOX_CAMERA_ADAPTER=picamera2 .venv-pi/bin/python -m nutribox_pi camera-check --json
scripts/run_camera_smoke_test.sh
install -d -m 700 .camera-smoke
NUTRIBOX_CAMERA_ADAPTER=picamera2 .venv-pi/bin/nutribox-pi camera-capture .camera-smoke/pi1b-smoke.jpg
.venv-pi/bin/python -c 'from pathlib import Path; from nutribox_pi.camera_validation import inspect_jpeg; print(inspect_jpeg(Path(".camera-smoke/pi1b-smoke.jpg")))'
stat -c '%a' .camera-smoke .camera-smoke/pi1b-smoke.jpg
```

Record the image checksum locally, repeat capture without `--overwrite`, and
require exit 1 with `output_exists`. Confirm that the checksum is unchanged.
Then repeat with `--overwrite`, require exit 0, and rerun the JPEG inspection
and permission check:

```bash
sha256sum .camera-smoke/pi1b-smoke.jpg
NUTRIBOX_CAMERA_ADAPTER=picamera2 .venv-pi/bin/nutribox-pi camera-capture .camera-smoke/pi1b-smoke.jpg
sha256sum .camera-smoke/pi1b-smoke.jpg
NUTRIBOX_CAMERA_ADAPTER=picamera2 .venv-pi/bin/nutribox-pi camera-capture .camera-smoke/pi1b-smoke.jpg --overwrite
.venv-pi/bin/python -c 'from pathlib import Path; from nutribox_pi.camera_validation import inspect_jpeg; print(inspect_jpeg(Path(".camera-smoke/pi1b-smoke.jpg")))'
stat -c '%a' .camera-smoke .camera-smoke/pi1b-smoke.jpg
rm .camera-smoke/pi1b-smoke.jpg
rmdir .camera-smoke
```

Complete the allowlisted record below only after confirming that the captured
image and repository-root `.camera-smoke` directory have been deleted. Record
no checksum, captured image, absolute path, username, hostname, IP or MAC
address, token, credential, or raw exception.

| Allowed field | Result |
| --- | --- |
| OS codename | trixie |
| Architecture | aarch64 |
| Python version | 3.13.5 |
| Sanitized Picamera2 version or `unknown` | 0.3.37 |
| Sanitized libcamera version or `unknown` | 0.7.1+rpt20260609 |
| Sensor family, such as IMX708 | IMX708 |
| Camera-check pass/fail | PASS |
| Capture pass/fail | PASS |
| Encoded width | 1920 |
| Encoded height | 1080 |
| No-overwrite pass/fail | PASS |
| Overwrite pass/fail | PASS |
| Cleanup confirmation | PASS |
