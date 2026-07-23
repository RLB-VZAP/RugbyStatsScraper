from fastapi import APIRouter

from app.api.players import router as players_router

router = APIRouter()
router.include_router(players_router)
