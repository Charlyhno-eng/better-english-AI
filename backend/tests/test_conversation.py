import asyncio
import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.ai.contracts import Message
from app.api.dependencies import get_conversation_service
from app.audio.contracts import PronunciationAssessment
from app.core.config import Settings
from app.core.errors import InvalidAudioError, InvalidTextError, ProviderUnavailableError
from app.main import create_app
from app.services.conversation import ConversationService
from app.services.english import Corrections, EnglishService, EnglishTurn
from app.services.pronunciation import PronunciationService
from app.services.synthesis import SynthesisService
from app.services.transcription import TranscriptionService
from test_transcription import recording


@pytest.fixture
def stages():
    synthesis = SimpleNamespace(synthesize=AsyncMock(return_value=recording()))

    async def stream(text):
        yield await synthesis.synthesize(text)

    synthesis.stream = stream
    return (
        SimpleNamespace(transcribe=AsyncMock(return_value=' Hello there! ')),
        SimpleNamespace(analyze=AsyncMock(return_value=PronunciationAssessment((), reference_text='Hello there!'))),
        SimpleNamespace(converse_turn=AsyncMock(return_value=EnglishTurn(
            'Hi! How are you?', Corrections(corrected_text='Hello there!', items=[]), 'Try linking the words.'))),
        synthesis,
    )


def test_complete_turn(stages):
    service = ConversationService(*stages)
    audio = recording()
    history = (Message('assistant', 'Hello'),)
    result = asyncio.run(service.respond(audio, history=history))
    assert result.transcript == 'Hello there!'
    assert result.reply == 'Hi! How are you?'
    assert result.audio == recording() and not result.warnings
    assert result.pronunciation.reference_inferred is True
    stages[0].transcribe.assert_awaited_once_with(audio)
    stages[1].analyze.assert_awaited_once_with(audio, 'Hello there!')
    stages[2].converse_turn.assert_awaited_once_with('Hello there!', history=history,
                                             pronunciation=result.pronunciation)
    stages[3].synthesize.assert_awaited_once_with(result.reply)


def test_reference_and_disabled_analysis(stages):
    async def run():
        service = ConversationService(*stages)
        result = await service.respond(recording(), reference_text=' Hello ')
        assert not result.pronunciation.reference_inferred
        stages[1].analyze.assert_awaited_once_with(recording(), 'Hello')
        stages[1].analyze.reset_mock()
        result = await service.respond(recording(), analyze_pronunciation=False)
        assert result.pronunciation is None and not result.warnings
        await ConversationService(*stages, pronunciation_enabled=False).respond(recording())
        stages[1].analyze.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize('error', [ProviderUnavailableError(), RuntimeError('private-detail'),
                                    InvalidAudioError('safe-invalid-audio')])
def test_secondary_failure_keeps_reply(stages, error):
    stages[1].analyze.side_effect = error
    result = asyncio.run(ConversationService(*stages).respond(recording()))
    assert result.reply and result.audio and result.pronunciation is None
    assert result.warnings[0].code == 'pronunciation_unavailable'
    assert 'private-detail' not in str(result.warnings)
    stages[2].converse_turn.assert_awaited_once_with('Hello there!', history=(), pronunciation=None)


def test_analysis_timeout_busy_and_recovery(stages):
    async def run():
        release = asyncio.Event()
        async def analyze(*args):
            await release.wait()
            return PronunciationAssessment(())
        stages[1].analyze.side_effect = analyze
        service = ConversationService(*stages, pronunciation_timeout_seconds=.01)
        first = await service.respond(recording())
        assert first.warnings[0].code == 'pronunciation_timeout' and first.audio
        second = await service.respond(recording())
        assert second.warnings[0].code == 'pronunciation_busy' and second.audio
        assert stages[1].analyze.await_count == 1
        release.set()
        await service.close()
        third = await service.respond(recording())
        assert third.pronunciation is not None and not third.warnings
    asyncio.run(run())


