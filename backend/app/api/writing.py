from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import get_english_service, get_settings
from app.api.schemas import ErrorResponse
from app.api.requests import read_json
from app.core.config import Settings
from app.services.english import Corrections, EnglishService

router = APIRouter()


class WritingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)


@router.post('/writing/corrections', response_model=Corrections,
             responses={code: {"model": ErrorResponse} for code in (400, 413, 415, 422, 503)},
             openapi_extra={"requestBody": {"required": True, "content": {
                 "application/json": {"schema": WritingRequest.model_json_schema()}}}})
async def correct_writing(
    request: Request, response: Response,
    service: Annotated[EnglishService, Depends(get_english_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Corrections:
    payload = await read_json(request, WritingRequest, 4096 + 6 * settings.glm.max_input_characters)
    result = await service.correct_writing(payload.text)
    response.headers['Cache-Control'] = 'no-store'
    return result
