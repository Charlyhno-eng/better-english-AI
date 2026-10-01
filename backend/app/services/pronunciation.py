from app.audio.contracts import AudioData, PronunciationAnalyzer, PronunciationAssessment
from app.core.errors import InvalidAudioError, InvalidTextError
from app.audio.wav import read_pcm


class PronunciationService:
    """Bounded audio/text input and a replaceable analyzer, independent of GLM."""
    def __init__(
        self, provider: PronunciationAnalyzer, *, max_audio_bytes: int = 10 * 1024 * 1024,
        max_duration_seconds: float = 60, max_text_characters: int = 2000,
    ) -> None:
        self._provider = provider
        self._max_audio_bytes = max_audio_bytes
        self._max_duration_seconds = max_duration_seconds
        self._max_text_characters = max_text_characters

    async def analyze(
        self, audio: AudioData, reference_text: str | None = None,
    ) -> PronunciationAssessment:
        if reference_text is not None:
            reference_text = reference_text.strip()
            if not reference_text or len(reference_text) > self._max_text_characters:
                raise InvalidTextError("The reference text is empty or exceeds the length limit.")
        if not audio.content or len(audio.content) > self._max_audio_bytes:
            raise InvalidAudioError("The recording is empty or exceeds the size limit.")
        read_pcm(audio, self._max_duration_seconds)
        return await self._provider.analyze(audio, reference_text)
