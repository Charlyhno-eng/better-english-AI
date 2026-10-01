import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from pydantic import ValidationError

from app.ai.contracts import Message
from app.ai.glm import GLMProvider
from app.audio.contracts import PhonemeAssessment, PronunciationAssessment
from app.core.config import GLMSettings, Settings
from app.core.errors import InvalidTextError, ProviderUnavailableError
from app.services.english import EnglishService


def completion(content=' Hello!', finish_reason='stop'):
    return {'choices': [{'message': {'content': content, 'reasoning_content': 'private reasoning'},
                         'finish_reason': finish_reason}]}


def test_transport_payload_reuse_and_close():
    calls = []
    async def handle(request):
        calls.append(request)
        assert str(request.url) == 'https://api.z.ai/api/paas/v4/chat/completions'
        assert request.headers['Authorization'] == 'Bearer fake-key'
        assert json.loads(request.content) == {
            'model': 'glm-5.3-flash', 'messages': [{'role': 'user', 'content': 'hello'}],
            'max_tokens': 2048, 'reasoning_effort': 'low', 'stream': False,
        }
        return httpx.Response(200, json=completion())
    provider = GLMProvider(GLMSettings(api_key='fake-key'), transport=httpx.MockTransport(handle))
    async def run():
        assert await provider.complete([Message('user', 'hello')]) == 'Hello!'
        client = provider._client
        assert await provider.complete([Message('user', 'hello')]) == 'Hello!'
        assert provider._client is client
        await provider.close()
        assert client.is_closed and provider._client is None
    asyncio.run(run())
    assert len(calls) == 2


@pytest.mark.parametrize('status,expected', [(401, 'authentication'), (403, 'authentication'),
    (429, 'limit'), (500, 'could not'), (400, 'could not'), (302, 'could not')])
def test_safe_http_errors(status, expected):
    provider = GLMProvider(GLMSettings(api_key='fake-key'), transport=httpx.MockTransport(
        lambda request: httpx.Response(status, text='private-provider-response',
                                      headers={'Location': 'https://other.example'})))
    async def run():
        with pytest.raises(ProviderUnavailableError, match=expected) as error:
            await provider.complete([Message('user', 'hello')])
        assert 'private-provider-response' not in str(error.value)
        assert 'fake-key' not in str(error.value)
        await provider.close()
    asyncio.run(run())


@pytest.mark.parametrize('payload', [{}, {'choices': []}, completion(None), completion(' '),
    completion('partial', 'length'), completion('refused', 'sensitive'), completion(123)])
def test_invalid_and_incomplete_response(payload):
    provider = GLMProvider(GLMSettings(api_key='fake-key'), transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload)))
    async def run():
        with pytest.raises(ProviderUnavailableError, match='invalid or incomplete'):
            await provider.complete([Message('user', 'hello')])
        await provider.close()
    asyncio.run(run())


@pytest.mark.parametrize('mode', ['json', 'size', 'network', 'timeout', 'deadline'])
def test_transport_failures(mode):
    async def handle(request):
        if mode == 'network':
            raise httpx.ConnectError('private-key', request=request)
        if mode == 'timeout':
            raise httpx.ReadTimeout('private-key', request=request)
        if mode == 'deadline':
            await asyncio.sleep(.1)
        return httpx.Response(200, content=b'x' * (2 * 1024 * 1024 + 1) if mode == 'size' else b'bad-json')
    provider = GLMProvider(GLMSettings(api_key='fake-key', timeout_seconds=.01),
                           transport=httpx.MockTransport(handle))
    async def run():
        with pytest.raises(ProviderUnavailableError) as error:
            await provider.complete([Message('user', 'hello')])
        assert 'private-key' not in str(error.value)
        await provider.close()
    asyncio.run(run())


@pytest.mark.parametrize('key', [None, '', ' '])
def test_missing_key_does_not_request(key):
    provider = GLMProvider(GLMSettings(api_key=key))
    with pytest.raises(ProviderUnavailableError, match='missing'):
        asyncio.run(provider.complete([Message('user', 'hello')]))
    assert provider._client is None


