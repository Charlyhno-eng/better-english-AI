"""OpenPronounce 0.3 adapter; no language-model or transcription-service dependency."""
import asyncio
import os
import threading

from app.audio.contracts import AudioData, PhonemeAssessment, PronunciationAssessment, PronunciationError
from app.audio.wav import read_pcm
from app.core.errors import InvalidAudioError, ProviderUnavailableError

# Upstream models and device selection are process-global caches. A worker-side
# lock serializes all instances, including when an awaiting caller is cancelled.
_RUNTIME_LOCK = threading.Lock()


class OpenPronounceProvider:
    def __init__(self, *, cpu_threads: int = 2, max_duration_seconds: float = 60) -> None:
        self._cpu_threads = cpu_threads
        self._max_duration_seconds = max_duration_seconds

    async def analyze(
        self, audio: AudioData, reference_text: str | None = None,
    ) -> PronunciationAssessment:
        return await asyncio.to_thread(self._analyze, audio, reference_text)

    def _analyze(self, audio: AudioData, reference_text: str | None) -> PronunciationAssessment:
        pcm = read_pcm(audio, self._max_duration_seconds)
        with _RUNTIME_LOCK:
            try:
                # Set before importing upstream or resolving its cached device.
                os.environ["OPENPRONOUNCE_DEVICE"] = "cpu"
                os.environ["OPENPRONOUNCE_TTS"] = "piper"
                os.environ["OPENPRONOUNCE_PHONEME_MODEL"] = "facebook/wav2vec2-lv-60-espeak-cv-ft"
                import numpy as np
                import torch
                import openpronounce
                from openpronounce.device import get_device

                if get_device().type != "cpu":
                    raise RuntimeError("OpenPronounce was already initialized on a non-CPU device")
                torch.set_num_threads(self._cpu_threads)
                waveform = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
                with torch.inference_mode():
                    inferred = reference_text is None
                    reference = reference_text
                    if inferred:
                        reference = openpronounce.transcribe(waveform, lang="en").strip()
                        if not reference:
                            raise InvalidAudioError("No speech was recognized in the recording.")
                    result = openpronounce.compare_audio_with_text(
                        waveform, reference, sampling_rate=16000, use_phone_model=True, lang="en",
                    )
                differences = result["differences"]
                errors = tuple(
                    PronunciationError(
                        word=error["word"], position=error["position"],
                        expected=error["expected"], observed=error["actual"],
                        confidence=error["confidence"],
                        phonemes=tuple(PhonemeAssessment(
                            expected=phone["expected"], observed=phone["heard"],
                            score=phone["confidence"],
                        ) for phone in error["phones"]),
                    ) for error in differences["errors"]
                )
                return PronunciationAssessment(
                    phonemes=tuple(phone for error in errors for phone in error.phonemes),
                    reference_text=reference, reference_inferred=inferred,
                    transcript=result["transcribe"], score=result["score"], errors=errors,
                    expected_phonemes=tuple(tuple(group) for group in differences["expected_phones"]),
                    observed_phonemes=tuple(differences["heard_phones"]),
                    observed_confidences=tuple(differences["heard_phones_confidence"]),
                    phoneme_error_rate=differences["phoneme_error_rate"],
                    word_error_rate=differences["word_error_rate"],
                    acoustic_distance=result["acoustic_distance"],
                    pitch_hz=tuple(result["prosody"]["f0"]),
                    energy=tuple(result["prosody"]["energy"]),
                    feedback=result["feedback"],
                )
            except InvalidAudioError:
                raise
            except ImportError as exc:
                raise ProviderUnavailableError(
                    "OpenPronounce dependencies are missing. Install the pronunciation extra."
                ) from exc
            except Exception as exc:
                raise ProviderUnavailableError("OpenPronounce could not analyze the recording.") from exc
