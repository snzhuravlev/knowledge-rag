from typing import Optional

import asyncpg

from app.config import Settings

db_pool: Optional[asyncpg.Pool] = None


async def init_pool(settings: Settings) -> None:
    global db_pool
    db_pool = await asyncpg.create_pool(
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_name,
        host=settings.db_host,
    )


async def close_pool() -> None:
    global db_pool
    if db_pool is not None:
        await db_pool.close()
        db_pool = None


def get_pool() -> asyncpg.Pool:
    if db_pool is None:
        raise RuntimeError("Database pool is not initialized.")
    return db_pool
