import json
from typing import List, Optional

import asyncpg

from app.config import Settings
from app.schemas import SourceChunk


class UserRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def find_by_id(self, user_id: int):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT id, username, role FROM users WHERE id = $1",
                user_id,
            )

    async def find_for_login(self, username: str):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT id, username, password_hash, role FROM users WHERE username = $1",
                username,
            )


class SourceRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def create(
        self, title: str, file_path: str, original_name: str, file_format: str
    ):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                """
                INSERT INTO sources (title, file_path, original_name, format, is_archive, status)
                VALUES ($1, $2, $3, $4, FALSE, 'pending')
                RETURNING id, title, original_name, format, status
                """,
                title,
                file_path,
                original_name,
                file_format,
            )

    async def get_for_indexing(self, source_id: int):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT id, title, file_path, original_name, format, is_archive FROM sources WHERE id = $1",
                source_id,
            )

    async def set_status(self, source_id: int, status: str, error_message: Optional[str] = None) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE sources SET status = $2, error_message = $3, updated_at = now() WHERE id = $1",
                source_id,
                status,
                error_message,
            )

    async def list_all(self):
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                "SELECT id, title, original_name, format, status FROM sources ORDER BY created_at DESC"
            )

    async def find_basic(self, source_id: int):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT id, title, original_name, format, status FROM sources WHERE id = $1",
                source_id,
            )

    async def update_title(self, source_id: int, title: str):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE sources SET title = $2, updated_at = now() WHERE id = $1",
                source_id,
                title,
            )
            return await conn.fetchrow(
                "SELECT id, title, original_name, format, status FROM sources WHERE id = $1",
                source_id,
            )

    async def get_file_path(self, source_id: int):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT file_path FROM sources WHERE id = $1",
                source_id,
            )

    async def delete(self, source_id: int) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM sources WHERE id = $1", source_id)


class ChunkRepository:
    def __init__(self, pool: asyncpg.Pool, settings: Settings) -> None:
        self.pool = pool
        self.settings = settings

    async def fetch_top_k(self, query_embedding: List[float], k: int) -> List[SourceChunk]:
        query_vector = self._to_vector_literal(query_embedding)
        async with self.pool.acquire() as conn:
            if self.settings.similarity_metric == "inner_product":
                score_expression = f"{self.settings.embedding_column} <#> $1::vector"
                order_expression = f"{self.settings.embedding_column} <#> $1::vector"
            else:
                score_expression = f"1 - ({self.settings.embedding_column} <-> $1::vector)"
                order_expression = f"{self.settings.embedding_column} <-> $1::vector"

            query = f"""
                SELECT id, {self.settings.content_column} AS content, {self.settings.source_column} AS source, {score_expression} AS score
                FROM {self.settings.table_name}
                ORDER BY {order_expression}
                LIMIT $2
            """
            rows = await conn.fetch(query, query_vector, k)
        return [
            SourceChunk(
                id=row["id"],
                content=row["content"],
                source=row.get("source"),
                score=float(row["score"]),
            )
            for row in rows
        ]

    async def insert_chunks(
        self,
        chunks: List[str],
        file_path: str,
        source_id: int,
        metadata_base: dict,
        embed_func,
    ) -> int:
        inserted = 0
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                for idx, chunk in enumerate(chunks):
                    emb = await embed_func(chunk)
                    emb_vector = self._to_vector_literal(emb)
                    metadata = dict(metadata_base)
                    metadata["chunk_index"] = idx
                    await conn.execute(
                        f"""
                        INSERT INTO {self.settings.table_name} ({self.settings.content_column}, {self.settings.source_column}, {self.settings.embedding_column}, {self.settings.metadata_column})
                        VALUES ($1, $2, $3, $4::jsonb)
                        """,
                        chunk,
                        file_path,
                        emb_vector,
                        json.dumps(metadata),
                    )
                    inserted += 1
        return inserted

    async def delete_by_source_id(self, source_id: int) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                f"DELETE FROM {self.settings.table_name} WHERE {self.settings.metadata_column} ->> 'source_id' = $1::text",
                str(source_id),
            )

    @staticmethod
    def _to_vector_literal(values: List[float]) -> str:
        return "[" + ",".join(f"{float(v):.10f}" for v in values) + "]"
