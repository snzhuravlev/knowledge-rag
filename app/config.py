import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    google_api_key: str
    db_user: str
    db_password: str
    db_name: str
    db_host: str
    table_name: str
    content_column: str
    source_column: str
    embedding_column: str
    metadata_column: str
    vector_dim: int
    similarity_metric: str
    embedding_model: str
    generation_model: str
    auth_secret_key: str
    auth_algorithm: str
    access_token_expire_minutes: int
    upload_dir: Path
    log_level: str
    log_format: str


def load_settings() -> Settings:
    google_api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not google_api_key:
        raise RuntimeError("GOOGLE_API_KEY (or GEMINI_API_KEY) is not set in environment variables.")

    upload_dir = Path(os.getenv("UPLOAD_DIR", "data/uploads")).resolve()
    upload_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        google_api_key=google_api_key,
        db_user=os.getenv("DB_USER", "claw"),
        db_password=os.getenv("DB_PASSWORD", "Drgh74364"),
        db_name=os.getenv("DB_NAME", "claw"),
        db_host=os.getenv("DB_HOST", "/var/run/postgresql"),
        table_name=os.getenv("RAG_TABLE_NAME", "knowledge_base"),
        content_column=os.getenv("RAG_CONTENT_COLUMN", "content"),
        source_column=os.getenv("RAG_SOURCE_COLUMN", "file_path"),
        embedding_column=os.getenv("RAG_EMBEDDING_COLUMN", "embedding"),
        metadata_column=os.getenv("RAG_METADATA_COLUMN", "metadata"),
        vector_dim=int(os.getenv("RAG_VECTOR_DIM", "768")),
        similarity_metric=os.getenv("RAG_SIMILARITY_METRIC", "cosine"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "google/text-embedding-004"),
        generation_model=os.getenv("GENERATION_MODEL", "google/gemini-flash-latest"),
        auth_secret_key=os.getenv("AUTH_SECRET_KEY", "change-me-in-production"),
        auth_algorithm=os.getenv("AUTH_ALGORITHM", "HS256"),
        access_token_expire_minutes=int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60")),
        upload_dir=upload_dir,
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        log_format=os.getenv(
            "LOG_FORMAT",
            "%(asctime)s %(levelname)s %(name)s - %(message)s",
        ),
    )


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format=settings.log_format,
    )
