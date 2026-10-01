from urllib.parse import urlsplit
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, SecretStr, field_validator

from app.api.requests import read_json
from app.services.setup import SetupService

router = APIRouter(prefix="/setup")


def setup_service(request: Request) -> SetupService:
    return request.app.state.setup_service


def same_origin(request: Request) -> None:
    # Only the app's own browser origin may trigger local writes/downloads.
    origin = request.headers.get("origin", "")
    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"} or parsed.netloc != request.headers.get("host"):
        raise HTTPException(403)


class KeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: SecretStr

    @field_validator("api_key")
    @classmethod
    def valid_key(cls, value: SecretStr) -> SecretStr:
        key = value.get_secret_value().strip()
        if not key or len(key) > 4096 or any(ord(character) < 32 for character in key):
            raise ValueError("Invalid API key")
        return SecretStr(key)


@router.get("")
def status(response: Response, service: SetupService = Depends(setup_service)):
    response.headers["Cache-Control"] = "no-store"
    return service.status()


@router.post("/glm", dependencies=[Depends(same_origin)])
async def save_key(request: Request, response: Response, service: SetupService = Depends(setup_service)):
    payload = await read_json(request, KeyRequest, 32768)
    service.save_key(payload.api_key)
    response.headers["Cache-Control"] = "no-store"
    return {"glm_configured": True}


@router.post("/models/{model}", status_code=202, dependencies=[Depends(same_origin)])
async def install_model(model: Literal["parakeet", "pocket-tts", "openpronounce"], response: Response,
                  service: SetupService = Depends(setup_service)):
    if not service.start_install(model):
        raise HTTPException(409)
    response.headers["Cache-Control"] = "no-store"
    return {"state": "installing"}
