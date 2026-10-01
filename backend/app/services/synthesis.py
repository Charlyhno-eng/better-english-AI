from collections.abc import AsyncIterator
from contextlib import aclosing

from app.audio.contracts import AudioData, TextToSpeech
from app.core.errors import InvalidTextError


class SynthesisService:
    """Convert an AI reply to encoded audio without exposing the TTS engine."""

    def __init__(self, provider: TextToSpeech, *, max_text_characters: int = 2000) -> None:
        self._provider = provider
        self._max_text_characters = max_text_characters

    async def synthesize(self, text: str) -> AudioData:
        return await self._provider.synthesize(self._validate(text))

    async def stream(self, text: str) -> AsyncIterator[AudioData]:
        text = self._validate(text)
        stream = getattr(self._provider, "stream", None)
        if stream is None:
            yield await self._provider.synthesize(text)
        else:
            async with aclosing(stream(text)) as chunks:
                async for chunk in chunks:
                    yield chunk

    def _validate(self, text: str) -> str:
        if len(text) > self._max_text_characters:
            raise InvalidTextError("The text exceeds the speech synthesis limit.")
        text = text.strip()
        if not text:
            raise InvalidTextError("Speech synthesis requires non-empty text.")
        return text
