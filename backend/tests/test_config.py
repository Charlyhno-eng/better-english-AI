import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_environment_overrides_dotenv(monkeypatch, tmp_path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "BETTER_ENGLISH_APP_NAME=From file\n"
        "BETTER_ENGLISH_GLM__TIMEOUT_SECONDS=15\n"
        "BETTER_ENGLISH_GLM__API_KEY=private-test-key\n"
    )
    monkeypatch.setenv("BETTER_ENGLISH_APP_NAME", "From environment")
    settings = Settings(_env_file=dotenv)
    assert settings.app_name == "From environment"
    assert settings.glm.timeout_seconds == 15
    assert settings.glm.api_key.get_secret_value() == "private-test-key"
    assert "private-test-key" not in repr(settings)
    assert "private-test-key" not in settings.model_dump_json()


@pytest.mark.parametrize(
    "variable,value",
    [
        ("BETTER_ENGLISH_AUDIO__DEVICE", "cuda"),
        ("BETTER_ENGLISH_GLM__TIMEOUT_SECONDS", "0"),
        ("BETTER_ENGLISH_GLM__TIMEOUT_SECONDS", "nan"),
        ("BETTER_ENGLISH_DOCS_ENABLED", "invalid"),
        ("BETTER_ENGLISH_PARAKEET__CPU_THREADS", "0"),
        ("BETTER_ENGLISH_PARAKEET__MAX_AUDIO_BYTES", "0"),
        ("BETTER_ENGLISH_PARAKEET__MAX_DURATION_SECONDS", "nan"),
        ("BETTER_ENGLISH_POCKET_TTS__CPU_THREADS", "0"),
        ("BETTER_ENGLISH_POCKET_TTS__MAX_TEXT_CHARACTERS", "0"),
    ],
)
def test_invalid_configuration_fails(monkeypatch, variable, value) -> None:
    monkeypatch.setenv(variable, value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
