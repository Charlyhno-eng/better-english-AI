import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.core.config import Settings
from app.core.errors import ProviderUnavailableError
from app.services.english import EnglishService


CORRECTIONS = {'corrected_text': 'I have an apple.', 'items': [
    {'category': 'grammar', 'original': 'has', 'replacement': 'have',
     'explanation': 'Use have with I.'}]}


def make_app(output):
    provider = SimpleNamespace(complete=AsyncMock(return_value=output))
    app = create_app(Settings(_env_file=None))
    app.state.english_service = EnglishService(provider)
    return app, provider


def test_writing_endpoint_reuses_structured_tutor():
    app, provider = make_app(json.dumps(CORRECTIONS))
    with TestClient(app) as client:
        response = client.post('/api/writing/corrections', json={'text': ' I has a apple. '})
    assert response.status_code == 200
    assert response.json() == CORRECTIONS
    assert response.headers['cache-control'] == 'no-store'
    messages = provider.complete.await_args.args[0]
    assert json.loads(messages[-1].content) == {'learner_text': 'I has a apple.'}
    assert 'short English explanation' in messages[0].content
    provider.complete.assert_awaited_once()


@pytest.mark.parametrize('payload,status', [({'text': ' '}, 400), ({'text': ''}, 422),
                                           ({'text': 12}, 422), ({'text': 'a' * 20001}, 400)])
def test_invalid_writing_never_calls_glm(payload, status):
    app, provider = make_app('unused')
    with TestClient(app) as client:
        response = client.post('/api/writing/corrections', json=payload)
    assert response.status_code == status
    provider.complete.assert_not_awaited()


@pytest.mark.parametrize('output', ['private model output', '{}',
    '{"corrected_text":"fine","items":[{"category":"made_up"}]}'])
def test_malformed_corrections_safe_error(output):
    app, provider = make_app(output)
    with TestClient(app) as client:
        response = client.post('/api/writing/corrections', json={'text': 'Hello'})
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'provider_unavailable'
    assert output not in response.text


def test_no_errors_unchanged_text():
    provider = SimpleNamespace(complete=AsyncMock(return_value='{"corrected_text":"Hello!","items":[]}'))
    result = asyncio.run(EnglishService(provider).correct_writing('Hello!'))
    assert result.corrected_text == 'Hello!' and not result.items


def test_writing_keeps_ideal_punctuation_but_hides_punctuation_only_nits():
    output = {
        'corrected_text': 'Hi, how are you doing today?',
        'items': [
            {'category': 'grammar', 'original': 'Hi how are you doing today ?',
             'replacement': 'Hi, how are you doing today?',
             'explanation': 'Add a comma after the greeting and move the question mark.'},
            {'category': 'style', 'original': 'Hi how', 'replacement': 'Hi, how',
             'explanation': 'The comma makes the greeting more natural.'},
            {'category': 'spelling', 'original': 'tuday', 'replacement': 'today',
             'explanation': "The word is spelled 'today' with an 'o'."},
        ],
    }
    provider = SimpleNamespace(complete=AsyncMock(return_value=json.dumps(output)))

    result = asyncio.run(EnglishService(provider).correct_writing('Hi how are you doing tuday ?'))

    assert result.corrected_text == 'Hi, how are you doing today?'
    assert [(item.original, item.replacement) for item in result.items] == [('tuday', 'today')]
    system_prompt = provider.complete.await_args.args[0][0].content
    assert 'silently normalize these in corrected_text' in system_prompt


def test_bounds_and_content_type():
    app, provider = make_app('unused')
    with TestClient(app) as client:
        assert client.post('/api/writing/corrections', content='hello').status_code == 415
        response = client.post('/api/writing/corrections', content='x' * 130000,
                               headers={'Content-Type': 'application/json'})
        assert response.status_code == 413
    provider.complete.assert_not_awaited()


def test_provider_unavailable():
    app, provider = make_app('unused')
    provider.complete.side_effect = ProviderUnavailableError('GLM unavailable.')
    with TestClient(app) as client:
        assert client.post('/api/writing/corrections', json={'text': 'Hello'}).status_code == 503
