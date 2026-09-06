from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUTOSTART_SCRIPT = PROJECT_ROOT / "scripts" / "configure_ui_autostart.sh"
LAUNCHER_SCRIPT = PROJECT_ROOT / "scripts" / "run_device_ui.sh"


def _project_with_spaces(tmp_path: Path) -> Path:
    project = tmp_path / "NutriBox Pi"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(AUTOSTART_SCRIPT, scripts / AUTOSTART_SCRIPT.name)
    launcher = scripts / LAUNCHER_SCRIPT.name
    launcher.write_text("#!/usr/bin/env bash\nexit 0\n")
    launcher.chmod(0o644)
    return project


def _environment(tmp_path: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(tmp_path / "home"),
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
        }
    )
    return environment


def _run(project: Path, command: str, environment: dict[str, str]) -> None:
    result = subprocess.run(
        [str(project / "scripts" / "configure_ui_autostart.sh"), command],
        cwd=project,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _autostart_path(environment: dict[str, str]) -> Path:
    return Path(environment["XDG_CONFIG_HOME"]) / "labwc" / "autostart"


def test_labwc_enable_preserves_content_is_idempotent_and_quotes_space_path(
    tmp_path: Path,
) -> None:
    project = _project_with_spaces(tmp_path)
    environment = _environment(tmp_path)
    autostart = _autostart_path(environment)
    autostart.parent.mkdir(parents=True)
    unrelated = "waybar &\n# retain this line\n"
    autostart.write_text(unrelated)

    _run(project, "enable", environment)
    first_enable = autostart.read_text()
    _run(project, "enable", environment)

    assert autostart.read_text() == first_enable
    assert unrelated in first_enable
    assert first_enable.count("# >>> Nutri-Box Pi managed autostart >>>") == 1
    assert first_enable.count("# <<< Nutri-Box Pi managed autostart <<<") == 1
    assert "'" + str(project / "scripts" / "run_device_ui.sh") + "' &" in first_enable
    assert (project / "scripts" / "run_device_ui.sh").stat().st_mode & 0o100


def test_labwc_disable_removes_only_managed_entry_and_is_idempotent(
    tmp_path: Path,
) -> None:
    project = _project_with_spaces(tmp_path)
    environment = _environment(tmp_path)
    autostart = _autostart_path(environment)
    autostart.parent.mkdir(parents=True)
    unrelated = "waybar &\ncustom-command --keep\n"
    autostart.write_text(unrelated)

    _run(project, "enable", environment)
    _run(project, "disable", environment)
    _run(project, "disable", environment)

    assert autostart.read_text() == unrelated


def test_labwc_enable_creates_missing_file_and_removes_obsolete_service(
    tmp_path: Path,
) -> None:
    project = _project_with_spaces(tmp_path)
    environment = _environment(tmp_path)
    config_root = Path(environment["XDG_CONFIG_HOME"])
    unit_dir = config_root / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    service = unit_dir / "nutribox-pi-ui.service"
    service.write_text("obsolete")
    for target in ("default.target.wants", "graphical-session.target.wants"):
        wants = unit_dir / target
        wants.mkdir()
        (wants / "nutribox-pi-ui.service").symlink_to("../nutribox-pi-ui.service")

    _run(project, "enable", environment)

    assert _autostart_path(environment).exists()
    assert not service.exists()
    assert not (unit_dir / "default.target.wants" / service.name).is_symlink()
    assert not (unit_dir / "graphical-session.target.wants" / service.name).is_symlink()


def test_labwc_disable_is_safe_when_autostart_and_legacy_files_are_missing(
    tmp_path: Path,
) -> None:
    project = _project_with_spaces(tmp_path)
    environment = _environment(tmp_path)

    _run(project, "disable", environment)

    assert not _autostart_path(environment).exists()


def test_labwc_installer_and_launcher_have_bounded_safe_shell_behavior() -> None:
    installer = AUTOSTART_SCRIPT.read_text()
    launcher = LAUNCHER_SCRIPT.read_text()

    assert "MANAGED_START" in installer
    assert "chmod u+x" in installer
    assert "systemctl --user disable --now" in installer
    assert "READY_TIMEOUT_SECONDS=30" in launcher
    assert 'while [ "$READY_ELAPSED" -lt "$READY_TIMEOUT_SECONDS" ]; do' in launcher
    assert 'sleep "$READY_POLL_SECONDS"' in launcher
    result = subprocess.run(
        ["bash", "-n", str(AUTOSTART_SCRIPT), str(LAUNCHER_SCRIPT)],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
