"""Typed startup UI state and localized PI-3B1 copy; no Pygame dependency."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from nutribox_pi.ui_preferences import Language, UIPreferences, UIPreferenceStore


class StartupMilestone(StrEnum):
    UI_INITIALIZED = "ui_initialized"
    CONFIGURATION_LOADED = "configuration_loaded"
    PREFERENCE_LOADED = "preference_loaded"
    PAIRING_VERIFICATION = "pairing_verification"
    WORKFLOW_READY = "workflow_ready"


MILESTONES = tuple(StartupMilestone)


@dataclass(slots=True)
class StartupShell:
    store: UIPreferenceStore
    preferences: UIPreferences = UIPreferences()
    completed: int = 0

    @property
    def progress(self) -> float:
        return self.completed / len(MILESTONES)

    def complete(self, milestone: StartupMilestone) -> None:
        expected = (
            MILESTONES[self.completed] if self.completed < len(MILESTONES) else None
        )
        if milestone is not expected:
            raise ValueError("Startup milestones must be completed in order.")
        if milestone is StartupMilestone.PREFERENCE_LOADED:
            self.preferences = self.store.load()
        self.completed += 1

    def select_language(self, language: Language) -> None:
        self.preferences = UIPreferences(
            language=language,
            show_intro_on_startup=self.preferences.show_intro_on_startup,
        )
        self.store.save(self.preferences)

    def toggle_intro(self) -> None:
        self.preferences = UIPreferences(
            language=self.preferences.language,
            show_intro_on_startup=not self.preferences.show_intro_on_startup,
        )
        self.store.save(self.preferences)


STRINGS = {
    Language.ENGLISH: {
        "choose_language": "Choose your language",
        "english": "English",
        "tagalog": "Tagalog",
        "show_intro": "Show intro video on startup",
        "ready": "Ready to operate NutriBox PI?",
        "analyze": "Analyze Meal",
        "back": "Back",
        "exit": "Exit",
        "pair": "Pair Device",
        "checking": "Checking device...",
        "paired": "Device paired",
        "instructions": "Instructions",
        "skip": "Skip",
        "media_unavailable": "Instructional media is not installed.",
    },
    Language.TAGALOG: {
        "choose_language": "Pumili ng wika",
        "english": "Ingles",
        "tagalog": "Tagalog",
        "show_intro": "Ipakita ang panimulang video",
        "ready": "Handa nang gamitin ang NutriBox PI?",
        "analyze": "Suriin ang Pagkain",
        "back": "Bumalik",
        "exit": "Lumabas",
        "pair": "Ikonekta ang Device",
        "checking": "Sinusuri ang device...",
        "paired": "Nakonekta ang device",
        "instructions": "Mga Tagubilin",
        "skip": "Magpatuloy",
        "media_unavailable": "Hindi naka-install ang instructional media.",
    },
}


def text(language: Language, key: str) -> str:
    return STRINGS.get(language, STRINGS[Language.ENGLISH]).get(
        key, STRINGS[Language.ENGLISH][key]
    )
