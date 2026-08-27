from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from nutribox_pi.adapters import pygame_device_ui
from nutribox_pi.adapters.pygame_device_ui import display_flags_for
from nutribox_pi.device_ui import (
    DISPLAY_SIZE,
    MealCaptureWorkflow,
    UIAction,
    UIScreen,
    buttons_for,
)
from nutribox_pi.ui_preferences import Language, UIPreferences, UIPreferenceStore
from nutribox_pi.ui_shell import MILESTONES, StartupMilestone, StartupShell, text


def test_loading_milestones_are_ordered_real_progress(tmp_path: Path) -> None:
    shell = StartupShell(UIPreferenceStore(tmp_path))
    assert shell.progress == 0
    observed = []
    for milestone in MILESTONES:
        shell.complete(milestone)
        observed.append(shell.progress)
    assert observed == pytest.approx([0.2, 0.4, 0.6, 0.8, 1.0])
    with pytest.raises(ValueError):
        StartupShell(UIPreferenceStore(tmp_path)).complete(
            StartupMilestone.WORKFLOW_READY
        )


@pytest.mark.parametrize("language", [Language.ENGLISH, Language.TAGALOG])
def test_language_and_intro_preference_round_trip(
    tmp_path: Path, language: Language
) -> None:
    store = UIPreferenceStore(tmp_path)
    shell = StartupShell(store)
    shell.select_language(language)
    shell.toggle_intro()
    assert store.load() == UIPreferences(language=language, show_intro_on_startup=False)


def test_preference_allowlist_privacy_and_malformed_recovery(tmp_path: Path) -> None:
    store = UIPreferenceStore(tmp_path)
    store.save(UIPreferences(language=Language.TAGALOG))
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert set(payload) == {
        "schema_version",
        "language",
        "show_intro_on_startup",
    }
    serialized = json.dumps(payload).casefold()
    assert all(
        forbidden not in serialized
        for forbidden in ("token", "email", "user_id", "owner", "backend", "image")
    )
    store.path.write_text("{broken", encoding="utf-8")
    assert store.load() == UIPreferences()


def test_atomic_save_leaves_no_temporary_file(tmp_path: Path) -> None:
    store = UIPreferenceStore(tmp_path)
    store.save(UIPreferences())
    assert [path.name for path in tmp_path.iterdir()] == ["ui-preferences.json"]


def test_display_mode_boundary_is_windowed_only_on_windows() -> None:
    assert display_flags_for("win32", 123) == 0
    assert display_flags_for("linux", 123) == 123
    assert DISPLAY_SIZE == (800, 480)


def test_all_new_buttons_fit_canvas_and_have_touch_targets() -> None:
    for screen in (UIScreen.LANGUAGE, UIScreen.INSTRUCTION, UIScreen.HOME):
        for button in buttons_for(screen):
            rectangle = button.rectangle
            assert rectangle.x >= 0 and rectangle.y >= 0
            assert rectangle.x + rectangle.width <= 800
            assert rectangle.y + rectangle.height <= 480
            assert rectangle.width >= 48 and rectangle.height >= 48


def test_localized_copy_has_deterministic_fallback() -> None:
    assert text(Language.ENGLISH, "analyze") == "Analyze Meal"
    assert text(Language.TAGALOG, "analyze") == "Suriin ang Pagkain"
    assert text(Language.TAGALOG, "media_unavailable")


def test_new_action_contract_is_explicit() -> None:
    actions = {button.action for button in buttons_for(UIScreen.LANGUAGE)}
    assert {
        UIAction.SELECT_ENGLISH,
        UIAction.SELECT_TAGALOG,
        UIAction.TOGGLE_INTRO,
        UIAction.HELP,
    } <= actions
    assert {button.action for button in buttons_for(UIScreen.INSTRUCTION)} >= {
        UIAction.BACK,
        UIAction.CONTINUE,
    }


def test_loading_transitions_to_language_selection(tmp_path: Path) -> None:
    workflow = MealCaptureWorkflow.__new__(MealCaptureWorkflow)
    workflow.startup_shell = StartupShell(UIPreferenceStore(tmp_path))
    workflow.screen = UIScreen.LOADING
    for _ in MILESTONES:
        workflow.tick_startup()
    assert workflow.screen is UIScreen.LANGUAGE


@pytest.mark.parametrize(
    ("language", "show_intro", "expected"),
    [
        (Language.ENGLISH, True, UIScreen.INSTRUCTION),
        (Language.TAGALOG, False, UIScreen.HOME),
    ],
)
def test_language_selection_respects_intro_setting(
    tmp_path: Path,
    language: Language,
    show_intro: bool,
    expected: UIScreen,
) -> None:
    workflow = MealCaptureWorkflow.__new__(MealCaptureWorkflow)
    workflow.startup_shell = StartupShell(
        UIPreferenceStore(tmp_path),
        UIPreferences(show_intro_on_startup=show_intro),
    )
    workflow.screen = UIScreen.LANGUAGE
    workflow.select_language(language)
    assert workflow.language is language
    assert workflow.screen is expected
    if expected is UIScreen.INSTRUCTION:
        workflow.continue_from_instruction()
        assert workflow.screen is UIScreen.HOME


def test_sdl_dummy_renders_new_screens_inside_canvas(tmp_path: Path) -> None:
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame = pytest.importorskip("pygame")
    pygame.init()
    try:
        surface = pygame.Surface(DISPLAY_SIZE)
        fonts = pygame_device_ui._Fonts(
            heading=pygame.font.Font(None, 48),
            subheading=pygame.font.Font(None, 34),
            body=pygame.font.Font(None, 28),
            small=pygame.font.Font(None, 20),
            button=pygame.font.Font(None, 32),
        )
        shell = StartupShell(UIPreferenceStore(tmp_path))
        shell.completed = len(MILESTONES)
        workflow = SimpleNamespace(
            startup_shell=shell,
            language=Language.ENGLISH,
            pairing=None,
        )
        renderers = (
            pygame_device_ui._render_loading,
            pygame_device_ui._render_language,
            pygame_device_ui._render_instruction,
            pygame_device_ui._render_home,
        )
        for renderer in renderers:
            surface.fill((255, 255, 255))
            renderer(pygame, surface, fonts, workflow)
            bounds = surface.get_bounding_rect(min_alpha=1)
            assert bounds.left >= 0 and bounds.top >= 0
            assert bounds.right <= 800 and bounds.bottom <= 480
    finally:
        pygame.quit()
