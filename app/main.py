import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from google import genai

from app.api_auth import router as auth_router
from app.api_chat import router as chat_router
from app.api_health import router as health_router
from app.api_sources import router as sources_router
from app.config import configure_logging, load_settings
from app.core.errors import install_error_handlers
from app.core.middleware import install_request_id_middleware
from app.core.rate_limit import RateLimiter
from app.db.pool import close_pool, get_pool, init_pool
from app.db.repositories import ChunkRepository, SourceRepository, UserRepository
from app.services.indexing import IndexingService
from app.services.rag import RagService
from app.state import AppState

settings = load_settings()
configure_logging(settings)
logger = logging.getLogger("knowledge-rag")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting application and creating database pool")
    await init_pool(settings)
    pool = get_pool()
    client = genai.Client(api_key=settings.google_api_key)
    user_repo = UserRepository(pool)
    source_repo = SourceRepository(pool)
    chunk_repo = ChunkRepository(pool, settings)
    rag_service = RagService(settings=settings, chunk_repo=chunk_repo, client=client)
    indexing_service = IndexingService(source_repo=source_repo, chunk_repo=chunk_repo, rag_service=rag_service)
    if settings.enable_indexing_worker:
        await indexing_service.start_worker()
    app.state.container = AppState(
        settings=settings,
        user_repo=user_repo,
        source_repo=source_repo,
        chunk_repo=chunk_repo,
        rag_service=rag_service,
        indexing_service=indexing_service,
        rate_limiter=RateLimiter(),
        genai_client=client,
    )
    yield
    logger.info("Shutting down application")
    await indexing_service.stop_worker()
    await close_pool()


app = FastAPI(title="Local RAG UI", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
install_request_id_middleware(app)
install_error_handlers(app)

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(sources_router)
app.include_router(health_router)


app.mount("/static", StaticFiles(directory="static", html=False), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse("static/index.html")