def test_cancellation_does_not_start_more_optional_workers(stages):
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        async def analyze(*args):
            started.set()
            await release.wait()
            raise RuntimeError('private-late-error')
        stages[1].analyze.side_effect = analyze
        service = ConversationService(*stages)
        turn = asyncio.create_task(service.respond(recording()))
        await started.wait()
        turn.cancel()
        with pytest.raises(asyncio.CancelledError):
            await turn
        assert not service._pending_analysis.done()
        result = await service.respond(recording())
        assert result.warnings[0].code == 'pronunciation_busy'
        assert stages[1].analyze.await_count == 1
        release.set()
        await service.close()
        assert service._pending_analysis is None
    asyncio.run(run())


def test_pronunciation_context_rejected_by_english_falls_back(stages):
    stages[2].converse_turn.side_effect = [InvalidTextError('Oversized context'), EnglishTurn(
        'Reply without assessment', Corrections(corrected_text='Hello there!', items=[]), None)]
    result = asyncio.run(ConversationService(*stages).respond(recording()))
    assert result.reply == 'Reply without assessment' and result.audio
    assert result.warnings[0].code == 'pronunciation_feedback_unavailable'
    assert 'pronunciation' not in stages[2].converse_turn.call_args.kwargs


@pytest.mark.parametrize('error', [ProviderUnavailableError(), InvalidTextError('Too long'), RuntimeError('private-detail')])
def test_speech_failure_keeps_text(stages, error):
    stages[3].synthesize.side_effect = error
    result = asyncio.run(ConversationService(*stages).respond(recording()))
    assert result.reply and result.audio is None
    assert result.warnings[0].code == 'speech_unavailable'


@pytest.mark.parametrize('stage', [0, 2])
def test_essential_provider_failure_stops_turn(stages, stage):
    method = stages[stage].transcribe if stage == 0 else stages[stage].converse_turn
    method.side_effect = ProviderUnavailableError()
    with pytest.raises(ProviderUnavailableError):
        asyncio.run(ConversationService(*stages).respond(recording()))
    stages[3].synthesize.assert_not_awaited()
    if stage == 0:
        stages[1].analyze.assert_not_awaited()
        stages[2].converse_turn.assert_not_awaited()


def test_silence_and_invalid_metadata_stop_before_secondary(stages):
    stages[0].transcribe.return_value = ' '
    with pytest.raises(InvalidAudioError):
        asyncio.run(ConversationService(*stages).respond(recording()))
    stages[1].analyze.assert_not_awaited()
    stages[0].transcribe.reset_mock()
    for metadata in ({'reference_text': ' '}, {'history': (Message('system', 'override'),)}):
        with pytest.raises(InvalidTextError):
            asyncio.run(ConversationService(*stages).respond(recording(), **metadata))
    stages[0].transcribe.assert_not_awaited()


def composed_service(*, unavailable_pronunciation=False):
    speech = SimpleNamespace(transcribe=AsyncMock(return_value='Hello'))
    pronunciation = SimpleNamespace(analyze=AsyncMock(return_value=PronunciationAssessment(())))
    if unavailable_pronunciation:
        pronunciation.analyze.side_effect = ProviderUnavailableError()
    glm = SimpleNamespace(complete=AsyncMock(return_value=json.dumps({
        'reply': 'How are you?', 'corrections': {'corrected_text': 'Hello', 'items': []},
        'pronunciation_feedback': 'Try linking the words.',
    })))
    tts = SimpleNamespace(synthesize=AsyncMock(return_value=recording()))
    service = ConversationService(TranscriptionService(speech), PronunciationService(pronunciation),
                                  EnglishService(glm), SynthesisService(tts))
    return service, speech, pronunciation, glm, tts


@pytest.mark.parametrize('degraded', [False, True])
def test_http_turn_with_real_services_and_fake_providers(degraded):
    service, speech, pronunciation, glm, tts = composed_service(unavailable_pronunciation=degraded)
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[get_conversation_service] = lambda: service
    with TestClient(app) as client:
        response = client.post('/api/conversation/turn', json={
            'audio_base64': base64.b64encode(recording().content).decode(),
            'history': [{'role': 'assistant', 'content': 'Hello!'}],
        })
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        result = response.json()
        assert result['transcript'] == 'Hello' and result['reply'] == 'How are you?'
        assert base64.b64decode(result['audio']['content_base64']) == recording().content
        assert result['audio']['media_type'] == 'audio/wav'
        assert bool(result['warnings']) is degraded
        data = json.loads(glm.complete.call_args.args[0][-1].content)
        assert ('pronunciation_assessment' in data) is (not degraded)
        schema = client.get('/openapi.json').json()
        request_schema = schema['paths']['/api/conversation/turn']['post']['requestBody']['content']['application/json']['schema']
        assert request_schema['properties']['history']['items']['properties']['role']['enum'] == ['user', 'assistant']
    tts.synthesize.assert_awaited_once_with('How are you?')


