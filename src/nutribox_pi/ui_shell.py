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
        "camera_preview": "Camera Preview",
        "capture_meal": "Capture Meal",
        "captured_preview": "Captured Meal Preview",
        "live_preview": "Live Camera Preview",
        "simulated_preview": "Simulated Camera Preview",
        "weight": "Weight",
        "meal_clear": "Does your meal look clear?",
        "yes": "Yes",
        "no": "No",
        "analyzing_meal": "Analyzing meal...",
        "retry": "Retry",
        "camera_error": "Camera preview is unavailable.",
        "network_error": "Meal analysis is unavailable. Try again when ready.",
        "food_selection_title": "Choose your food",
        "food_selection_prompt": "Select one food to continue.",
        "food_selection_submitting": "Submitting selection...",
        "food_selection_retry": "Selection was not sent. Retry when ready.",
        "previous": "Previous",
        "next": "Next",
        "continue_food": "Continue",
        "nutrition_title": "Nutritional Contents",
        "nutrition_overview": "Overview",
        "nutrition_macros": "Macros",
        "nutrition_micros": "Micros",
        "meal_summary": "Meal Summary",
        "captured_meal": "Captured meal",
        "analyzed_weight": "Analyzed weight",
        "nutrition_result": "Result",
        "nutrition_complete": "Completed",
        "not_available": "Not available",
        "simulated_recognition": "Simulated recognition",
        "nutrition_energy": "Energy",
        "nutrition_calories": "Calories",
        "nutrition_protein": "Protein",
        "nutrition_carbohydrates": "Carbohydrates",
        "nutrition_total_fat": "Total Fat",
        "nutrition_saturated_fat": "Saturated Fat",
        "nutrition_fiber": "Fiber",
        "nutrition_sugar": "Sugar",
        "nutrition_sodium": "Sodium",
        "nutrition_cholesterol": "Cholesterol",
        "nutrition_omega_3": "Omega-3",
        "nutrition_omega_6": "Omega-6",
        "nutrition_calcium": "Calcium",
        "nutrition_iron": "Iron",
        "nutrition_potassium": "Potassium",
        "nutrition_magnesium": "Magnesium",
        "nutrition_zinc": "Zinc",
        "nutrition_phosphorus": "Phosphorus",
        "nutrition_vitamin_a": "Vitamin A",
        "nutrition_vitamin_b6": "Vitamin B6",
        "nutrition_vitamin_c": "Vitamin C",
        "nutrition_vitamin_b12": "Vitamin B12",
        "nutrition_folate": "Folate",
        "nutrition_vitamin_d": "Vitamin D",
        "nutrition_niacin": "Niacin/B3",
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
        "camera_preview": "Preview ng Camera",
        "capture_meal": "Kunan ang Pagkain",
        "captured_preview": "Nakunang Preview ng Pagkain",
        "live_preview": "Live na Preview ng Camera",
        "simulated_preview": "Simulated na Preview ng Camera",
        "weight": "Timbang",
        "meal_clear": "Malinaw ba ang kuha ng pagkain?",
        "yes": "Oo",
        "no": "Hindi",
        "analyzing_meal": "Sinusuri ang pagkain...",
        "retry": "Subukan muli",
        "camera_error": "Hindi available ang preview ng camera.",
        "network_error": "Hindi available ang pagsusuri. Subukan muli.",
        "food_selection_title": "Piliin ang pagkain",
        "food_selection_prompt": "Pumili ng isang pagkain upang magpatuloy.",
        "food_selection_submitting": "Ipinapadala ang pinili...",
        "food_selection_retry": "Hindi naipadala ang pinili. Subukan muli.",
        "previous": "Nakaraan",
        "next": "Susunod",
        "continue_food": "Magpatuloy",
        "nutrition_title": "Nilalamang Nutrisyon",
        "nutrition_overview": "Buod",
        "nutrition_macros": "Macros",
        "nutrition_micros": "Micros",
        "meal_summary": "Buod ng Pagkain",
        "captured_meal": "Nakuhang pagkain",
        "analyzed_weight": "Sinuring timbang",
        "nutrition_result": "Resulta",
        "nutrition_complete": "Tapos na",
        "not_available": "Hindi available",
        "simulated_recognition": "Simulated na pagkilala",
        "nutrition_energy": "Enerhiya",
        "nutrition_calories": "Calories",
        "nutrition_protein": "Protina",
        "nutrition_carbohydrates": "Carbohydrates",
        "nutrition_total_fat": "Kabuuang Taba",
        "nutrition_saturated_fat": "Saturated Fat",
        "nutrition_fiber": "Fiber",
        "nutrition_sugar": "Asukal",
        "nutrition_sodium": "Sodium",
        "nutrition_cholesterol": "Cholesterol",
        "nutrition_omega_3": "Omega-3",
        "nutrition_omega_6": "Omega-6",
        "nutrition_calcium": "Calcium",
        "nutrition_iron": "Iron",
        "nutrition_potassium": "Potassium",
        "nutrition_magnesium": "Magnesium",
        "nutrition_zinc": "Zinc",
        "nutrition_phosphorus": "Phosphorus",
        "nutrition_vitamin_a": "Vitamin A",
        "nutrition_vitamin_b6": "Vitamin B6",
        "nutrition_vitamin_c": "Vitamin C",
        "nutrition_vitamin_b12": "Vitamin B12",
        "nutrition_folate": "Folate",
        "nutrition_vitamin_d": "Vitamin D",
        "nutrition_niacin": "Niacin/B3",
    },
}


def text(language: Language, key: str) -> str:
    return STRINGS.get(language, STRINGS[Language.ENGLISH]).get(
        key, STRINGS[Language.ENGLISH][key]
    )
