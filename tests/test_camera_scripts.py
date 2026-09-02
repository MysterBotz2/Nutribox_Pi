import os
from pathlib import Path


def test_camera_scripts_are_executable_and_do_not_modify_pi1a_environment() -> None:
    setup = Path("scripts/setup_pi_camera.sh")
    smoke = Path("scripts/run_camera_smoke_test.sh")
    assert os.access(setup, os.X_OK)
    assert os.access(smoke, os.X_OK)
    setup_text = setup.read_text()
    smoke_text = smoke.read_text()
    assert "sudo" not in setup_text
    assert "pip install picamera2" not in setup_text.lower()
    assert "python3 -m venv --system-site-packages" in setup_text
    assert "$PROJECT_DIR/.venv-pi" in setup_text
    assert "$PROJECT_DIR/.venv/bin/python" in setup_text
    assert "rm " not in setup_text
    assert ".venv-pi/bin/python" in smoke_text
    assert 'exec "$VENV_PYTHON" -m nutribox_pi camera-check' in smoke_text
    assert "NUTRIBOX_API_BASE_URL" not in smoke_text


def test_camera_repository_hygiene_rules_are_exact() -> None:
    rules = Path(".gitignore").read_text().splitlines()
    assert ".venv-pi/" in rules
    assert "/.camera-smoke/" in rules


def test_hardware_validation_template_has_complete_smoke_workflow() -> None:
    template = Path("docs/PI1B_HARDWARE_VALIDATION.md").read_text()
    assert "camera-capture .camera-smoke/pi1b-smoke.jpg" in template
    assert "--overwrite" in template
    assert "inspect_jpeg" in template
    assert "stat -c '%a'" in template
    assert "rm .camera-smoke/pi1b-smoke.jpg" in template
    assert "rmdir .camera-smoke" in template
    assert "Picamera2 version or `unknown` |" in template
