import asyncio
import io
import sys
import threading
import time
import wave
from contextlib import nullcontext
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.audio.contracts import AudioData
from app.audio.parakeet import ParakeetProvider
from app.core.errors import InvalidAudioError, ProviderUnavailableError
from app.services.transcription import TranscriptionService


def recording(*, frames=160, rate=16000, channels=1, width=2) -> AudioData:
    stream = io.BytesIO()
    with wave.open(stream, "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(width)
        output.setframerate(rate)
        output.writeframes(b"\0" * frames * channels * width)
    return AudioData(stream.getvalue(), "audio/wav")


def test_service_delegates_without_model_details() -> None:
    audio = recording()

    class Provider:
        async def transcribe(self, received: AudioData) -> str:
            assert received is audio
            return "Hello!"

    assert asyncio.run(TranscriptionService(Provider()).transcribe(audio)) == "Hello!"


@pytest.mark.parametrize(
    "audio,limits",
    [
        (AudioData(b"", "audio/wav"), {}),
        (AudioData(b"not a WAV", "audio/wav"), {}),
        (AudioData(recording().content, "audio/webm"), {}),
        (recording(rate=44100), {}),
        (recording(channels=2), {}),
        (recording(width=1), {}),
        (recording(frames=0), {}),
        (AudioData(recording().content[:-2], "audio/wav"), {}),
        (recording(), {"max_audio_bytes": 10}),
        (recording(frames=16001), {"max_duration_seconds": 1}),
    ],
)
def test_invalid_audio_is_rejected_before_provider_call(audio, limits) -> None:
    class Provider:
        async def transcribe(self, audio):
            pytest.fail("Invalid input must not reach the model")

    with pytest.raises(InvalidAudioError):
        asyncio.run(TranscriptionService(Provider(), **limits).transcribe(audio))


@pytest.fixture
def model_runtime(monkeypatch, tmp_path):
    model_path = tmp_path / "model.nemo"
    model_path.touch()
    model = MagicMock()
    model.transcribe.return_value = [SimpleNamespace(text=" Hello world! ")]
    torch = MagicMock()
    torch.inference_mode.side_effect = nullcontext
    nemo = ModuleType("nemo")
    collections = ModuleType("nemo.collections")
    asr = ModuleType("nemo.collections.asr")
    asr.models = SimpleNamespace(ASRModel=SimpleNamespace(restore_from=MagicMock(return_value=model)))
    nemo.collections = collections
    collections.asr = asr
    for name, module in [("torch", torch), ("nemo", nemo), ("nemo.collections", collections), ("nemo.collections.asr", asr)]:
        monkeypatch.setitem(sys.modules, name, module)
    return model_path, model, torch, asr.models.ASRModel.restore_from


def test_provider_loads_once_and_forces_cpu(model_runtime) -> None:
    path, model, torch, restore = model_runtime
    provider = ParakeetProvider(path, cpu_threads=2)

    async def run():
        assert await provider.transcribe(recording()) == "Hello world!"
        model.transcribe.return_value = ["Bonjour !"]
        assert await provider.transcribe(recording()) == "Bonjour !"
        await provider.close()

    asyncio.run(run())
    restore.assert_called_once_with(restore_path=str(path), map_location="cpu")
    torch.set_num_threads.assert_called_once_with(2)
    model.to.assert_called_once_with("cpu")
    model.freeze.assert_called_once()
    model.eval.assert_called_once()
    torch.frombuffer.return_value.to.assert_called_with(dtype=torch.float32, device="cpu")
    assert model.transcribe.call_args.kwargs == {
        "use_lhotse": False, "batch_size": 1, "num_workers": 0, "verbose": False,
    }
    assert provider._model is None


def test_inference_is_serialized_and_off_event_loop(model_runtime) -> None:
    path, model, _, restore = model_runtime
    provider = ParakeetProvider(path)
    active = 0
    maximum = 0
    main_thread = threading.get_ident()

    def infer(*args, **kwargs):
        nonlocal active, maximum
        assert threading.get_ident() != main_thread
        active += 1
        maximum = max(maximum, active)
        time.sleep(0.02)
        active -= 1
        return [SimpleNamespace(text="Hello")]

    model.transcribe.side_effect = infer

    async def run():
        return await asyncio.gather(*(provider.transcribe(recording()) for _ in range(3)))

    assert asyncio.run(run()) == ["Hello"] * 3
    assert maximum == 1
    restore.assert_called_once()


def test_missing_checkpoint_is_a_safe_service_error(tmp_path) -> None:
    provider = ParakeetProvider(tmp_path / "missing.nemo")
    with pytest.raises(ProviderUnavailableError, match="checkpoint is missing"):
        asyncio.run(provider.transcribe(recording()))


def test_missing_runtime_is_a_safe_service_error(monkeypatch, tmp_path) -> None:
    path = tmp_path / "model.nemo"
    path.touch()
    monkeypatch.setitem(sys.modules, "torch", None)
    with pytest.raises(ProviderUnavailableError, match="dependencies are missing"):
        asyncio.run(ParakeetProvider(path).transcribe(recording()))


def test_model_failure_is_wrapped_and_can_be_retried(model_runtime) -> None:
    path, model, _, _ = model_runtime
    provider = ParakeetProvider(path)
    model.transcribe.side_effect = RuntimeError("private model detail")
    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(provider.transcribe(recording()))
    assert "private model detail" not in str(raised.value)
    assert isinstance(raised.value.__cause__, RuntimeError)
    model.transcribe.side_effect = None
    assert asyncio.run(provider.transcribe(recording())) == "Hello world!"


def test_application_owns_service_and_closes_provider(monkeypatch, tmp_path) -> None:
    import app.main as application_module
    from app.core.config import Settings

    provider = SimpleNamespace(transcribe=AsyncMock(return_value="Hello"), close=AsyncMock())
    factory = MagicMock(return_value=provider)
    monkeypatch.setattr(application_module, "ParakeetProvider", factory)
    settings = Settings(
        _env_file=None,
        audio={"models_directory": tmp_path},
        parakeet={"cpu_threads": 2, "max_audio_bytes": 100, "max_duration_seconds": 1},
    )
    app = application_module.create_app(settings)

    async def run():
        async with app.router.lifespan_context(app):
            assert await app.state.transcription_service.transcribe(recording(frames=10)) == "Hello"
            with pytest.raises(InvalidAudioError):
                await app.state.transcription_service.transcribe(recording())

    asyncio.run(run())
    factory.assert_called_once_with(
        tmp_path / "parakeet-tdt-0.6b-v3.nemo", cpu_threads=2, max_duration_seconds=1,
    )
    provider.close.assert_awaited_once()


def test_explicit_checkpoint_download(monkeypatch, tmp_path) -> None:
    from app.audio import download_parakeet
    from app.core.config import Settings

    settings = Settings(_env_file=None, audio={"models_directory": tmp_path / "models"})
    monkeypatch.setattr(download_parakeet, "Settings", lambda: settings)
    download = MagicMock(return_value=str(tmp_path / "models" / "parakeet-tdt-0.6b-v3.nemo"))
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(hf_hub_download=download))
    download_parakeet.main()
    download.assert_called_once_with(
        repo_id="nvidia/parakeet-tdt-0.6b-v3", filename="parakeet-tdt-0.6b-v3.nemo",
        local_dir=tmp_path / "models",
    )
