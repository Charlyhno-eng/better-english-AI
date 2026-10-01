"""Shared bounded JSON and audio decoding at the HTTP boundary."""
import base64
import binascii
from typing import TypeVar

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError
from starlette.exceptions import HTTPException

from app.audio.contracts import AudioData
from app.core.errors import InvalidAudioError

RequestModel = TypeVar('RequestModel', bound=BaseModel)


def encoded_audio_limit(max_bytes: int) -> int:
    return 4 * ((max_bytes + 2) // 3)


async def read_json(request: Request, model: type[RequestModel], max_bytes: int) -> RequestModel:
    if request.headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'application/json':
        raise HTTPException(415)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > max_bytes:
            raise HTTPException(413)
        body.extend(chunk)
    try:
        return model.model_validate_json(body)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from None


def decode_audio(encoded: str, media_type: str, max_bytes: int) -> AudioData:
    if len(encoded) > encoded_audio_limit(max_bytes):
        raise InvalidAudioError('The recording exceeds the size limit.')
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise InvalidAudioError('The recording must contain valid base64 audio.') from None
    if len(content) > max_bytes:
        raise InvalidAudioError('The recording exceeds the size limit.')
    return AudioData(content, media_type)
