import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, HttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class GLMSettings(BaseModel):
    api_key: SecretStr | None = None
    model: str = Field(default="glm-5.3-flash", min_length=1)
    timeout_seconds: float = Field(default=60, gt=0, allow_inf_nan=False)
    api_url: HttpUrl = HttpUrl("https://api.z.ai/api/paas/v4/chat/completions")
    max_response_tokens: int = Field(default=2048, ge=1, le=32768)
    reasoning_effort: Literal["low", "high", "max"] = "low"
    max_input_characters: int = Field(default=20000, ge=1)
    max_history_messages: int = Field(default=10, ge=0, le=100)

    @field_validator("api_url")
    @classmethod
    def secure_endpoint(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https" or value.username or value.password or value.query or value.fragment:
            raise ValueError("GLM endpoint must be HTTPS without credentials, query or fragment")
        return value


class AudioSettings(BaseModel):
    # Local providers must never silently select a GPU.
    device: Literal["cpu"] = "cpu"
    models_directory: Path = Path("data/models")
    preload_models: bool = True


class ParakeetSettings(BaseModel):
    # None uses audio.models_directory / parakeet-tdt-0.6b-v3.nemo.
    model_path: Path | None = None
    cpu_threads: int = Field(default=min(4, os.cpu_count() or 1), ge=1)
    max_audio_bytes: int = Field(default=10 * 1024 * 1024, ge=1)
    max_duration_seconds: float = Field(default=60, gt=0, allow_inf_nan=False)


class PocketTTSSettings(BaseModel):
    # None uses audio.models_directory / pocket-tts/{config.yaml,alba.safetensors}.
    config_path: Path | None = None
    voice_path: Path | None = None
    cpu_threads: int = Field(default=1, ge=1)
    max_text_characters: int = Field(default=2000, ge=1)


class OpenPronounceSettings(BaseModel):
    cpu_threads: int = Field(default=2, ge=1)
    max_audio_bytes: int = Field(default=10 * 1024 * 1024, ge=1)
    max_duration_seconds: float = Field(default=60, gt=0, allow_inf_nan=False)
    max_text_characters: int = Field(default=2000, ge=1)


class ConversationSettings(BaseModel):
    pronunciation_enabled: bool = True
    pronunciation_timeout_seconds: float = Field(default=5, gt=0, allow_inf_nan=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BETTER_ENGLISH_",
        env_nested_delimiter="__",
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_name: str = Field(default="Better English AI", min_length=1)
    docs_enabled: bool = True
    conversation: ConversationSettings = Field(default_factory=ConversationSettings)
    glm: GLMSettings = Field(default_factory=GLMSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    parakeet: ParakeetSettings = Field(default_factory=ParakeetSettings)
    openpronounce: OpenPronounceSettings = Field(default_factory=OpenPronounceSettings)
    pocket_tts: PocketTTSSettings = Field(default_factory=PocketTTSSettings)
