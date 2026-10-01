import asyncio
import io
import threading
import wave
from pathlib import Path
from typing import Any

from app.audio.contracts import AudioData
from app.core.errors import ProviderUnavailableError


def local_config_resources(config: dict) -> list[Path]:
    """Reject remote model/tokenizer paths before Pocket TTS can fetch them."""
    resources = [config["weights_path"], config["flow_lm"]["lookup_table"]["tokenizer_path"]]
    if config.get("weights_path_without_voice_cloning"):
        resources.append(config["weights_path_without_voice_cloning"])
    for section in ("flow_lm", "mimi"):
        if config.get(section, {}).get("weights_path"):
            resources.append(config[section]["weights_path"])
    paths = []
    for resource in resources:
        if not isinstance(resource, str) or "://" in resource:
            raise ValueError("Pocket TTS resources must be local files")
        path = Path(resource)
        if not path.is_file():
            raise FileNotFoundError("Pocket TTS resource is missing")
        paths.append(path)
    return paths


class PocketTTSProvider:
    """Lazy local CPU model and voice, serialized in a worker thread."""

    def __init__(self, config_path: Path, voice_path: Path, *, cpu_threads: int = 1) -> None:
        self._config_path = config_path
        self._voice_path = voice_path
        self._cpu_threads = cpu_threads
        self._model: Any = None
        self._voice_state: Any = None
        self._lock = threading.Lock()

    def _load(self) -> None:
        if self._model is not None:
            return
        if not self._config_path.is_file() or not self._voice_path.is_file():
            raise ProviderUnavailableError("Pocket TTS resources are missing. Install the local model and voice first.")
        try:
            import torch
            import yaml
            from pocket_tts import TTSModel

            local_config_resources(yaml.safe_load(self._config_path.read_text(encoding="utf-8")))
            torch.set_num_threads(self._cpu_threads)
            model = TTSModel.load_model(config=self._config_path)
            model.to("cpu")
            model.eval()
            voice_state = model.get_state_for_audio_prompt(self._voice_path)
            self._model = model
            self._voice_state = voice_state
        except ImportError as exc:
            raise ProviderUnavailableError("Pocket TTS dependencies are missing. Install the backend tts extra.") from exc
        except Exception as exc:
            raise ProviderUnavailableError("The local Pocket TTS model or voice could not be loaded.") from exc

    async def synthesize(self, text: str) -> AudioData:
        return await asyncio.to_thread(self._synthesize, text)

    def _synthesize(self, text: str) -> AudioData:
        with self._lock:
            self._load()
            try:
                import torch

                # Pocket TTS manages inference across its own generation threads.
                # An outer inference_mode creates tensors those threads cannot mutate.
                samples = self._model.generate_audio(self._voice_state, text, copy_state=True)
                samples = samples.detach().cpu().reshape(-1)
                if samples.numel() == 0 or not torch.isfinite(samples).all():
                    raise ValueError("Pocket TTS returned invalid audio")
                pcm = samples.clamp(-1, 1).mul(32767).to(torch.int16).numpy().astype("<i2").tobytes()
                output = io.BytesIO()
                with wave.open(output, "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(self._model.sample_rate)
                    wav.writeframes(pcm)
                return AudioData(output.getvalue(), "audio/wav")
            except Exception as exc:
                raise ProviderUnavailableError("Pocket TTS could not synthesize the text.") from exc

    async def close(self) -> None:
        await asyncio.to_thread(self._close)

    def _close(self) -> None:
        with self._lock:
            self._voice_state = None
            self._model = None
