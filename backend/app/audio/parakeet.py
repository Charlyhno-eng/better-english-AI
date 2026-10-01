import asyncio
import threading
from pathlib import Path
from typing import Any

from app.audio.contracts import AudioData
from app.audio.wav import read_pcm
from app.core.errors import ProviderUnavailableError

REPOSITORY = "nvidia/parakeet-tdt-0.6b-v3"
MODEL_FILE = "parakeet-tdt-0.6b-v3.nemo"


class ParakeetProvider:
    """Lazy, serialized local CPU inference following the T.A.R.S. provider."""

    def __init__(
        self, model_path: Path, *, cpu_threads: int = 4,
        max_duration_seconds: float = 60,
    ) -> None:
        self._model_path = model_path
        self._cpu_threads = cpu_threads
        self._max_duration_seconds = max_duration_seconds
        self._model: Any = None
        # A worker-side lock remains held if an awaiting request is cancelled.
        self._lock = threading.Lock()

    async def transcribe(self, audio: AudioData) -> str:
        return await asyncio.to_thread(self._transcribe, audio)

    async def warmup(self) -> None:
        if self._model_path.is_file():
            await asyncio.to_thread(self._prepare)

    def _prepare(self) -> None:
        with self._lock:
            self._load()

    def _load(self) -> None:
        if self._model is not None:
            return
        if not self._model_path.is_file():
            raise ProviderUnavailableError(
                "Parakeet checkpoint is missing. Install the local model first."
            )
        try:
            import torch
            import nemo.collections.asr as nemo_asr

            torch.set_num_threads(self._cpu_threads)
            model = nemo_asr.models.ASRModel.restore_from(
                restore_path=str(self._model_path), map_location="cpu"
            )
            model.to("cpu")
            model.freeze()
            model.eval()
            self._model = model
        except ImportError as exc:
            raise ProviderUnavailableError(
                "Parakeet dependencies are missing. Install the backend stt extra."
            ) from exc
        except Exception as exc:
            raise ProviderUnavailableError("The local Parakeet model could not be loaded.") from exc

    def _transcribe(self, audio: AudioData) -> str:
        pcm = read_pcm(audio, self._max_duration_seconds)
        with self._lock:
            self._load()
            try:
                import torch

                torch.set_num_threads(self._cpu_threads)

                # bytearray owns writable memory; the float conversion owns its tensor.
                waveform = torch.frombuffer(bytearray(pcm), dtype=torch.int16)
                waveform = waveform.to(dtype=torch.float32, device="cpu").div_(32768.0)
                with torch.inference_mode():
                    results = self._model.transcribe(
                        [waveform], use_lhotse=False, batch_size=1,
                        num_workers=0, verbose=False,
                    )
                text = getattr(results[0], "text", results[0])
                if not isinstance(text, str):
                    raise ValueError("Unexpected Parakeet response")
                return text.strip()
            except Exception as exc:
                raise ProviderUnavailableError("Parakeet could not transcribe the recording.") from exc

    async def close(self) -> None:
        await asyncio.to_thread(self._close)

    def _close(self) -> None:
        with self._lock:
            self._model = None
