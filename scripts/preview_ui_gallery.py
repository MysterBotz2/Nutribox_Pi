#!/usr/bin/env python3
"""Developer-only client gallery rendered by NutriBox's real Pygame renderer."""

from __future__ import annotations

import argparse
import importlib
import os
import sys
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

CLIENT_SET = (
    ("01-loading.png", "loading", "en", "light"),
    ("02-language-selection.png", "language", "en", "light"),
    ("03-instructions.png", "instructions", "en", "light"),
    ("04-guest-home.png", "guest", "en", "light"),
    ("05-paired-home.png", "home", "en", "light"),
    ("06-camera-preview.png", "camera", "en", "light"),
    ("07-confirm-captured-meal.png", "review", "en", "light"),
    ("08-food-selection.png", "food", "en", "light"),
    ("09-ingredient-confirmation.png", "ingredients", "en", "light"),
    ("10-ingredient-editing.png", "editor", "en", "light"),
    ("11-recipe-confirmation.png", "recipe", "en", "light"),
    ("12-nutrition-overview.png", "overview", "en", "light"),
    ("13-macronutrients.png", "macros", "en", "light"),
    ("14-micronutrients.png", "micros", "en", "light"),
    ("15-meal-saved.png", "saved", "en", "light"),
    ("16-profile-settings.png", "profile", "en", "light"),
    ("17-leftover-select-meal.png", "leftover-select", "en", "light"),
    ("18-leftover-capture-review.png", "leftover-review", "en", "light"),
    ("19-leftover-calculated-review.png", "leftover-calculated", "en", "light"),
    ("20-leftover-summary.png", "leftover-summary", "en", "light"),
    ("21-tagalog-home-dark.png", "home", "tl", "dark"),
    ("22-tagalog-nutrition-dark.png", "overview", "tl", "dark"),
    ("23-tagalog-leftover-summary-dark.png", "leftover-summary", "tl", "dark"),
)


class _Backend:
    pass


class _Pairing:
    def __init__(self, paired: bool) -> None:
        from nutribox_pi.pairing import PairingState

        self.state = PairingState.PAIRED if paired else PairingState.UNPAIRED
        self.device = SimpleNamespace(owner_first_name="Mia") if paired else None
        self.greeting = "Welcome back, Mia!" if paired else None
        self.error_message = None

    def get_verified_device_token(self) -> str | None:
        return "gallery-token" if self.device else None


def _module(name: str) -> object:
    return importlib.import_module(name)


def _nutrition(
    calories: str,
    protein: str,
    carbohydrates: str,
    fat: str,
    fiber: str,
    values: dict[str, str | None],
) -> object:
    models = _module("nutribox_pi.models")
    return models.NutritionValues(calories, protein, carbohydrates, fat, fiber, values)


def _original_nutrition() -> object:
    return _nutrition(
        "630",
        "42",
        "70",
        "21",
        "8",
        {
            "saturated_fat_g": "5",
            "sugars_g": "7",
            "sodium_mg": "500",
            "calcium_mg": "90",
            "iron_mg": "3",
            "potassium_mg": "400",
            "magnesium_mg": "50",
            "phosphorus_mg": "200",
            "vitamin_c_mg": "30",
        },
    )


def _remaining_nutrition() -> object:
    return _nutrition(
        "142.5",
        "9.5",
        "15.75",
        "4.75",
        "1.8",
        {
            "saturated_fat_g": "1.125",
            "sugars_g": "1.575",
            "sodium_mg": "112.5",
            "calcium_mg": "20.25",
            "iron_mg": "0.675",
            "potassium_mg": "90",
            "magnesium_mg": "11.25",
            "phosphorus_mg": "45",
            "vitamin_c_mg": "6.75",
        },
    )


def _consumed_nutrition() -> object:
    return _nutrition(
        "487.5",
        "32.5",
        "54.25",
        "16.25",
        "6.2",
        {
            "saturated_fat_g": "3.875",
            "sugars_g": "5.425",
            "sodium_mg": "387.5",
            "calcium_mg": "69.75",
            "iron_mg": "2.325",
            "potassium_mg": "310",
            "magnesium_mg": "38.75",
            "phosphorus_mg": "155",
            "vitamin_c_mg": "23.25",
        },
    )


def _validate_leftover_fixture() -> None:
    """Keep gallery-only original, remaining, and consumed nutrition coherent."""
    original = _original_nutrition()
    remaining = _remaining_nutrition()
    consumed = _consumed_nutrition()
    for field in ("calories", "protein", "carbohydrates", "fat", "fiber"):
        if Decimal(getattr(original, field)) - Decimal(
            getattr(remaining, field)
        ) != Decimal(getattr(consumed, field)):
            raise RuntimeError("gallery nutrition fixture is inconsistent")
    for key, original_value in original.values.items():
        remaining_value = remaining.values[key]
        consumed_value = consumed.values[key]
        if Decimal(original_value) - Decimal(remaining_value) != Decimal(
            consumed_value
        ):
            raise RuntimeError("gallery nutrition fixture is inconsistent")


