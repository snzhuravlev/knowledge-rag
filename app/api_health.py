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


@router.get("/vector-config")
async def health_vector_config(state: AppState = Depends(get_state)) -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            SELECT
                format_type(a.atttypid, a.atttypmod) AS embedding_type,
                t.schemaname,
                t.tablename
            FROM pg_catalog.pg_attribute a
            JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_catalog.pg_tables t
              ON t.schemaname = n.nspname
             AND t.tablename = c.relname
            WHERE n.nspname = 'public'
              AND c.relname = $1
              AND a.attname = $2
              AND a.attnum > 0
              AND NOT a.attisdropped
            LIMIT 1
            """,
            state.settings.table_name,
            state.settings.embedding_column,
        )
    if row is None:
        return {
            "status": "error",
            "detail": "Embedding column not found",
            "expected_table": state.settings.table_name,
            "expected_column": state.settings.embedding_column,
            "expected_vector_dim": state.settings.vector_dim,
        }
    embedding_type = row["embedding_type"]
    expected_type = f"vector({state.settings.vector_dim})"
    is_match = embedding_type == expected_type
    return {
        "status": "ok" if is_match else "mismatch",
        "table": f"{row['schemaname']}.{row['tablename']}",
        "column": state.settings.embedding_column,
        "actual_embedding_type": embedding_type,
        "expected_embedding_type": expected_type,
        "vector_dim_match": is_match,
    }
