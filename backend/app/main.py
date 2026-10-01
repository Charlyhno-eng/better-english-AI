from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import register_error_handlers
from app.api.router import router
from app.audio.contracts import SpeechToText, TextToSpeech, PronunciationAnalyzer
from app.ai.contracts import LanguageModel
from app.audio.parakeet import MODEL_FILE, ParakeetProvider
from app.audio.pocket_tts import PocketTTSProvider
from app.audio.openpronounce import OpenPronounceProvider
from app.services.pronunciation import PronunciationService
from app.ai.glm import GLMProvider
from app.services.english import EnglishService
from app.services.conversation import ConversationService
from app.core.config import Settings
from app.services.transcription import TranscriptionService
from app.services.synthesis import SynthesisService
from app.services.setup import SetupService, saved_key


def create_app(
    settings: Settings | None = None, *,
    stt_provider: SpeechToText | None = None,
    tts_provider: TextToSpeech | None = None,
    pronunciation_provider: PronunciationAnalyzer | None = None,
    language_model: LanguageModel | None = None,
) -> FastAPI:
    """Compose replaceable providers; injected resources are owned by this application.

    Providers may expose an async close() for shutdown cleanup. Model imports and
    initialization stay in adapters, never in the API or use cases.
    """
    if settings is None:
        settings = Settings()
        persisted_key = saved_key()
        if persisted_key is not None:
            settings.glm.api_key = persisted_key
    provider = stt_provider if stt_provider is not None else ParakeetProvider(
        settings.parakeet.model_path or settings.audio.models_directory / MODEL_FILE,
        cpu_threads=settings.parakeet.cpu_threads,
        max_duration_seconds=settings.parakeet.max_duration_seconds,
    )
    tts_directory = settings.audio.models_directory / "pocket-tts"
    tts_provider = tts_provider if tts_provider is not None else PocketTTSProvider(
        settings.pocket_tts.config_path or tts_directory / "config.yaml",
        settings.pocket_tts.voice_path or tts_directory / "alba.safetensors",
        cpu_threads=settings.pocket_tts.cpu_threads,
    )

    glm_provider = language_model if language_model is not None else GLMProvider(settings.glm)
    analysis_provider = pronunciation_provider if pronunciation_provider is not None else OpenPronounceProvider(
        cpu_threads=settings.openpronounce.cpu_threads,
        max_duration_seconds=settings.openpronounce.max_duration_seconds,
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        try:
            yield
        finally:
            try:
                await application.state.setup_service.close()
                await application.state.conversation_service.close()
            finally:
                await close_providers()

    async def close_provider(resource):
        close = getattr(resource, "close", None)
        if close is not None:
            await close()

    async def close_providers():
        try:
            await close_provider(provider)
        finally:
            try:
                await close_provider(tts_provider)
            finally:
                try:
                    await close_provider(glm_provider)
                finally:
                    await close_provider(analysis_provider)

    application = FastAPI(
        title=settings.app_name,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        lifespan=lifespan,
    )
    application.state.settings = settings
    application.state.setup_service = SetupService(settings, glm_provider)
    application.state.synthesis_service = SynthesisService(
        tts_provider, max_text_characters=settings.pocket_tts.max_text_characters,
    )
    application.state.transcription_service = TranscriptionService(
        provider, max_audio_bytes=settings.parakeet.max_audio_bytes,
        max_duration_seconds=settings.parakeet.max_duration_seconds,
    )
    application.state.pronunciation_service = PronunciationService(
        analysis_provider,
        max_audio_bytes=settings.openpronounce.max_audio_bytes,
        max_duration_seconds=settings.openpronounce.max_duration_seconds,
        max_text_characters=settings.openpronounce.max_text_characters,
    )
    application.state.english_service = EnglishService(
        glm_provider, max_input_characters=settings.glm.max_input_characters,
        max_history_messages=settings.glm.max_history_messages,
    )
    application.state.conversation_service = ConversationService(
        application.state.transcription_service, application.state.pronunciation_service,
        application.state.english_service, application.state.synthesis_service,
        pronunciation_timeout_seconds=settings.conversation.pronunciation_timeout_seconds,
        pronunciation_enabled=settings.conversation.pronunciation_enabled,
        max_reference_characters=settings.openpronounce.max_text_characters,
    )
    register_error_handlers(application)
    application.include_router(router)
    return application


app = create_app()