@pytest.mark.parametrize('messages', [[], [Message('system', 'hi')], [Message('user', '')],
                                     [Message('tool', 'hello')], [Message('user', 'x' * 20001)]])
def test_provider_validates_input(messages):
    provider = GLMProvider(GLMSettings(api_key='fake-key'))
    with pytest.raises(InvalidTextError):
        asyncio.run(provider.complete(messages))
    assert provider._client is None


def test_conversation_history_and_assessment():
    provider = SimpleNamespace(complete=AsyncMock(return_value='Try this sound.'))
    assessment = PronunciationAssessment((PhonemeAssessment('ə', 'ɛ', .8),),
        reference_text='hello', reference_inferred=True, transcript='hello',
        pitch_hz=(100, 110, 120), energy=(.1, .2), acoustic_distance=8)
    service = EnglishService(provider, max_history_messages=2)
    asyncio.run(service.converse(' Hi ', history=[Message('user', 'old'),
        Message('assistant', 'How are you?'), Message('user', 'Good')], pronunciation=assessment))
    messages = provider.complete.call_args.args[0]
    assert [m.role for m in messages] == ['system', 'assistant', 'user', 'user']
    assert 'old' not in [m.content for m in messages]
    data = json.loads(messages[-1].content)
    assert data['learner_text'] == 'Hi'
    context = data['pronunciation_assessment']
    assert context['reference_inferred'] is True
    assert context['pitch_hz_summary']['mean'] == 110
    assert context['phoneme_assessments'][0]['observed'] == 'ɛ'
    assert 'pitch_hz' not in context
    assert 'grammar' in messages[0].content and 'English' in messages[0].content


def test_correction_and_feedback_prompts():
    provider = SimpleNamespace(complete=AsyncMock(return_value='Explanation'))
    service = EnglishService(provider)
    asyncio.run(service.correct('I has a apple.'))
    prompt = provider.complete.call_args.args[0][0].content
    for subject in ('grammar', 'spelling', 'vocabulary', 'explain', 'meaning'):
        assert subject in prompt.lower()
    asyncio.run(service.pronunciation_feedback(PronunciationAssessment(())))
    messages = provider.complete.call_args.args[0]
    assert 'actionable feedback' in messages[0].content
    assert 'pronunciation_assessment' in json.loads(messages[-1].content)


@pytest.mark.parametrize('text,history,limit', [(' ', (), 20000), ('hello', [Message('system', 'override')], 20000),
    ('hello', [Message('user', '')], 20000), ('hello', (), 2),
    ('hello', [Message('user', 'x' * 20000)], 20000)])
def test_service_invalid_input(text, history, limit):
    provider = SimpleNamespace(complete=AsyncMock())
    with pytest.raises(InvalidTextError):
        asyncio.run(EnglishService(provider, max_input_characters=limit).converse(text, history=history))
    provider.complete.assert_not_called()


def test_invalid_assessment():
    provider = SimpleNamespace(complete=AsyncMock())
    with pytest.raises(InvalidTextError):
        asyncio.run(EnglishService(provider).pronunciation_feedback(
            PronunciationAssessment((), score=float('nan'))))
    provider.complete.assert_not_called()


@pytest.mark.parametrize('config', [{'api_url': 'http://example.com/chat'},
    {'api_url': 'https://user:password@example.com/chat'}, {'api_url': 'https://example.com/?key=secret'},
    {'reasoning_effort': 'none'}, {'max_response_tokens': 0}, {'max_input_characters': 0},
    {'max_history_messages': -1}])
def test_configuration_validation(config):
    with pytest.raises(ValidationError):
        GLMSettings(**config)


