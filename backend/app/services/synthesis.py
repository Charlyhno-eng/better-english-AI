from app.audio.contracts import AudioData, TextToSpeech
from app.core.errors import InvalidTextError


class SynthesisService:
    """Convert an AI reply to encoded audio without exposing the TTS engine."""

    def __init__(self, provider: TextToSpeech, *, max_text_characters: int = 2000) -> None:
        self._provider = provider
        self._max_text_characters = max_text_characters

    async def synthesize(self, text: str) -> AudioData:
        if len(text) > self._max_text_characters:
            raise InvalidTextError("The text exceeds the speech synthesis limit.")
        text = text.strip()
        if not text:
            raise InvalidTextError("Speech synthesis requires non-empty text.")
        return await self._provider.synthesize(text)
