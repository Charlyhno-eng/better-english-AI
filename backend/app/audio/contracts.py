from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AudioData:
    """Encoded audio with a declared media type, independent of HTTP uploads."""

    content: bytes
    media_type: str


@dataclass(frozen=True)
class PhonemeAssessment:
    expected: str
    observed: str | None
    score: float | None


@dataclass(frozen=True)
class PronunciationError:
    word: str
    position: int
    expected: str
    observed: str | None
    confidence: float
    phonemes: tuple[PhonemeAssessment, ...]


@dataclass(frozen=True)
class PronunciationAssessment:
    phonemes: tuple[PhonemeAssessment, ...]
    reference_text: str | None = None
    reference_inferred: bool = False
    transcript: str = ""
    score: float | None = None
    errors: tuple[PronunciationError, ...] = ()
    expected_phonemes: tuple[tuple[str, ...], ...] = ()
    observed_phonemes: tuple[str, ...] = ()
    observed_confidences: tuple[float, ...] = ()
    phoneme_error_rate: float | None = None
    word_error_rate: float | None = None
    acoustic_distance: float | None = None
    pitch_hz: tuple[float, ...] = ()
    energy: tuple[float, ...] = ()
    feedback: str = ""


class SpeechToText(Protocol):
    async def transcribe(self, audio: AudioData) -> str:
        ...


class TextToSpeech(Protocol):
    async def synthesize(self, text: str) -> AudioData:
        ...


class PronunciationAnalyzer(Protocol):
    async def analyze(self, audio: AudioData, reference_text: str | None = None) -> PronunciationAssessment:
        ...
