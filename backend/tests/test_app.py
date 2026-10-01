from typing import Annotated

import pytest
from fastapi import Depends, HTTPException
from fastapi.testclient import TestClient

from app.api.dependencies import get_health_service, get_settings
from app.core.config import Settings
from app.core.errors import ApplicationError, ProviderUnavailableError
from app.main import create_app


def test_app_configuration_and_dependency_injection() -> None:
    settings = Settings(_env_file=None, app_name="Test application", docs_enabled=False)
    app = create_app(settings)

    @app.get("/test-settings")
    def settings_route(request_settings: Annotated[Settings, Depends(get_settings)]):
        return {"name": request_settings.app_name}

    class UnavailableHealthService:
        def status(self) -> str:
            raise ProviderUnavailableError()

    app.dependency_overrides[get_health_service] = UnavailableHealthService
    with TestClient(app) as client:
        assert client.get("/test-settings").json() == {"name": "Test application"}
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/api/health").status_code == 503
    assert app.title == "Test application"
    assert create_app(Settings(_env_file=None)).state.settings is not settings


@pytest.mark.parametrize(
    "exception,status,code,message",
    [
        (ApplicationError("Safe message"), 400, "application_error", "Safe message"),
        (ProviderUnavailableError(), 503, "provider_unavailable", "The requested provider is unavailable."),
        (RuntimeError("private-test-key"), 500, "internal_error", "An unexpected error occurred."),
        (HTTPException(401, detail="private-test-key", headers={"WWW-Authenticate": "Bearer"}),
         401, "http_error", "Unauthorized"),
    ],
)
def test_errors_have_safe_consistent_responses(exception, status, code, message) -> None:
    app = create_app(Settings(_env_file=None))

    @app.get("/test-error")
    async def error_route():
        raise exception

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/test-error")
    assert response.status_code == status
    assert response.json() == {"error": {"code": code, "message": message}}
    assert "private-test-key" not in response.text
    if status == 401:
        assert response.headers["WWW-Authenticate"] == "Bearer"


def test_validation_and_missing_route() -> None:
    app = create_app(Settings(_env_file=None))

    @app.get("/test-validation")
    async def validation_route(count: int):
        return {"count": count}

    with TestClient(app) as client:
        response = client.get("/test-validation", params={"count": "private-test-key"})
        assert response.status_code == 422
        assert response.json() == {
            "error": {"code": "validation_error", "message": "The request is invalid."}
        }
        assert "private-test-key" not in response.text
        assert client.get("/missing").json() == {
            "error": {"code": "http_error", "message": "Not Found"}
        }


def test_replaceable_providers_and_cleanup():
    import asyncio
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.audio.contracts import PronunciationAssessment
    from test_transcription import recording

    stt = SimpleNamespace(transcribe=AsyncMock(return_value='Hello!'), close=AsyncMock())
    tts = SimpleNamespace(synthesize=AsyncMock(return_value=recording()), close=AsyncMock())
    pronunciation = SimpleNamespace(analyze=AsyncMock(return_value=PronunciationAssessment(())), close=AsyncMock())
    language = SimpleNamespace(complete=AsyncMock(return_value=json.dumps({
        'reply': 'Hello there!', 'corrections': {'corrected_text': 'Hello!', 'items': []},
        'pronunciation_feedback': 'Keep practising.',
    })), close=AsyncMock())
    app = create_app(Settings(_env_file=None), stt_provider=stt, tts_provider=tts,
                     pronunciation_provider=pronunciation, language_model=language)

    async def run():
        async with app.router.lifespan_context(app):
            result = await app.state.conversation_service.respond(recording())
            assert result.reply == 'Hello there!' and result.audio is not None
            assert result.pronunciation is not None
    asyncio.run(run())
    for provider in (stt, tts, pronunciation, language):
        provider.close.assert_awaited_once()


def test_private_exception_details_are_not_logged(caplog):
    app = create_app(Settings(_env_file=None))

    @app.get('/private-failure')
    async def fail():
        raise RuntimeError('private-learner-text')

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get('/private-failure')
    assert response.status_code == 500
    assert response.headers['cache-control'] == 'no-store'
    assert 'private-learner-text' not in caplog.text


def test_speech_preloading_is_nonblocking_and_resources_are_closed():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    async def run():
        started, release = asyncio.Event(), asyncio.Event()

        async def warmup():
            started.set()
            await release.wait()

        stt = SimpleNamespace(warmup=warmup, close=AsyncMock())
        tts = SimpleNamespace(warmup=AsyncMock(), close=AsyncMock())
        app = create_app(Settings(_env_file=None, audio={'preload_models': True}), stt_provider=stt, tts_provider=tts)
        async with app.router.lifespan_context(app):
            await asyncio.wait_for(started.wait(), 1)
            tts.warmup.assert_not_awaited()
            release.set()
        tts.warmup.assert_awaited_once()
        stt.close.assert_awaited_once()
        tts.close.assert_awaited_once()

    asyncio.run(run())
