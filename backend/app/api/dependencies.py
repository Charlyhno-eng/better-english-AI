from fastapi import Request

from app.core.config import Settings
from app.services.conversation import ConversationService
from app.services.health import HealthService
from app.services.english import EnglishService
from app.services.synthesis import SynthesisService
from app.services.pronunciation import PronunciationService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_health_service() -> HealthService:
    return HealthService()


def get_synthesis_service(request: Request) -> SynthesisService:
    return request.app.state.synthesis_service


def get_pronunciation_service(request: Request) -> PronunciationService:
    return request.app.state.pronunciation_service


def get_english_service(request: Request) -> EnglishService:
    return request.app.state.english_service


def get_conversation_service(request: Request) -> ConversationService:
    return request.app.state.conversation_service
