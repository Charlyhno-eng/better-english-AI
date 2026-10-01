import asyncio
import io
import sys
import threading
import time
import wave
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_synthesis_service
from app.audio.contracts import AudioData
from app.audio.pocket_tts import PocketTTSProvider, local_config_resources
from app.core.config import Settings
from app.core.errors import InvalidTextError, ProviderUnavailableError
from app.main import create_app
from app.services.synthesis import SynthesisService


def test_service_normalizes_text_and_delegates() -> None:
    provider = SimpleNamespace(synthesize=AsyncMock(return_value=AudioData(b"wav", "audio/wav")))
    result = asyncio.run(SynthesisService(provider).synthesize(" Hello! \n"))
    assert result == AudioData(b"wav", "audio/wav")
    provider.synthesize.assert_awaited_once_with("Hello!")


@pytest.mark.parametrize("text", ["", " \n\t", "x" * 11])
def test_service_rejects_invalid_text(text) -> None:
    provider = SimpleNamespace(synthesize=AsyncMock())
    with pytest.raises(InvalidTextError):
        asyncio.run(SynthesisService(provider, max_text_characters=10).synthesize(text))
    provider.synthesize.assert_not_awaited()


def test_route_returns_playable_wav_and_documentation() -> None:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\0\0" * 100)
    provider = SimpleNamespace(synthesize=AsyncMock(return_value=AudioData(output.getvalue(), "audio/wav")))
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[get_synthesis_service] = lambda: SynthesisService(provider)
    with TestClient(app) as client:
        response = client.post("/api/audio/speech", json={"text": "Hello!"})
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/wav"
        assert response.headers["cache-control"] == "no-store"
        assert "inline" in response.headers["content-disposition"]
        with wave.open(io.BytesIO(response.content), "rb") as wav:
            assert wav.getframerate() == 24000
            assert wav.getsampwidth() == 2
            assert wav.getnframes() == 100
        schema = client.get("/openapi.json").json()
        assert "audio/wav" in schema["paths"]["/api/audio/speech"]["post"]["responses"]["200"]["content"]


@pytest.mark.parametrize("body,status", [({}, 422), ({"text": 1}, 422), ({"text": ""}, 422), ({"text": " "}, 400), ({"text": "x" * 2001}, 400)])
def test_route_rejects_invalid_requests(body, status) -> None:
    provider = SimpleNamespace(synthesize=AsyncMock())
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[get_synthesis_service] = lambda: SynthesisService(provider)
    with TestClient(app) as client:
        response = client.post("/api/audio/speech", json=body)
        assert response.status_code == status
        assert "error" in response.json()
    provider.synthesize.assert_not_awaited()


def test_route_returns_safe_provider_error() -> None:
    provider = SimpleNamespace(synthesize=AsyncMock(side_effect=ProviderUnavailableError()))
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[get_synthesis_service] = lambda: SynthesisService(provider)
    with TestClient(app) as client:
        response = client.post("/api/audio/speech", json={"text": "Hello"})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "provider_unavailable"


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    config = tmp_path / "config.yaml"
    voice = tmp_path / "alba.safetensors"
    config.touch()
    voice.touch()
    resource = tmp_path / "weights"
    resource.touch()
    yaml = SimpleNamespace(safe_load=lambda text: {"weights_path": str(resource), "flow_lm": {"lookup_table": {"tokenizer_path": str(resource)}}})
    torch = MagicMock()
    torch.inference_mode.side_effect = nullcontext
    samples = MagicMock()
    samples.numel.return_value = 100
    samples.clamp.return_value.mul.return_value.to.return_value.numpy.return_value.astype.return_value.tobytes.return_value = b"\0\0" * 100
    model = MagicMock()
    model.sample_rate = 24000
    model.generate_audio.return_value.detach.return_value.cpu.return_value.reshape.return_value = samples
    loader = MagicMock(return_value=model)
    for name, module in [("torch", torch), ("yaml", yaml), ("pocket_tts", SimpleNamespace(TTSModel=SimpleNamespace(load_model=loader)))]:
        monkeypatch.setitem(sys.modules, name, module)
    return PocketTTSProvider(config, voice), model, loader, torch, voice


def test_provider_reuses_model_and_voice_on_cpu(runtime) -> None:
    provider, model, loader, torch, voice = runtime

    async def run():
        for _ in range(2):
            audio = await provider.synthesize("Hello!")
            with wave.open(io.BytesIO(audio.content), "rb") as wav:
                assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 24000)
        await provider.close()

    asyncio.run(run())
    loader.assert_called_once()
    assert all(call.args == (1,) for call in torch.set_num_threads.call_args_list)
    assert torch.set_num_threads.call_count == 3  # load and both inferences
    model.to.assert_called_once_with("cpu")
    model.get_state_for_audio_prompt.assert_called_once_with(voice)
    assert model.generate_audio.call_args.kwargs == {"copy_state": True}
    assert provider._model is None and provider._voice_state is None


