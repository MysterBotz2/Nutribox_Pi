"""Private, hardware-independent local UI preferences for PI-3B1."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path


class Language(StrEnum):
    ENGLISH = "en"
    TAGALOG = "tl"


@dataclass(frozen=True, slots=True)
class UIPreferences:
    schema_version: int = 1
    language: Language = Language.ENGLISH
    show_intro_on_startup: bool = True


class UIPreferenceStore:
    """Atomic allowlisted JSON storage, deliberately separate from credentials."""

    def __init__(self, directory: Path | None = None) -> None:
        root = directory or Path.home() / ".config" / "nutribox-pi"
        self.path = root / "ui-preferences.json"

    def load(self) -> UIPreferences:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or set(payload) != {
                "schema_version",
                "language",
                "show_intro_on_startup",
            }:
                return UIPreferences()
            if payload["schema_version"] != 1 or not isinstance(
                payload["show_intro_on_startup"], bool
            ):
                return UIPreferences()
            return UIPreferences(
                language=Language(payload["language"]),
                show_intro_on_startup=payload["show_intro_on_startup"],
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return UIPreferences()

    def save(self, preferences: UIPreferences) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(self.path.parent, 0o700)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".ui-preferences-", suffix=".tmp", dir=self.path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(asdict(preferences), stream, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            if os.name == "posix":
                os.chmod(temporary, 0o600)
            temporary.replace(self.path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
