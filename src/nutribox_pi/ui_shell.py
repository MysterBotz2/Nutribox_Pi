"""Typed startup UI state and localized PI-3B1 copy; no Pygame dependency."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from nutribox_pi.ui_preferences import Language, Theme, UIPreferences, UIPreferenceStore


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
    preferences: UIPreferences = field(default_factory=UIPreferences)
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
            theme=self.preferences.theme,
        )
        self.store.save(self.preferences)

    def toggle_intro(self) -> None:
        self.preferences = UIPreferences(
            language=self.preferences.language,
            show_intro_on_startup=not self.preferences.show_intro_on_startup,
            theme=self.preferences.theme,
        )
        self.store.save(self.preferences)

    def set_theme(self, theme: Theme) -> None:
        self.preferences = UIPreferences(
            language=self.preferences.language,
            show_intro_on_startup=self.preferences.show_intro_on_startup,
            theme=theme,
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
        "paired_with": "Paired with {name}",
        "pair_leftovers": "Pair device to analyze leftovers",
        "instructions": "Instructions",
        "skip": "Skip",
        "media_unavailable": "Instructional video is not installed.",
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
        "ingredient_title": "AI Scan Results",
        "ingredient_prompt": "Confirm the ingredients found in this meal.",
        "ingredient_component": "Meal part",
        "ingredient_submitting": "Confirming ingredients...",
        "ingredient_retry": "Ingredients were not confirmed. Retry when ready.",
        "confirm_ingredients": "Confirm ingredients",
        "rescan": "Rescan",
        "previous_component": "Previous meal part",
        "next_component": "Next meal part",
        "edit_ingredient": "Edit Ingredient",
        "add_ingredient": "Add Ingredient",
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
        "save_saving": "Saving…",
        "save_saved": "Meal saved",
        "save_failed": "Save failed",
        "save_uncertain": "Check Web Companion",
        "profile_settings": "Profile & Settings",
        "guest_mode": "Guest mode",
        "paired_device": "Paired device",
        "unpair": "Unpair",
        "theme": "Theme",
        "diagnostics": "Diagnostics",
        "portion_analysis": "Portion Analysis",
        "select_saved_meal": "Select Saved Meal",
        "select_saved_meal_instruction": "Select a saved meal to scan its leftovers.",
        "no_saved_meals": "No saved meals are available.",
        "saved_meals_unavailable": "Saved meals are unavailable. Try again.",
        "page": "Page {number}",
        "selected": "Selected",
        "leftover_scan": "Leftover scan",
        "portion_explanation": (
            "This feature compares the saved meal with its remaining portion."
        ),
        "portion_status": "Load-cell mounting and calibration required.",
        "analyze_leftovers": "Analyze Leftovers",
        "portion_setup": (
            "Install the load cell, secure the mount, and calibrate before "
            "enabling leftovers analysis."
        ),
        "instructional_video_unavailable": "Instructional video is not installed.",
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
        "paired_with": "Nakapares kay {name}",
        "pair_leftovers": "I-pair ang device para suriin ang natira.",
        "instructions": "Mga Tagubilin",
        "skip": "Magpatuloy",
        "media_unavailable": "Hindi naka-install ang instructional video.",
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
        "ingredient_title": "Resulta ng AI Scan",
        "ingredient_prompt": "Kumpirmahin ang mga sangkap sa pagkain.",
        "ingredient_component": "Bahagi ng pagkain",
        "ingredient_submitting": "Kinukumpirma ang mga sangkap...",
        "ingredient_retry": "Hindi nakumpirma ang mga sangkap. Subukan muli.",
        "confirm_ingredients": "Kumpirmahin ang sangkap",
        "rescan": "I-scan muli",
        "previous_component": "Nakaraang bahagi",
        "next_component": "Susunod na bahagi",
        "edit_ingredient": "I-edit ang sangkap",
        "add_ingredient": "Magdagdag ng sangkap",
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
        "save_saving": "Sine-save…",
        "save_saved": "Nai-save ang pagkain",
        "save_failed": "Hindi na-save ang pagkain",
        "save_uncertain": "Tingnan ang Web Companion",
        "profile_settings": "Profile at Settings",
        "guest_mode": "Guest mode",
        "paired_device": "Nakapares na device",
        "unpair": "I-unpair",
        "theme": "Tema",
        "diagnostics": "Diagnostics",
        "portion_analysis": "Pagsusuri ng Porsyon",
        "select_saved_meal": "Pumili ng Naka-save na Pagkain",
        "select_saved_meal_instruction": (
            "Pumili ng naka-save na pagkain para suriin ang natira."
        ),
        "no_saved_meals": "Walang naka-save na pagkain.",
        "saved_meals_unavailable": (
            "Hindi available ang mga naka-save na pagkain. Subukan muli."
        ),
        "page": "Pahina {number}",
        "selected": "Napili",
        "leftover_scan": "Pagsusuri ng natitirang pagkain",
        "portion_explanation": (
            "Ang feature na ito ay naghahambing ng naka-save na pagkain sa "
            "natitirang bahagi nito."
        ),
        "portion_status": "Kinakailangan ang mounting at calibration ng load cell.",
        "analyze_leftovers": "Suriin ang Natira",
        "portion_setup": (
            "I-install ang load cell, i-secure ang mount, at i-calibrate bago "
            "paganahin ang pagsusuri ng natira."
        ),
        "instructional_video_unavailable": (
            "Hindi naka-install ang instructional video."
        ),
    },
}


def text(language: Language, key: str) -> str:
    return STRINGS.get(language, STRINGS[Language.ENGLISH]).get(
        key, STRINGS[Language.ENGLISH][key]
    )