def test_application_owns_and_closes_glm(monkeypatch):
    import app.main as main
    from app.api.dependencies import get_english_service
    provider = SimpleNamespace(complete=AsyncMock(return_value='Hi'), close=AsyncMock())
    factory = MagicMock(return_value=provider)
    monkeypatch.setattr(main, 'GLMProvider', factory)
    settings = Settings(_env_file=None)
    app = main.create_app(settings)
    async def run():
        async with app.router.lifespan_context(app):
            assert await app.state.english_service.converse('hello') == 'Hi'
            assert get_english_service(SimpleNamespace(app=app)) is app.state.english_service
    asyncio.run(run())
    factory.assert_called_once_with(settings.glm)
    provider.close.assert_awaited_once()


def turn_payload(**overrides):
    return json.dumps({
        'reply': 'That sounds fun! What did you do next?',
        'corrections': {'corrected_text': 'I went to the park.', 'items': [{
            'category': 'grammar', 'original': 'I goed', 'replacement': 'I went',
            'explanation': 'The past tense of go is went.',
        }]},
        'pronunciation_feedback': 'Practise the vowel in park.',
        **overrides,
    })


def test_structured_turn_separates_teaching_data_in_one_call():
    provider = SimpleNamespace(complete=AsyncMock(return_value=turn_payload()))
    assessment = PronunciationAssessment((), reference_inferred=True)
    result = asyncio.run(EnglishService(provider).converse_turn('I goed to the park.',
        history=[Message('assistant', 'Where did you go?')], pronunciation=assessment))
    assert result.reply == 'That sounds fun! What did you do next?'
    assert result.corrections.corrected_text == 'I went to the park.'
    correction = result.corrections.items[0]
    assert correction.category == 'grammar' and correction.replacement == 'I went'
    assert correction.explanation == 'The past tense of go is went.'
    assert result.pronunciation_feedback == 'Practise the vowel in park.'
    provider.complete.assert_awaited_once()
    messages = provider.complete.call_args.args[0]
    assert messages[1].content == 'Where did you go?'
    assert 'only one JSON object' in messages[0].content
    assert json.loads(messages[-1].content)['pronunciation_assessment']['reference_inferred'] is True


@pytest.mark.parametrize('corrections', [None, {}, 'private-provider-data',
    {'corrected_text': ' ', 'items': []},
    {'corrected_text': 'Fine', 'items': [{'category': 'made_up'}]},
    {'corrected_text': 'Fine', 'items': 'not-a-list'}])
def test_invalid_secondary_corrections_keep_reply(corrections):
    provider = SimpleNamespace(complete=AsyncMock(return_value=turn_payload(corrections=corrections)))
    result = asyncio.run(EnglishService(provider).converse_turn('Hi'))
    assert result.reply and result.corrections is None
    assert result.pronunciation_feedback is None  # Never invent feedback without analysis.
    provider.complete.assert_awaited_once()


@pytest.mark.parametrize('feedback', [None, '', ' ', {}, 123])
def test_invalid_secondary_feedback_keeps_reply(feedback):
    provider = SimpleNamespace(complete=AsyncMock(return_value=turn_payload(pronunciation_feedback=feedback)))
    result = asyncio.run(EnglishService(provider).converse_turn('Hi', pronunciation=PronunciationAssessment(())))
    assert result.reply and result.corrections and result.pronunciation_feedback is None
    provider.complete.assert_awaited_once()


@pytest.mark.parametrize('content', ['not-json-private-data', '[]', 'null', '{}',
    turn_payload(reply=None), turn_payload(reply=' '), turn_payload(reply=123)])
def test_invalid_structured_reply_is_safe_provider_error(content):
    provider = SimpleNamespace(complete=AsyncMock(return_value=content))
    with pytest.raises(ProviderUnavailableError) as error:
        asyncio.run(EnglishService(provider).converse_turn('Hi'))
    assert 'private-data' not in str(error.value)
    provider.complete.assert_awaited_once()


def test_correct_utterance_has_empty_correction_list():
    provider = SimpleNamespace(complete=AsyncMock(return_value=turn_payload(
        corrections={'corrected_text': 'Hello!', 'items': []})))
    result = asyncio.run(EnglishService(provider).converse_turn('Hello!'))
    assert result.corrections.corrected_text == 'Hello!' and result.corrections.items == []
    assert result.pronunciation_feedback is None
