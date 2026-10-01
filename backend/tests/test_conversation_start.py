import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.core.config import Settings
from app.core.errors import ProviderUnavailableError
from app.services.english import EnglishService
from test_transcription import recording


def setup_app():
    provider = SimpleNamespace(complete=AsyncMock(return_value='What would you like to discover in Japan?'))
    synthesis = SimpleNamespace(synthesize=AsyncMock(return_value=recording()))
    app = create_app(Settings(_env_file=None))
    app.state.english_service = EnglishService(provider)
    app.state.synthesis_service = synthesis
    return app, provider, synthesis


@pytest.mark.parametrize('mode', ['voice', 'writing'])
def test_ai_opens_without_learner_message(mode):
    app, provider, synthesis = setup_app()
    with TestClient(app) as client:
        response = client.post('/api/conversation/start', json={'topic': ' Japan ', 'mode': mode})
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    result = response.json()
    assert result['reply'] == 'What would you like to discover in Japan?'
    assert result['warnings'] == []
    messages = provider.complete.await_args.args[0]
    assert json.loads(messages[-1].content) == {'learner_text': 'Japan'}
    assert 'You speak first' in messages[0].content
    assert len(messages) == 2
    if mode == 'voice':
        assert result['audio']['media_type'] == 'audio/wav'
        synthesis.synthesize.assert_awaited_once_with(result['reply'])
    else:
        assert result['audio'] is None
        synthesis.synthesize.assert_not_awaited()


@pytest.mark.parametrize('topic', ['', '   ', 'x' * 501, 12])
def test_invalid_topic_does_not_call_providers(topic):
    app, provider, synthesis = setup_app()
    with TestClient(app) as client:
        assert client.post('/api/conversation/start', json={'topic': topic, 'mode': 'voice'}).status_code == 422
    provider.complete.assert_not_awaited()
    synthesis.synthesize.assert_not_awaited()


def test_opening_keeps_text_when_speech_fails():
    app, _, synthesis = setup_app()
    synthesis.synthesize.side_effect = RuntimeError('private details')
    with TestClient(app) as client:
        response = client.post('/api/conversation/start', json={'topic': 'Japan', 'mode': 'voice'})
    assert response.status_code == 200
    assert response.json()['reply']
    assert response.json()['audio'] is None
    assert response.json()['warnings'][0]['code'] == 'speech_unavailable'
    assert 'private details' not in response.text


def test_opening_provider_failure_and_request_bounds():
    app, provider, synthesis = setup_app()
    provider.complete.side_effect = ProviderUnavailableError('GLM unavailable.')
    with TestClient(app) as client:
        assert client.post('/api/conversation/start', json={'topic': 'Japan', 'mode': 'writing'}).status_code == 503
        assert client.post('/api/conversation/start', content='hello').status_code == 415
        assert client.post('/api/conversation/start', content='x' * 8193,
                           headers={'Content-Type': 'application/json'}).status_code == 413
    synthesis.synthesize.assert_not_awaited()
