from __future__ import annotations

import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUTOSTART_SCRIPT = PROJECT_ROOT / "scripts" / "configure_ui_autostart.sh"
LAUNCHER_SCRIPT = PROJECT_ROOT / "scripts" / "run_device_ui.sh"


def _fake_systemctl(tmp_path: Path) -> Path:
    command = tmp_path / "bin" / "systemctl"
    command.parent.mkdir()
    command.write_text(
        """#!/usr/bin/env bash
set -eu
printf '%s\\n' "$*" >> "$FAKE_SYSTEMCTL_LOG"
case "$*" in
  *"enable --now nutribox-pi-ui.service")
    wants="$XDG_CONFIG_HOME/systemd/user/default.target.wants"
    mkdir -p "$wants"
    ln -sfn ../nutribox-pi-ui.service "$wants/nutribox-pi-ui.service"
    ;;
esac
"""
    )
    command.chmod(0o755)
    return command


def _script_environment(tmp_path: Path) -> dict[str, str]:
    fake_systemctl = _fake_systemctl(tmp_path)
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(tmp_path / "home"),
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
            "FAKE_SYSTEMCTL_LOG": str(tmp_path / "systemctl.log"),
            "PATH": f"{fake_systemctl.parent}{os.pathsep}{environment['PATH']}",
        }
    )
    return environment


def _run_autostart(command: str, environment: dict[str, str]) -> None:
    result = subprocess.run(
        [str(AUTOSTART_SCRIPT), command],
        cwd=PROJECT_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_autostart_enable_uses_default_target_and_cleans_legacy_link(
    tmp_path: Path,
) -> None:
    environment = _script_environment(tmp_path)
    unit_dir = Path(environment["XDG_CONFIG_HOME"]) / "systemd" / "user"
    legacy_link = unit_dir / "graphical-session.target.wants" / "nutribox-pi-ui.service"
    legacy_link.parent.mkdir(parents=True)
    legacy_link.symlink_to("../nutribox-pi-ui.service")

    _run_autostart("enable", environment)
    _run_autostart("enable", environment)

    service = (unit_dir / "nutribox-pi-ui.service").read_text()
    assert "After=graphical-session.target network-online.target" in service
    assert "Wants=network-online.target" in service
    assert "Restart=on-failure" in service
    assert "RestartSec=3" in service
    assert "WantedBy=default.target" in service
    assert "WantedBy=graphical-session.target" not in service
    assert not legacy_link.is_symlink()
    assert (unit_dir / "default.target.wants" / "nutribox-pi-ui.service").is_symlink()


def test_autostart_disable_is_idempotent_and_removes_current_and_legacy_links(
    tmp_path: Path,
) -> None:
    environment = _script_environment(tmp_path)
    unit_dir = Path(environment["XDG_CONFIG_HOME"]) / "systemd" / "user"

    _run_autostart("enable", environment)
    legacy_link = unit_dir / "graphical-session.target.wants" / "nutribox-pi-ui.service"
    legacy_link.parent.mkdir(parents=True)
    legacy_link.symlink_to("../nutribox-pi-ui.service")

    _run_autostart("disable", environment)
    _run_autostart("disable", environment)

    assert not (unit_dir / "nutribox-pi-ui.service").exists()
    default_link = unit_dir / "default.target.wants" / "nutribox-pi-ui.service"
    assert not default_link.is_symlink()
    assert not legacy_link.is_symlink()


def test_launcher_has_bounded_wayland_readiness_wait_and_valid_shell_syntax() -> None:
    launcher = LAUNCHER_SCRIPT.read_text()

    assert "READY_TIMEOUT_SECONDS=30" in launcher
    assert 'while [ "$READY_ELAPSED" -lt "$READY_TIMEOUT_SECONDS" ]; do' in launcher
    assert 'sleep "$READY_POLL_SECONDS"' in launcher
    assert "graphical session did not become ready before the timeout" in launcher
    result = subprocess.run(
        ["bash", "-n", str(LAUNCHER_SCRIPT), str(AUTOSTART_SCRIPT)],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
