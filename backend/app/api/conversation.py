import base64
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.ai.contracts import Message
from app.api.dependencies import get_conversation_service, get_settings
from app.audio.contracts import PronunciationAssessment
from app.api.requests import read_json, decode_audio, encoded_audio_limit
from app.api.schemas import ErrorResponse
from app.core.config import Settings
from app.services.conversation import ConversationService, ConversationWarning
from app.services.english import Corrections

router = APIRouter()


class HistoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


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
    max_body = encoded_audio_limit(settings.parakeet.max_audio_bytes) + 4096 + 6 * (
        settings.glm.max_input_characters + settings.openpronounce.max_text_characters
    )
    payload = await read_json(request, ConversationRequest, max_body)
    audio = decode_audio(payload.audio_base64, payload.media_type, settings.parakeet.max_audio_bytes)
    result = await service.respond(
        audio,
        history=tuple(Message(message.role, message.content) for message in payload.history),
        reference_text=payload.reference_text, analyze_pronunciation=payload.analyze_pronunciation,
    )
    response.headers["Cache-Control"] = "no-store"
    return ConversationResponse(
        transcript=result.transcript, reply=result.reply, pronunciation=result.pronunciation,
        corrections=result.corrections, pronunciation_feedback=result.pronunciation_feedback,
        audio=ConversationAudio(media_type=result.audio.media_type,
                                content_base64=base64.b64encode(result.audio.content).decode("ascii"))
        if result.audio is not None else None,
        warnings=result.warnings,
    )
