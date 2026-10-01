"""Direct CPU pronunciation practice, independent of conversation providers."""
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import get_pronunciation_service, get_settings
from app.audio.contracts import PronunciationAssessment
from app.api.requests import read_json, decode_audio, encoded_audio_limit
from app.core.config import Settings
from app.services.pronunciation import PronunciationService

router = APIRouter()


class PracticeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audio_base64: str = Field(min_length=1)
    media_type: str = "audio/wav"
    reference_text: str = Field(min_length=1)


@router.post("/pronunciation/analyze", response_model=PronunciationAssessment,
             openapi_extra={"requestBody": {"required": True, "content": {
                 "application/json": {"schema": PracticeRequest.model_json_schema()}}}})
async def analyze_pronunciation(
    request: Request, response: Response,
    service: Annotated[PronunciationService, Depends(get_pronunciation_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PronunciationAssessment:
    limit = settings.openpronounce.max_audio_bytes
    max_body = encoded_audio_limit(limit) + 4096 + 6 * settings.openpronounce.max_text_characters
    payload = await read_json(request, PracticeRequest, max_body)
    audio = decode_audio(payload.audio_base64, payload.media_type, limit)
    result = await service.analyze(audio, payload.reference_text)
    response.headers["Cache-Control"] = "no-store"
    return result
