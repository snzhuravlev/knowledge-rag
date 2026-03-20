from dataclasses import dataclass

from google import genai
from openai import OpenAI

from app.config import Settings
from app.core.rate_limit import RateLimiter
from app.db.repositories import ChunkRepository, SourceRepository, UserRepository
from app.services.indexing import IndexingService
from app.services.rag import RagService


@dataclass
class AppState:
    settings: Settings
    user_repo: UserRepository
    source_repo: SourceRepository
    chunk_repo: ChunkRepository
    rag_service: RagService
    indexing_service: IndexingService
    rate_limiter: RateLimiter
    genai_client: genai.Client
    openai_client: OpenAI | None