def _response() -> object:
    models = _module("nutribox_pi.models")
    nutrition = _original_nutrition()
    return models.CalculatedResponse(
        models.AnalysisStatus.CALCULATED,
        (models.RecognizedFood("Roast meat with carrots, broccoli, soup, and yogurt"),),
        models.RecognitionSource.SIMULATED,
        "420",
        9,
        None,
        None,
        nutrition=nutrition,
        weight_grams="420",
        weight_source="manual",
        food=models.CalculatedFoodReference(
            1, "Roast meat with carrots, broccoli, soup, and yogurt"
        ),
    )


def _workflow(
    pygame: object, name: str, language: str, theme: str, image: Path
) -> tuple[object, object, object | None]:
    mock = _module("nutribox_pi.adapters.mock_hardware")
    simulated = _module("nutribox_pi.adapters.simulated_camera")
    renderer = _module("nutribox_pi.adapters.pygame_device_ui")
    controller_module = _module("nutribox_pi.controller")
    device = _module("nutribox_pi.device_ui")
    models = _module("nutribox_pi.models")
    preferences = _module("nutribox_pi.ui_preferences")
    continuation = _module("nutribox_pi.continuation")
    leftovers = _module("nutribox_pi.leftover")
    paired = name != "guest"
    controller = controller_module.NutriBoxController(
        _Backend(), mock.SimulatedWeightSensor(420), mock.SimulatedTemperatureSensor()
    )
    workflow = device.MealCaptureWorkflow(
        simulated.SimulatedCamera(),
        controller,
        simulated_weight=True,
        pairing=_Pairing(paired),
    )
    workflow.startup_shell = SimpleNamespace(
        preferences=SimpleNamespace(
            language=preferences.Language.TAGALOG
            if language == "tl"
            else preferences.Language.ENGLISH,
            theme=preferences.Theme.DARK
            if theme == "dark"
            else preferences.Theme.LIGHT,
            show_intro_on_startup=True,
        ),
        progress=0.7,
    )
    response = _response()
    workflow.analysis_response = response
    workflow.recognized_foods = response.recognized_foods
    workflow.recognition_source = response.recognition_source
    screens = {
        "loading": device.UIScreen.LOADING,
        "language": device.UIScreen.LANGUAGE,
        "instructions": device.UIScreen.INSTRUCTION,
        "guest": device.UIScreen.HOME,
        "home": device.UIScreen.HOME,
        "camera": device.UIScreen.CAPTURE,
        "review": device.UIScreen.REVIEW,
        "leftover-review": device.UIScreen.REVIEW,
        "food": device.UIScreen.FOOD_SELECTION,
        "ingredients": device.UIScreen.REQUIRES_INGREDIENT_VERIFICATION,
        "editor": device.UIScreen.INGREDIENT_EDITOR,
        "recipe": device.UIScreen.REQUIRES_RECIPE_CONFIRMATION,
        "overview": device.UIScreen.CALCULATED,
        "macros": device.UIScreen.CALCULATED,
        "micros": device.UIScreen.CALCULATED,
        "saved": device.UIScreen.CALCULATED,
        "profile": device.UIScreen.PROFILE_SETTINGS,
        "leftover-select": device.UIScreen.SAVED_MEAL_SELECTION,
        "leftover-calculated": device.UIScreen.CALCULATED,
        "leftover-summary": device.UIScreen.LEFTOVER_SUMMARY,
    }
    workflow.screen = screens[name]
    workflow._store._image = image
    workflow.captured_weight_grams = 420
    cache = renderer._UiImageCache()
    cache.capture_review_image(pygame, image, workflow.meal_generation)
    preview = None
    if name == "camera":
        preview = pygame.image.load(str(image)).convert()
    if name == "food":
        workflow._food_selection = device.FoodSelectionView(
            ("Chicken adobo", "Pancit", "Vegetable curry"), 0, None, False, False
        )
    if name == "ingredients":
        workflow._ingredient_verification = device.IngredientVerificationView(
            ("Rice bowl",),
            ("Chicken", "Rice", "Carrots"),
            (True, True, True),
            0,
            0,
            False,
            False,
        )
    if name == "editor":
        workflow._ingredient_editor = device.IngredientEditorView("Chicken", 0, None)
    if name == "macros":
        workflow._nutrition_view = device.NutritionView(device.NutritionTab.MACROS)
    if name == "micros":
        workflow._nutrition_view = device.NutritionView(device.NutritionTab.MICROS)
    if name == "saved":
        workflow._analysis_started_paired = True
        workflow.continuation._save_state = continuation.SaveState.SAVED
        workflow.continuation._saved_meal = SimpleNamespace(id=1)
    if name == "leftover-select":
        workflow.leftovers._page = models.SavedMealPage(
            tuple(
                models.SavedMealListItem(
                    index,
                    datetime(2026, 9, index, tzinfo=UTC),
                    (meal_name,),
                    "420" if index == 1 else str(250 + index * 25),
                )
                for index, meal_name in enumerate(
                    (
                        "Roast meat with carrots, broccoli, soup, and yogurt",
                        "Vegetable pasta",
                        "Fish stew",
                        "Tofu curry",
                    ),
                    start=1,
                )
            ),
            4,
            0,
        )
        workflow.leftovers.state = leftovers.LeftoverState.SELECTING
    if name in {"leftover-review", "leftover-calculated"}:
        workflow.leftover_mode = True
    if name == "leftover-summary":
        workflow.leftovers._summary = models.LeftoverScanResponse(
            1,
            1,
            9,
            "420",
            "95",
            "325",
            "77.38",
            _remaining_nutrition(),
            _consumed_nutrition(),
            (),
            datetime(2026, 9, 2, tzinfo=UTC),
        )
    return workflow, cache, preview


