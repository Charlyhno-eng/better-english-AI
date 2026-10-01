"""One stateless voice turn, with best-effort secondary pronunciation analysis."""
import asyncio
import logging
import io
import wave
from collections.abc import AsyncIterator, Sequence
from contextlib import aclosing
from dataclasses import dataclass, replace

from app.ai.contracts import Message
from app.audio.contracts import AudioData, PronunciationAssessment
from app.core.errors import InvalidAudioError, InvalidTextError
from app.services.english import Corrections, EnglishService
from app.services.pronunciation import PronunciationService
from app.services.synthesis import SynthesisService
from app.services.transcription import TranscriptionService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConversationWarning:
    code: str
    message: str


@dataclass(frozen=True)
class ConversationTurn:
    transcript: str
    reply: str
    audio: AudioData | None
    pronunciation: PronunciationAssessment | None
    warnings: tuple[ConversationWarning, ...]
    corrections: Corrections | None
    pronunciation_feedback: str | None


class ConversationService:
    def __init__(
        self, transcription: TranscriptionService, pronunciation: PronunciationService,
        english: EnglishService, synthesis: SynthesisService, *,
        pronunciation_timeout_seconds: float = 5, pronunciation_enabled: bool = True,
        max_reference_characters: int = 2000,
    ) -> None:
        self._transcription = transcription
        self._pronunciation = pronunciation
        self._english = english
        self._synthesis = synthesis
        self._pronunciation_timeout = pronunciation_timeout_seconds
        self._pronunciation_enabled = pronunciation_enabled
        self._max_reference_characters = max_reference_characters
        # A timed-out worker keeps running; do not queue more optional CPU work.
        self._pending_analysis: asyncio.Task[PronunciationAssessment] | None = None

    async def respond(
        self, audio: AudioData, *, history: Sequence[Message] = (),
        reference_text: str | None = None, analyze_pronunciation: bool = True,
    ) -> ConversationTurn:
        reference_text = self._validate(history, reference_text)
        transcript = await self._transcribe(audio)
        warnings: list[ConversationWarning] = []
        assessment = None
        if analyze_pronunciation and self._pronunciation_enabled:
            assessment = await self._analyze(audio, reference_text, transcript, warnings)
        try:
            turn = await self._english.converse_turn(transcript, history=history, pronunciation=assessment)
        except InvalidTextError:
            if assessment is None:
                raise
            # An invalid or oversized secondary result must not prevent the base reply.
            turn = await self._english.converse_turn(transcript, history=history)
        if assessment is not None and turn.pronunciation_feedback is None:
            warnings.append(ConversationWarning(
                "pronunciation_feedback_unavailable", "Natural pronunciation feedback is unavailable.",
            ))
        if turn.corrections is None:
            warnings.append(ConversationWarning("corrections_unavailable", "English corrections are unavailable."))
        reply = turn.reply
        try:
            spoken = await self._synthesis.synthesize(reply)
        except Exception as exc:
            # Keep the useful reply even if speech resources are unavailable.
            logger.warning("Conversation synthesis failed (%s)", type(exc).__name__)
            spoken = None
            warnings.append(ConversationWarning("speech_unavailable", "The reply audio is unavailable."))
        return ConversationTurn(transcript, reply, spoken, assessment, tuple(warnings),
                                turn.corrections, turn.pronunciation_feedback)

    async def stream(
        self, audio: AudioData, *, history: Sequence[Message] = (),
        reference_text: str | None = None, analyze_pronunciation: bool = True,
    ) -> AsyncIterator[tuple[str, ConversationTurn | AudioData]]:
        """Send reply and playable speech before optional pronunciation coaching."""
        reference_text = self._validate(history, reference_text)
        transcript = await self._transcribe(audio)
        turn = await self._english.converse_turn(transcript, history=history)
        warnings = []
        if turn.corrections is None:
            warnings.append(ConversationWarning("corrections_unavailable", "English corrections are unavailable."))
        result = ConversationTurn(transcript, turn.reply, None, None, tuple(warnings), turn.corrections, None)
        yield "reply", result
        frames = bytearray()
        sample_rate = None
        spoken = None
        try:
            async with aclosing(self._synthesis.stream(turn.reply)) as chunks:
                async for chunk in chunks:
                    # Keep one complete WAV for replay, never concatenate WAV headers.
                    with wave.open(io.BytesIO(chunk.content), "rb") as wav:
                        rate = wav.getframerate()
                        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or (sample_rate and rate != sample_rate):
                            raise ValueError("Invalid speech chunk format")
                        sample_rate = rate
                        frames.extend(wav.readframes(wav.getnframes()))
                    yield "audio", chunk
            if not frames:
                raise ValueError("No speech audio")
            output = io.BytesIO()
            with wave.open(output, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(sample_rate)
                wav.writeframes(frames)
            spoken = AudioData(output.getvalue(), "audio/wav")
        except Exception as exc:
            logger.warning("Conversation streaming synthesis failed (%s)", type(exc).__name__)
            warnings.append(ConversationWarning("speech_unavailable", "The reply audio is unavailable."))
        # Explicitly signal the end of speech before doing any optional CPU work.
        yield "feedback", replace(result, audio=spoken, warnings=tuple(warnings))
        assessment = None
        feedback = None
        if analyze_pronunciation and self._pronunciation_enabled:
            deadline = asyncio.get_running_loop().time() + self._pronunciation_timeout
            assessment = await self._analyze(audio, reference_text, transcript, warnings)
            if assessment is not None:
                try:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        raise TimeoutError
                    feedback = await asyncio.wait_for(
                        self._english.pronunciation_feedback(assessment), remaining,
                    )
                except Exception as exc:
                    logger.warning("Conversation coaching failed (%s)", type(exc).__name__)
                    warnings.append(ConversationWarning(
                        "pronunciation_feedback_unavailable", "Natural pronunciation feedback is unavailable.",
                    ))
        yield "done", replace(result, audio=spoken, pronunciation=assessment,
                              pronunciation_feedback=feedback, warnings=tuple(warnings))

    def _validate(self, history: Sequence[Message], reference_text: str | None) -> str | None:
        if reference_text is not None:
            reference_text = reference_text.strip()
            if not reference_text or len(reference_text) > self._max_reference_characters:
                raise InvalidTextError("The reference text is empty or exceeds the length limit.")
        if any(message.role not in {"user", "assistant"} or not message.content.strip() for message in history):
            raise InvalidTextError("History must contain nonempty user or assistant messages.")
        return reference_text

    async def _transcribe(self, audio: AudioData) -> str:
        transcript = (await self._transcription.transcribe(audio)).strip()
        if not transcript:
            raise InvalidAudioError("No speech was recognized in the recording.")
        return transcript

    async def _analyze(
        self, audio: AudioData, reference_text: str | None, transcript: str,
        warnings: list[ConversationWarning],
    ) -> PronunciationAssessment | None:
        if self._pending_analysis is not None and not self._pending_analysis.done():
            warnings.append(ConversationWarning(
                "pronunciation_busy", "Pronunciation analysis is still processing a previous recording.",
            ))
            return None
        task = asyncio.create_task(self._pronunciation.analyze(audio, reference_text or transcript))
        self._pending_analysis = task
        task.add_done_callback(self._analysis_finished)
        try:
            # Shield keeps ownership of CPU work after timeout or caller cancellation.
            assessment = await asyncio.wait_for(asyncio.shield(task), self._pronunciation_timeout)
            return replace(assessment, reference_inferred=True) if reference_text is None else assessment
        except TimeoutError:
            warnings.append(ConversationWarning(
                "pronunciation_timeout", "Pronunciation analysis exceeded the conversation time limit.",
            ))
        except Exception as exc:
            logger.warning("Conversation pronunciation failed (%s)", type(exc).__name__)
            warnings.append(ConversationWarning(
                "pronunciation_unavailable", "Pronunciation analysis is unavailable for this recording.",
            ))
        return None

    def _analysis_finished(self, task: asyncio.Task[PronunciationAssessment]) -> None:
        if not task.cancelled():
            task.exception()  # Retrieve late failures without logging private provider details.
        if self._pending_analysis is task:
            self._pending_analysis = None

    async def close(self) -> None:
        if self._pending_analysis is not None:
            await asyncio.gather(self._pending_analysis, return_exceptions=True)
