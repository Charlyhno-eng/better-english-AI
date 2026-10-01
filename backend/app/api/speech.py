from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from app.api.dependencies import get_synthesis_service
from app.services.synthesis import SynthesisService

router = APIRouter()


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1)


@router.post(
    "/audio/speech", response_class=Response,
    responses={200: {"content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}}}},
)
async def synthesize_speech(
    request: SpeechRequest, service: Annotated[SynthesisService, Depends(get_synthesis_service)],
) -> Response:
    audio = await service.synthesize(request.text)
    return Response(
        content=audio.content, media_type=audio.media_type,
        headers={"Content-Disposition": 'inline; filename="speech.wav"', "Cache-Control": "no-store"},
    )
