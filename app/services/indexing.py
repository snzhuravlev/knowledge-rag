import asyncio
import logging
from pathlib import Path
from typing import Optional

from app.db.repositories import ChunkRepository, SourceRepository
from app.services.extractors import (
    extract_text_from_docx,
    extract_text_from_epub,
    extract_text_from_fb2,
    extract_text_from_pdf,
    extract_text_from_txt,
    split_into_chunks,
)
from app.services.rag import RagService

logger = logging.getLogger("knowledge-rag")


class IndexingService:
    def __init__(
        self,
        source_repo: SourceRepository,
        chunk_repo: ChunkRepository,
        rag_service: RagService,
    ) -> None:
        self.source_repo = source_repo
        self.chunk_repo = chunk_repo
        self.rag_service = rag_service
        self.queue: asyncio.Queue[int] = asyncio.Queue()
        self.worker_task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    async def start_worker(self) -> None:
        if self.worker_task is None:
            self.worker_task = asyncio.create_task(self._worker_loop(), name="indexing-worker")

    async def stop_worker(self) -> None:
        self._stop.set()
        if self.worker_task is not None:
            await self.queue.put(-1)
            await self.worker_task
            self.worker_task = None

    async def enqueue(self, source_id: int) -> None:
        await self.queue.put(source_id)

    async def _worker_loop(self) -> None:
        logger.info("Indexing worker started")
        while not self._stop.is_set():
            source_id = await self.queue.get()
            if source_id == -1:
                break
            try:
                await self.index_source(source_id)
            except Exception:
                logger.exception("Indexing worker failed on source_id=%d", source_id)
            finally:
                self.queue.task_done()
        logger.info("Indexing worker stopped")

    async def index_source(self, source_id: int) -> None:
        src = await self.source_repo.get_for_indexing(source_id)
        if src is None:
            logger.warning("Source not found for indexing: source_id=%d", source_id)
            return
        await self.source_repo.set_status(source_id, "indexing")
        logger.info("Indexing started: source_id=%d title=%s", source_id, src["title"])

        path = Path(src["file_path"])
        if not path.exists():
            await self.source_repo.set_status(source_id, "failed", "File not found on disk")
            return

        try:
            ext = path.suffix.lower()
            if ext == ".pdf":
                full_text = extract_text_from_pdf(path)
            elif ext == ".docx":
                full_text = extract_text_from_docx(path)
            elif ext == ".epub":
                full_text = extract_text_from_epub(path)
            elif ext == ".fb2":
                full_text = extract_text_from_fb2(path)
            else:
                full_text = extract_text_from_txt(path)

            chunks = split_into_chunks(full_text)
            metadata_base = {
                "source_id": source_id,
                "title": src["title"],
                "original_name": src["original_name"],
                "format": src["format"],
            }
            inserted = await self.chunk_repo.insert_chunks(
                chunks=chunks,
                file_path=src["file_path"],
                source_id=source_id,
                metadata_base=metadata_base,
                embed_func=self.rag_service.embed_query,
            )
            await self.source_repo.set_status(source_id, "ready")
            logger.info("Indexing completed: source_id=%d chunks=%d", source_id, inserted)
        except Exception as exc:
            await self.source_repo.set_status(source_id, "failed", str(exc))
            logger.exception("Indexing failed: source_id=%d", source_id)
