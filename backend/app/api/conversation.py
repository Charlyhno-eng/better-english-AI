import base64
import json
import logging
from contextlib import aclosing
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.ai.contracts import Message
from app.api.dependencies import get_conversation_service, get_settings, get_english_service, get_synthesis_service
from app.audio.contracts import PronunciationAssessment
from app.audio.contracts import AudioData
from app.api.requests import read_json, decode_audio, encoded_audio_limit
from app.api.schemas import ErrorResponse, HistoryMessage
from app.core.config import Settings
from app.core.errors import ApplicationError
from app.services.conversation import ConversationService, ConversationWarning, ConversationTurn
from app.services.english import Corrections, EnglishService
from app.services.synthesis import SynthesisService

router = APIRouter()
logger = logging.getLogger(__name__)


class ConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audio_base64: str = Field(min_length=1)
    media_type: str = "audio/wav"
    history: list[HistoryMessage] = Field(default_factory=list, max_length=100)
    reference_text: str | None = None
    analyze_pronunciation: bool = True


class ConversationAudio(BaseModel):
    media_type: str
    content_base64: str


class ConversationResponse(BaseModel):
    transcript: str
    reply: str
    corrections: Corrections | None
    pronunciation_feedback: str | None
    audio: ConversationAudio | None
    pronunciation: PronunciationAssessment | None
    warnings: tuple[ConversationWarning, ...]


class ConversationStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    topic: str = Field(min_length=1, max_length=500)
    mode: Literal["voice", "writing"]


class ConversationStartResponse(BaseModel):
    reply: str
    audio: ConversationAudio | None
    warnings: tuple[ConversationWarning, ...]


@router.post("/conversation/start", response_model=ConversationStartResponse,
             summary="Let the AI open a conversation about a chosen topic",
             responses={code: {"model": ErrorResponse} for code in (400, 413, 415, 422, 503)},
             openapi_extra={"requestBody": {"required": True, "content": {"application/json": {
                 "schema": ConversationStartRequest.model_json_schema()}}}})
async def start_conversation(
    request: Request, response: Response,
    english: Annotated[EnglishService, Depends(get_english_service)],
    synthesis: Annotated[SynthesisService, Depends(get_synthesis_service)],
) -> ConversationStartResponse:
    payload = await read_json(request, ConversationStartRequest, 8192)
    reply = await english.start_conversation(payload.topic)
    audio = None
    warnings = []
    if payload.mode == "voice":
        try:
            spoken = await synthesis.synthesize(reply)
            audio = ConversationAudio(media_type=spoken.media_type,
                                      content_base64=base64.b64encode(spoken.content).decode("ascii"))
        except Exception as exc:
            logger.warning("Opening speech failed (%s)", type(exc).__name__)
            warnings.append(ConversationWarning("speech_unavailable", "The reply audio is unavailable."))
    response.headers["Cache-Control"] = "no-store"
    return ConversationStartResponse(reply=reply, audio=audio, warnings=tuple(warnings))


# Inline the nested model for the manually documented bounded JSON reader.
_REQUEST_SCHEMA = ConversationRequest.model_json_schema()
_REQUEST_SCHEMA.pop("$defs", None)
_REQUEST_SCHEMA["properties"]["history"]["items"] = HistoryMessage.model_json_schema()


@router.post(
    "/conversation/turn", response_model=ConversationResponse,
    summary="Send a voice message and receive a structured learning turn",
    description="Returns transcription, separate English corrections and pronunciation feedback, "
                "the AI reply, and base64 WAV reply audio. Secondary failures return nullable "
                "fields with warnings; no conversation state is stored.",
    responses={status: {"model": ErrorResponse, "description": description} for status, description in (
        (400, "Invalid audio, reference text or history; no recognized speech"),
        (413, "Request body exceeds the size limit"),
        (415, "Request content type must be application/json"),
        (422, "Malformed JSON or invalid request schema"),
        (503, "Transcription or conversation provider unavailable"),
    )},
    openapi_extra={"requestBody": {"required": True, "content": {"application/json": {
        "schema": _REQUEST_SCHEMA,
    }}}},
)
async def conversation_turn(
    request: Request, response: Response,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ConversationResponse:
    payload, audio = await _read_turn(request, settings)
    result = await service.respond(
        audio,
        history=tuple(Message(message.role, message.content) for message in payload.history),
        reference_text=payload.reference_text, analyze_pronunciation=payload.analyze_pronunciation,
    )
    response.headers["Cache-Control"] = "no-store"
    return _response(result)


async def _read_turn(request: Request, settings: Settings) -> tuple[ConversationRequest, AudioData]:
    max_body = encoded_audio_limit(settings.parakeet.max_audio_bytes) + 4096 + 6 * (
        settings.glm.max_input_characters + settings.openpronounce.max_text_characters
    )
    payload = await read_json(request, ConversationRequest, max_body)
    audio = decode_audio(payload.audio_base64, payload.media_type, settings.parakeet.max_audio_bytes)
    return payload, audio


def _response(result: ConversationTurn) -> ConversationResponse:
    return ConversationResponse(
        transcript=result.transcript, reply=result.reply, pronunciation=result.pronunciation,
        corrections=result.corrections, pronunciation_feedback=result.pronunciation_feedback,
        audio=ConversationAudio(media_type=result.audio.media_type,
                                content_base64=base64.b64encode(result.audio.content).decode("ascii"))
        if result.audio is not None else None,
        warnings=result.warnings,
    )


@router.post(
    "/conversation/turn/stream", response_class=StreamingResponse,
    summary="Receive a voice reply progressively, followed by pronunciation feedback",
    responses={200: {"content": {"application/x-ndjson": {}}, "description":
        "Newline-delimited reply, audio (base64 PCM16 WAV chunks), feedback and done events. "
        "Each event has type and data fields. Failures after reply use an error event."}},
    openapi_extra={"requestBody": {"required": True, "content": {"application/json": {
        "schema": _REQUEST_SCHEMA,
    }}}},
)
async def stream_conversation_turn(
    request: Request,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> StreamingResponse:
    payload, audio = await _read_turn(request, settings)
    events = service.stream(
        audio, history=tuple(Message(message.role, message.content) for message in payload.history),
        reference_text=payload.reference_text, analyze_pronunciation=payload.analyze_pronunciation,
    )
    # Preserve regular safe HTTP errors for transcription and GLM failures.
    try:
        first = await anext(events)
    except BaseException:
        await events.aclose()
        raise

    def encode(event):
        kind, result = event
        data = {"media_type": result.media_type,
                "content_base64": base64.b64encode(result.content).decode("ascii")} \
            if isinstance(result, AudioData) else _response(result).model_dump(mode="json")
        return json.dumps({"type": kind, "data": data}, ensure_ascii=False) + "\n"

    async def body():
        async with aclosing(events):
            try:
                yield encode(first)
                async for event in events:
                    yield encode(event)
            except Exception as exc:
                logger.warning("Conversation stream failed (%s)", type(exc).__name__)
                message = exc.message if isinstance(exc, ApplicationError) else "The voice reply was interrupted."
                yield json.dumps({"type": "error", "data": {"message": message}}) + "\n"

    return StreamingResponse(body(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
