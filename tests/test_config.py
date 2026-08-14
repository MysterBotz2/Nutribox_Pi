import math

import pytest

from nutribox_pi.config import ConfigurationError, Settings


def test_settings_load_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NUTRIBOX_API_BASE_URL", "https://api.example.test/")
    monkeypatch.setenv("NUTRIBOX_HTTP_TIMEOUT_SECONDS", "3.5")
    monkeypatch.setenv("NUTRIBOX_SIMULATED_WEIGHT_GRAMS", "412")

    settings = Settings.from_env()

    assert settings.api_base_url == "https://api.example.test"
    assert settings.http_timeout_seconds == 3.5
    assert settings.simulated_weight_grams == 412


def test_api_base_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NUTRIBOX_API_BASE_URL", raising=False)

    with pytest.raises(ConfigurationError, match="required"):
        Settings.from_env()


@pytest.mark.parametrize(
    "url",
    [
        "",
        "file:///tmp/backend",
        "http:///missing-host",
        "example.test",
        "https://user:secret@example.test",
    ],
)
def test_settings_reject_invalid_api_url(url: str) -> None:
    with pytest.raises(ConfigurationError, match="URL"):
        Settings(api_base_url=url)


@pytest.mark.parametrize("timeout", [0, -1, math.inf, -math.inf, math.nan])
def test_settings_reject_invalid_timeout(timeout: float) -> None:
    with pytest.raises(ConfigurationError, match="timeout"):
        Settings(api_base_url="https://api.example.test", http_timeout_seconds=timeout)


@pytest.mark.parametrize("weight", [-1, 5001, math.inf, -math.inf, math.nan])
def test_settings_reject_invalid_weight(weight: float) -> None:
    with pytest.raises(ConfigurationError, match="weight"):
        Settings(api_base_url="https://api.example.test", simulated_weight_grams=weight)


@pytest.mark.parametrize("temperature", [math.inf, -math.inf, math.nan])
def test_settings_reject_nonfinite_temperature(temperature: float) -> None:
    with pytest.raises(ConfigurationError, match="temperature"):
        Settings(
            api_base_url="https://api.example.test",
            simulated_temperature_c=temperature,
        )
