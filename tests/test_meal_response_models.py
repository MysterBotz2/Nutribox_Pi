from __future__ import annotations

from datetime import UTC, datetime

import pytest

from nutribox_pi.models import (
    AdditionalNutrientValues,
    MealItemNutritionSource,
    MealItemResponse,
    MealResponse,
    MealTotals,
    SavedMealFood,
)


def optional_values() -> dict[str, str | None]:
    return {
        "saturated_fat_g": None,
        "sugars_g": "1.2",
        "sodium_mg": "3",
        "cholesterol_mg": None,
        "omega_3_g": None,
        "omega_6_g": None,
        "calcium_mg": "1",
        "potassium_mg": None,
        "zinc_mg": None,
        "iron_mg": None,
        "magnesium_mg": None,
        "energy_kj": "4.184",
        "phosphorus_mg": "2",
        "vitamin_b6_mg": None,
        "niacin_mg": None,
        "vitamin_a_mcg_rae": None,
        "vitamin_b12_mcg": None,
        "vitamin_c_mg": None,
        "vitamin_d_mcg": None,
        "folate_mcg_dfe": None,
    }


def totals() -> MealTotals:
    return MealTotals(
        "100", "2", "3", "4", "5", AdditionalNutrientValues(optional_values())
    )


def item(identifier: int = 1) -> MealItemResponse:
    return MealItemResponse(
        identifier,
        SavedMealFood(1, "safe food"),
        "250",
        totals(),
        MealItemNutritionSource("USDA", None, None, False),
        False,
    )


def test_complete_hierarchy_preserves_decimal_strings_and_nulls() -> None:
    response = MealResponse(
        1,
        datetime.now(UTC),
        (item(), item(2)),
        totals(),
        AdditionalNutrientValues(optional_values()),
    )
    assert len(response.items) == 2
    assert response.totals.additional.values["energy_kj"] == "4.184"
    assert response.additional_totals.values["vitamin_c_mg"] is None


@pytest.mark.parametrize(
    "category",
    [
        None,
        "canteen_recipe",
        "local_database",
        "USDA",
        "AI_estimate",
        "ai_recipe_estimate",
    ],
)
def test_authoritative_provenance_categories(category: str | None) -> None:
    assert MealItemNutritionSource(category, None, None, None).category == category


@pytest.mark.parametrize(
    "factory",
    [
        lambda: SavedMealFood(True, "x"),
        lambda: MealItemResponse(
            True, SavedMealFood(1, "x"), "1", totals(), None, False
        ),
        lambda: MealResponse(
            1, datetime.now(), (), totals(), AdditionalNutrientValues(optional_values())
        ),
        lambda: MealTotals(
            "NaN", "1", "1", "1", "1", AdditionalNutrientValues(optional_values())
        ),
    ],
)
def test_invalid_ids_timestamps_and_numerics_are_normalized(factory: object) -> None:
    with pytest.raises(ValueError) as error:
        factory()
    assert "safe food" not in str(error.value)


def test_unknown_optional_nutrient_and_invalid_provenance_rejected() -> None:
    values = optional_values()
    values["extra"] = None
    with pytest.raises(ValueError):
        AdditionalNutrientValues(values)
    with pytest.raises(ValueError):
        MealItemNutritionSource("secret", None, None, None)


def test_models_have_no_hardware_import_boundary() -> None:
    import nutribox_pi.models as models

    assert models.MealResponse is MealResponse
