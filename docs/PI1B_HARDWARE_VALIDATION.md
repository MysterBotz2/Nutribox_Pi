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
| OS codename | |
| Architecture | |
| Python version | |
| Sanitized Picamera2 version or `unknown` | |
| Sanitized libcamera version or `unknown` | |
| Sensor family, such as IMX708 | |
| Camera-check pass/fail | |
| Capture pass/fail | |
| Encoded width | |
| Encoded height | |
| No-overwrite pass/fail | |
| Overwrite pass/fail | |
| Cleanup confirmation | |