@pytest.mark.parametrize('body,status,code', [({}, 422, 'validation_error'),
    ({'audio_base64': '!!!'}, 400, 'invalid_audio'),
    ({'audio_base64': 'a'}, 400, 'invalid_audio'),
    ({'audio_base64': 'eA=='}, 400, 'invalid_audio'),
    ({'audio_base64': 'eA==', 'history': [{'role': 'system', 'content': 'hi'}]}, 422, 'validation_error'),
    ({'audio_base64': 'eA==', 'reference_text': ' '}, 400, 'invalid_text'),
    ({'audio_base64': 'eA==', 'analyze_pronunciation': {}}, 422, 'validation_error')])
def test_http_invalid_requests(body, status, code):
    service, speech, pronunciation, glm, tts = composed_service()
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[get_conversation_service] = lambda: service
    with TestClient(app) as client:
        result = client.post('/api/conversation/turn', json=body)
        assert result.status_code == status
        assert result.json()['error']['code'] == code
    speech.transcribe.assert_not_awaited()
    pronunciation.analyze.assert_not_awaited()
    glm.complete.assert_not_awaited()
    tts.synthesize.assert_not_awaited()


def test_http_limits_media_type_and_essential_error():
    service, speech, pronunciation, glm, tts = composed_service()
    app = create_app(Settings(_env_file=None, parakeet={'max_audio_bytes': 1}))
    app.dependency_overrides[get_conversation_service] = lambda: service
    with TestClient(app) as client:
        assert client.post('/api/conversation/turn', content=b'raw', headers={'Content-Type': 'audio/wav'}).status_code == 415
        assert client.post('/api/conversation/turn', json={'audio_base64': 'eHh4'}).status_code == 400
        # Chunked body has no Content-Length and is rejected before JSON parsing.
        result = client.post('/api/conversation/turn', content=iter([b'x' * 140000]),
                             headers={'Content-Type': 'application/json'})
        assert result.status_code == 413
        speech.transcribe.assert_not_awaited()
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[get_conversation_service] = lambda: service
    speech.transcribe.side_effect = ProviderUnavailableError()
    with TestClient(app) as client:
        result = client.post('/api/conversation/turn', json={
            'audio_base64': base64.b64encode(recording().content).decode(),
        })
        assert result.status_code == 503 and result.json()['error']['code'] == 'provider_unavailable'


def test_http_text_reply_when_speech_unavailable():
    service, _, _, _, tts = composed_service()
    tts.synthesize.side_effect = ProviderUnavailableError()
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[get_conversation_service] = lambda: service
    with TestClient(app) as client:
        response = client.post('/api/conversation/turn', json={
            'audio_base64': base64.b64encode(recording().content).decode(),
            'analyze_pronunciation': False,
        })
        assert response.status_code == 200
        result = response.json()
        assert result['audio'] is None and result['pronunciation'] is None
        assert result['reply'] == 'How are you?'
        assert result['warnings'][0]['code'] == 'speech_unavailable'


