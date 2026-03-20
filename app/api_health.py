from fastapi import APIRouter, Depends

from app.dependencies import get_state
from app.db.pool import get_pool
from app.state import AppState

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def health_live() -> dict:
    return {"status": "ok"}


@router.get("/ready")
async def health_ready(state: AppState = Depends(get_state)) -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("SELECT 1")
    return {
        "status": "ready",
        "indexing_queue_size": state.indexing_service.queue.qsize(),
    }
