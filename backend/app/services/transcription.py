from app.audio.contracts import AudioData, SpeechToText
from app.audio.wav import read_pcm
from app.core.errors import InvalidAudioError


class TranscriptionService:
    """Public transcription interface independent of the model implementation."""

    def __init__(
        self, provider: SpeechToText, *, max_audio_bytes: int = 10 * 1024 * 1024,
        max_duration_seconds: float = 60,
    ) -> None:
        self._provider = provider
        self._max_audio_bytes = max_audio_bytes
        self._max_duration_seconds = max_duration_seconds

    async def transcribe(self, audio: AudioData) -> str:
        if not audio.content:
            raise InvalidAudioError("The recording is empty.")
        if len(audio.content) > self._max_audio_bytes:
            raise InvalidAudioError("The recording exceeds the size limit.")
        read_pcm(audio, self._max_duration_seconds)
        return await self._provider.transcribe(audio)