def test_settings_validate_analysis_deadline_and_disabled_analysis():
    from pydantic import ValidationError
    for value in (0, -1, float('nan'), float('inf')):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, conversation={'pronunciation_timeout_seconds': value})
    _, _, pronunciation, _, _ = composed_service()
    app = create_app(Settings(_env_file=None, conversation={'pronunciation_enabled': False}))
    # Per-application composition uses the configured service behavior.
    app.state.transcription_service._provider = SimpleNamespace(transcribe=AsyncMock(return_value='Hello'))
    app.state.english_service._provider = SimpleNamespace(complete=AsyncMock(return_value=json.dumps({
        'reply': 'Hi', 'corrections': {'corrected_text': 'Hello', 'items': []},
        'pronunciation_feedback': None,
    })))
    app.state.synthesis_service._provider = SimpleNamespace(synthesize=AsyncMock(return_value=recording()))
    app.state.pronunciation_service._provider = pronunciation
    with TestClient(app) as client:
        response = client.post('/api/conversation/turn', json={
            'audio_base64': base64.b64encode(recording().content).decode(),
        })
        assert response.status_code == 200 and response.json()['pronunciation'] is None
    pronunciation.analyze.assert_not_awaited()


@pytest.mark.parametrize('missing', ['corrections', 'pronunciation_feedback', 'both'])
def test_http_missing_secondary_teaching_data_keeps_conversation(missing):
    service, _, _, glm, tts = composed_service()
    data = json.loads(glm.complete.return_value)
    if missing in {'corrections', 'both'}:
        data['corrections'] = {'private-detail': 'invalid'}
    if missing in {'pronunciation_feedback', 'both'}:
        data['pronunciation_feedback'] = 42
    glm.complete.return_value = json.dumps(data)
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[get_conversation_service] = lambda: service
    with TestClient(app) as client:
        result = client.post('/api/conversation/turn', json={
            'audio_base64': base64.b64encode(recording().content).decode(),
        })
        assert result.status_code == 200
        body = result.json()
        assert body['reply'] == 'How are you?' and body['audio']
        codes = {warning['code'] for warning in body['warnings']}
        assert ('corrections_unavailable' in codes) is (missing in {'corrections', 'both'})
        assert ('pronunciation_feedback_unavailable' in codes) is (missing in {'pronunciation_feedback', 'both'})
        assert 'private-detail' not in result.text
    glm.complete.assert_awaited_once()
    tts.synthesize.assert_awaited_once_with('How are you?')


def test_http_structured_corrections_and_documented_response():
    service, _, _, glm, _ = composed_service()
    glm.complete.return_value = json.dumps({
        'reply': 'What did you do there?',
        'corrections': {'corrected_text': 'I went to the park.', 'items': [{
            'category': 'grammar', 'original': 'goed', 'replacement': 'went',
            'explanation': 'Go has an irregular past tense.',
        }]},
        'pronunciation_feedback': 'Practise the vowel in park.',
    })
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[get_conversation_service] = lambda: service
    with TestClient(app) as client:
        result = client.post('/api/conversation/turn', json={
            'audio_base64': base64.b64encode(recording().content).decode(),
            'reference_text': 'I went to the park.',
        })
        assert result.status_code == 200
        body = result.json()
        assert body['corrections']['items'][0]['category'] == 'grammar'
        assert body['corrections']['items'][0]['replacement'] == 'went'
        assert body['pronunciation_feedback'] == 'Practise the vowel in park.'
        assert body['pronunciation']['reference_inferred'] is False
        assert body['warnings'] == []
        schema = client.get('/openapi.json').json()
        operation = schema['paths']['/api/conversation/turn']['post']
        assert set(operation['responses']) >= {'200', '400', '413', '415', '422', '503'}
        fields = schema['components']['schemas']['ConversationResponse']['properties']
        assert set(fields) == {'transcript', 'reply', 'corrections', 'pronunciation_feedback',
                               'pronunciation', 'audio', 'warnings'}
    glm.complete.assert_awaited_once()


def test_http_invalid_structured_reply_does_not_call_tts():
    service, _, _, glm, tts = composed_service()
    glm.complete.return_value = '{"reply": " ", "private": "provider-details"}'
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[get_conversation_service] = lambda: service
    with TestClient(app) as client:
        result = client.post('/api/conversation/turn', json={
            'audio_base64': base64.b64encode(recording().content).decode(),
        })
        assert result.status_code == 503
        assert result.json()['error']['code'] == 'provider_unavailable'
        assert 'provider-details' not in result.text
    tts.synthesize.assert_not_awaited()