def _center_cropped_capture_image(pygame: object, source: Path, output: Path) -> Path:
    """Create a temporary 16:9 capture image without stretching a photograph."""
    try:
        original = pygame.image.load(str(source)).convert()
    except Exception as exc:
        raise ValueError("gallery meal photograph could not be loaded") from exc
    width, height = original.get_size()
    if width <= 0 or height <= 0:
        raise ValueError("gallery meal photograph could not be loaded")
    target_width, target_height = 1920, 1080
    scale = max(target_width / width, target_height / height)
    scaled = pygame.transform.smoothscale(
        original, (round(width * scale), round(height * scale))
    )
    cropped = pygame.Surface((target_width, target_height))
    cropped.blit(
        scaled,
        (
            (target_width - scaled.get_width()) // 2,
            (target_height - scaled.get_height()) // 2,
        ),
    )
    pygame.image.save(cropped, str(output))
    return output


def render_client_set(
    output: Path, initial_meal_image: Path, leftover_meal_image: Path
) -> None:
    pygame = _module("pygame")
    _validate_leftover_fixture()
    pygame.init()
    screen = pygame.display.set_mode((800, 480))
    renderer = _module("nutribox_pi.adapters.pygame_device_ui")
    fonts = renderer._Fonts(
        heading=pygame.font.Font(None, 48),
        subheading=pygame.font.Font(None, 34),
        body=pygame.font.Font(None, 28),
        small=pygame.font.Font(None, 20),
        button=pygame.font.Font(None, 32),
    )
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="nutribox-gallery-") as temporary:
        temporary_root = Path(temporary)
        initial_image = _center_cropped_capture_image(
            pygame, initial_meal_image, temporary_root / "initial-meal.jpg"
        )
        leftover_image = _center_cropped_capture_image(
            pygame, leftover_meal_image, temporary_root / "leftover-meal.jpg"
        )
        for filename, name, language, theme in CLIENT_SET:
            image = (
                leftover_image
                if name
                in {"leftover-review", "leftover-calculated", "leftover-summary"}
                else initial_image
            )
            workflow, cache, preview = _workflow(pygame, name, language, theme, image)
            renderer._render(pygame, screen, fonts, workflow, None, preview, cache)
            pygame.image.save(screen, str(output / filename))
    sheet = pygame.Surface((800, 480))
    sheet.fill((255, 255, 255))
    for index, (filename, *_rest) in enumerate(CLIENT_SET):
        image = pygame.transform.smoothscale(
            pygame.image.load(str(output / filename)), (160, 96)
        )
        sheet.blit(image, ((index % 5) * 160, (index // 5) * 96))
    pygame.image.save(sheet, str(output / "contact-sheet.png"))
    pygame.quit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-set", action="store_true")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--initial-meal-image", type=Path)
    parser.add_argument("--leftover-meal-image", type=Path)
    args = parser.parse_args()
    if not args.client_set:
        parser.error("--client-set is required")
    if args.initial_meal_image is None or args.leftover_meal_image is None:
        parser.error("--initial-meal-image and --leftover-meal-image are required")
    for image in (args.initial_meal_image, args.leftover_meal_image):
        if not image.is_file():
            parser.error("meal photograph must be a readable file")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    try:
        render_client_set(
            args.output_dir, args.initial_meal_image, args.leftover_meal_image
        )
    except ValueError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