def test_inference_is_serialized_off_event_loop(runtime) -> None:
    provider, model, _, _, _ = runtime
    main_thread = threading.get_ident()
    active = 0
    maximum = 0
    audio = model.generate_audio.return_value

    def generate(*args, **kwargs):
        nonlocal active, maximum
        assert threading.get_ident() != main_thread
        active += 1
        maximum = max(maximum, active)
        time.sleep(0.02)
        active -= 1
        return audio

    model.generate_audio.side_effect = generate

    async def run():
        await asyncio.gather(*(provider.synthesize("Hello") for _ in range(3)))

    asyncio.run(run())
    assert maximum == 1


def test_missing_resources_are_reported(tmp_path) -> None:
    with pytest.raises(ProviderUnavailableError, match="resources are missing"):
        asyncio.run(PocketTTSProvider(tmp_path / "config.yaml", tmp_path / "voice").synthesize("Hello"))


def test_synthesis_failure_is_wrapped(runtime) -> None:
    provider, model, _, _, _ = runtime
    model.generate_audio.side_effect = RuntimeError("private details")
    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(provider.synthesize("Hello"))
    assert "private details" not in str(raised.value)
    assert isinstance(raised.value.__cause__, RuntimeError)


def test_remote_resources_are_rejected_before_loading(tmp_path) -> None:
    with pytest.raises(ValueError, match="local files"):
        local_config_resources({"weights_path": "hf://remote/weights", "flow_lm": {"lookup_table": {"tokenizer_path": "tokenizer"}}})


def test_application_releases_tts_model(monkeypatch, tmp_path) -> None:
    import app.main as module
    provider = SimpleNamespace(synthesize=AsyncMock(return_value=AudioData(b"wav", "audio/wav")), close=AsyncMock())
    monkeypatch.setattr(module, "PocketTTSProvider", lambda *args, **kwargs: provider)
    app = module.create_app(Settings(_env_file=None, pocket_tts={"max_text_characters": 5}))
    with TestClient(app) as client:
        assert client.post("/api/audio/speech", json={"text": "Hello"}).status_code == 200
        assert client.post("/api/audio/speech", json={"text": "Too long"}).status_code == 400
    provider.close.assert_awaited_once()


def test_stream_yields_before_generation_finishes_and_reuses_voice(runtime):
    provider, model, loader, _, _ = runtime
    release = threading.Event()
    samples = model.generate_audio.return_value

    def generate(*args, **kwargs):
        assert kwargs['copy_state'] is True
        yield samples
        assert release.wait(2)
        yield samples

    model.generate_audio_stream.side_effect = generate

    async def run():
        await provider.warmup()
        stream = provider.stream('Hello!')
        first = await asyncio.wait_for(anext(stream), 1)
        with wave.open(io.BytesIO(first.content), 'rb') as wav:
            assert wav.getnframes() == 100
        release.set()
        remaining = [chunk async for chunk in stream]
        assert len(remaining) == 1
        await provider.close()

    asyncio.run(run())
    loader.assert_called_once()
    model.get_state_for_audio_prompt.assert_called_once()
    model.generate_audio.assert_not_called()


def test_stream_cancellation_signals_upstream_and_releases_lock(runtime):
    provider, model, _, _, _ = runtime
    stopped = threading.Event()
    samples = model.generate_audio.return_value

    def generate(*args, stop, **kwargs):
        yield samples
        assert stop.wait(2)
        stopped.set()

    model.generate_audio_stream.side_effect = generate

    async def run():
        stream = provider.stream('Hello!')
        await anext(stream)
        await asyncio.wait_for(stream.aclose(), 1)
        assert stopped.is_set()
        assert not provider._lock.locked()
        # A following request can still use the cached model.
        assert await provider.synthesize('Hello!')
        await provider.close()

    asyncio.run(run())


def test_stream_errors_are_safe_and_release_worker(runtime):
    provider, model, _, _, _ = runtime
    model.generate_audio_stream.side_effect = RuntimeError('private-provider-details')

    async def run():
        with pytest.raises(ProviderUnavailableError, match='could not synthesize') as error:
            async for _ in provider.stream('Hello!'):
                pytest.fail('Generation failed before producing audio')
        assert 'private-provider-details' not in str(error.value)
        assert not provider._lock.locked()
        await provider.close()

    asyncio.run(run())


def test_service_stream_fallback_and_validation():
    provider = SimpleNamespace(synthesize=AsyncMock(return_value=AudioData(b'wav', 'audio/wav')))
    service = SynthesisService(provider, max_text_characters=10)

    async def run():
        assert [chunk async for chunk in service.stream(' Hello! ')] == [AudioData(b'wav', 'audio/wav')]
        with pytest.raises(InvalidTextError):
            await anext(service.stream(' '))

    asyncio.run(run())
    provider.synthesize.assert_awaited_once_with('Hello!')