def test_stream_speech_precedes_optional_analysis_and_complete_wav_is_replayable(stages):
    stages[2].pronunciation_feedback = AsyncMock(return_value='Try linking the words.')
    first, second = recording(frames=100), recording(frames=200)

    async def speech(text):
        yield first
        yield second

    stages[3].stream = speech

    async def run():
        service = ConversationService(*stages)
        stream = service.stream(recording())
        kind, reply = await anext(stream)
        assert kind == 'reply' and reply.reply and reply.audio is None
        stages[1].analyze.assert_not_awaited()
        assert await anext(stream) == ('audio', first)
        assert await anext(stream) == ('audio', second)
        stages[1].analyze.assert_not_awaited()
        kind, spoken = await anext(stream)
        assert kind == 'feedback'
        import io
        import wave
        with wave.open(io.BytesIO(spoken.audio.content), 'rb') as wav:
            assert wav.getnframes() == 300
        kind, result = await anext(stream)
        assert kind == 'done' and result.pronunciation.reference_inferred
        assert result.pronunciation_feedback == 'Try linking the words.'
        assert result.audio == spoken.audio
        stages[2].converse_turn.assert_awaited_once_with('Hello there!', history=())
        await stream.aclose()

    asyncio.run(run())


def test_stream_analysis_and_coaching_timeouts_keep_spoken_reply(stages):
    async def stalled(*args):
        await asyncio.sleep(.1)
        return 'Late feedback'

    stages[2].pronunciation_feedback = AsyncMock(side_effect=stalled)

    async def run():
        service = ConversationService(*stages, pronunciation_timeout_seconds=.01)
        events = [event async for event in service.stream(recording())]
        assert [kind for kind, _ in events] == ['reply', 'audio', 'feedback', 'done']
        final = events[-1][1]
        assert final.audio and final.pronunciation
        assert final.warnings[0].code == 'pronunciation_feedback_unavailable'
        stages[1].analyze.side_effect = stalled
        final = [event async for event in service.stream(recording())][-1][1]
        assert final.audio and final.pronunciation is None
        assert final.warnings[0].code == 'pronunciation_timeout'
        await service.close()

    asyncio.run(run())


def test_stream_cancellation_closes_speech_without_starting_analysis(stages):
    closed = False

    async def speech(text):
        nonlocal closed
        try:
            yield recording()
            await asyncio.Event().wait()
        finally:
            closed = True

    stages[3].stream = speech

    async def run():
        stream = ConversationService(*stages).stream(recording())
        await anext(stream)
        await anext(stream)
        await stream.aclose()
        assert closed
        stages[1].analyze.assert_not_awaited()

    asyncio.run(run())


def test_stream_http_events_and_essential_errors():
    service, _, _, glm, _ = composed_service()
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[get_conversation_service] = lambda: service
    payload = {'audio_base64': base64.b64encode(recording().content).decode(), 'analyze_pronunciation': False}
    with TestClient(app) as client:
        response = client.post('/api/conversation/turn/stream', json=payload)
        assert response.status_code == 200
        assert response.headers['content-type'] == 'application/x-ndjson'
        assert response.headers['cache-control'] == 'no-store'
        events = [json.loads(line) for line in response.text.splitlines()]
        assert [event['type'] for event in events] == ['reply', 'audio', 'feedback', 'done']
        assert base64.b64decode(events[1]['data']['content_base64']) == recording().content
        assert events[-1]['data']['transcript'] == 'Hello'
        assert events[-1]['data']['warnings'] == []
        glm.complete.side_effect = ProviderUnavailableError('Safe failure')
        response = client.post('/api/conversation/turn/stream', json=payload)
        assert response.status_code == 503
        assert response.json()['error']['message'] == 'Safe failure'


def test_stream_speech_failure_keeps_reply(stages):
    stages[3].synthesize.side_effect = RuntimeError('private-speech-detail')

    async def run():
        events = [event async for event in ConversationService(*stages).stream(recording(), analyze_pronunciation=False)]
        assert [kind for kind, _ in events] == ['reply', 'feedback', 'done']
        final = events[-1][1]
        assert final.reply and final.audio is None
        assert final.warnings[0].code == 'speech_unavailable'
        assert 'private-speech-detail' not in str(final.warnings)

    asyncio.run(run())
