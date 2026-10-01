import asyncio
import os
import sys
import threading
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock

import pytest

from app.audio.contracts import AudioData, PronunciationAssessment
from app.audio.openpronounce import OpenPronounceProvider
from app.services.pronunciation import PronunciationService
from app.core.errors import InvalidAudioError, InvalidTextError, ProviderUnavailableError
from test_transcription import recording


@pytest.mark.parametrize('reference', [None, ' Hello '])
def test_service_delegates(reference):
    provider = SimpleNamespace(analyze=AsyncMock(return_value=PronunciationAssessment(())))
    audio = recording()
    asyncio.run(PronunciationService(provider).analyze(audio, reference))
    provider.analyze.assert_awaited_once_with(audio, reference.strip() if reference else None)


@pytest.mark.parametrize('audio,reference,limits,error', [
    (AudioData(b'', 'audio/wav'), None, {}, InvalidAudioError),
    (recording(), None, {'max_audio_bytes': 2}, InvalidAudioError),
    (recording(), None, {'max_duration_seconds': .001}, InvalidAudioError),
    (AudioData(b'bad', 'audio/webm'), None, {}, InvalidAudioError),
    (recording(), ' ', {}, InvalidTextError),
    (recording(), 'hello', {'max_text_characters': 2}, InvalidTextError),
])
def test_invalid_inputs(audio, reference, limits, error):
    provider = SimpleNamespace(analyze=AsyncMock())
    with pytest.raises(error):
        asyncio.run(PronunciationService(provider, **limits).analyze(audio, reference))
    provider.analyze.assert_not_called()


@pytest.fixture
def runtime(monkeypatch):
    # No optional dependencies or model weights needed.
    for name in ("OPENPRONOUNCE_DEVICE", "OPENPRONOUNCE_TTS", "OPENPRONOUNCE_PHONEME_MODEL"):
        monkeypatch.setenv(name, "test")
    waveform = MagicMock()
    numpy = SimpleNamespace(frombuffer=MagicMock(return_value=waveform), float32='float32')
    torch = SimpleNamespace(set_num_threads=MagicMock(), inference_mode=nullcontext)
    main_thread = threading.get_ident()
    def compare(*args, **kwargs):
        assert threading.get_ident() != main_thread
        assert os.environ['OPENPRONOUNCE_DEVICE'] == 'cpu'
        assert os.environ['OPENPRONOUNCE_TTS'] == 'piper'
        assert kwargs == {'sampling_rate': 16000, 'use_phone_model': True, 'lang': 'en'}
        return {
            'score': 80, 'transcribe': 'hello', 'acoustic_distance': 8,
            'feedback': 'Practice hello', 'prosody': {'f0': [100, 110], 'energy': [.4, .5]},
            'differences': {
                'expected_phones': [['h', 'ə']], 'heard_phones': ['h', 'ɛ'],
                'heard_phones_confidence': [.9, .8], 'phoneme_error_rate': .5,
                'word_error_rate': 0,
                'errors': [{'word': 'hello', 'position': 0, 'expected': 'hə',
                            'actual': 'hɛ', 'confidence': .8,
                            'phones': [{'expected': 'ə', 'heard': 'ɛ', 'confidence': .8}]}],
            },
        }
    sdk = SimpleNamespace(transcribe=MagicMock(return_value='hello'),
                          compare_audio_with_text=MagicMock(side_effect=compare))
    device = SimpleNamespace(get_device=lambda: SimpleNamespace(type='cpu'))
    for name, value in [('numpy', numpy), ('torch', torch), ('openpronounce', sdk),
                        ('openpronounce.device', device)]:
        monkeypatch.setitem(sys.modules, name, value)
    return sdk, torch


@pytest.mark.parametrize('reference', ['hello', None])
def test_cpu_result_mapping(runtime, reference):
    sdk, torch = runtime
    result = asyncio.run(OpenPronounceProvider().analyze(recording(), reference))
    assert result.reference_text == 'hello'
    assert result.reference_inferred is (reference is None)
    assert result.observed_phonemes == ('h', 'ɛ')
    assert result.errors[0].phonemes[0].observed == 'ɛ'
    assert result.pitch_hz == (100, 110)
    assert result.energy == (.4, .5)
    assert result.acoustic_distance == 8
    torch.set_num_threads.assert_called_once_with(2)
    assert sdk.transcribe.call_count == (1 if reference is None else 0)


def test_missing_speech_and_safe_failure(runtime):
    sdk, _ = runtime
    sdk.transcribe.return_value = ''
    with pytest.raises(InvalidAudioError):
        asyncio.run(OpenPronounceProvider().analyze(recording()))
    sdk.compare_audio_with_text.side_effect = RuntimeError('private detail')
    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(OpenPronounceProvider().analyze(recording(), 'hello'))
    assert 'private detail' not in str(raised.value)


def test_missing_dependency(monkeypatch):
    monkeypatch.setitem(sys.modules, 'openpronounce', None)
    with pytest.raises(ProviderUnavailableError):
        asyncio.run(OpenPronounceProvider().analyze(recording(), 'hello'))


def test_application_composition():
    from app.main import create_app
    from app.core.config import Settings
    app = create_app(Settings(_env_file=None, openpronounce={'max_text_characters': 2}))
    with pytest.raises(InvalidTextError):
        asyncio.run(app.state.pronunciation_service.analyze(recording(), 'hello'))


def test_rejects_preinitialized_gpu(runtime, monkeypatch):
    monkeypatch.setitem(sys.modules, 'openpronounce.device', SimpleNamespace(
        get_device=lambda: SimpleNamespace(type='cuda'),
    ))
    with pytest.raises(ProviderUnavailableError):
        asyncio.run(OpenPronounceProvider().analyze(recording(), 'hello'))
    runtime[0].compare_audio_with_text.assert_not_called()


def test_serializes_across_instances(runtime):
    import time
    sdk, _ = runtime
    compare = sdk.compare_audio_with_text.side_effect
    active = 0
    maximum = 0
    def slow_compare(*args, **kwargs):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        time.sleep(.01)
        result = compare(*args, **kwargs)
        active -= 1
        return result
    sdk.compare_audio_with_text.side_effect = slow_compare
    async def run():
        await asyncio.gather(*(OpenPronounceProvider().analyze(recording(), 'hello')
                               for _ in range(3)))
    asyncio.run(run())
    assert maximum == 1
