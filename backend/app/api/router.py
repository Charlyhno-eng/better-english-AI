from fastapi import APIRouter

from app.api.health import router as health_router
from app.api.speech import router as speech_router
from app.api.conversation import router as conversation_router
from app.api.pronunciation import router as pronunciation_router
from app.api.writing import router as writing_router

from app.api.setup import router as setup_router

router = APIRouter(prefix="/api")
router.include_router(setup_router, tags=["setup"])
router.include_router(health_router, tags=["health"])
router.include_router(speech_router, tags=["audio"])
router.include_router(conversation_router, tags=["conversation"])
router.include_router(pronunciation_router, tags=["pronunciation"])
router.include_router(writing_router, tags=["writing"])
