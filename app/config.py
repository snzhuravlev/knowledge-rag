import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

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
    embedding_provider: str
    generation_model: str
    generation_provider: str
    openai_api_key: str | None
    openai_base_url: str | None
    auth_secret_key: str
    auth_algorithm: str
    access_token_expire_minutes: int
    upload_dir: Path
    log_level: str
    log_format: str
    cors_origins: Tuple[str, ...]
    upload_max_bytes: int
    login_rate_limit_per_minute: int
    chat_rate_limit_per_minute: int
    enable_indexing_worker: bool


def load_settings() -> Settings:
    embedding_provider = os.getenv("EMBEDDING_PROVIDER", "google").lower()
    if embedding_provider not in {"google", "openai"}:
        raise RuntimeError("EMBEDDING_PROVIDER must be either 'google' or 'openai'.")
    generation_provider = os.getenv("GENERATION_PROVIDER", "google").lower()
    if generation_provider not in {"google", "openai"}:
        raise RuntimeError("GENERATION_PROVIDER must be either 'google' or 'openai'.")
    openai_api_key = os.getenv("OPENAI_API_KEY")
    openai_base_url = os.getenv("OPENAI_BASE_URL")
    if (embedding_provider == "openai" or generation_provider == "openai") and not openai_api_key:
        raise RuntimeError(
            "OPENAI_API_KEY must be set when EMBEDDING_PROVIDER=openai or GENERATION_PROVIDER=openai."
        )

    google_api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not google_api_key:
        raise RuntimeError("GOOGLE_API_KEY (or GEMINI_API_KEY) is not set in environment variables.")
    db_password = os.getenv("DB_PASSWORD")
    if not db_password:
        raise RuntimeError("DB_PASSWORD must be set in environment variables.")
    auth_secret_key = os.getenv("AUTH_SECRET_KEY")
    if not auth_secret_key or len(auth_secret_key) < 32:
        raise RuntimeError("AUTH_SECRET_KEY must be set and at least 32 characters long.")

    identifier_pattern = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

    def validated_identifier(env_name: str, default_value: str) -> str:
        value = os.getenv(env_name, default_value)
        if not identifier_pattern.match(value):
            raise RuntimeError(f"{env_name} contains invalid SQL identifier.")
        return value

    cors_env = os.getenv("CORS_ALLOW_ORIGINS", "http://127.0.0.1:8008,http://localhost:8008")
    cors_origins = tuple(origin.strip() for origin in cors_env.split(",") if origin.strip())
    if not cors_origins:
        raise RuntimeError("CORS_ALLOW_ORIGINS must contain at least one origin.")

    upload_dir = Path(os.getenv("UPLOAD_DIR", "data/uploads")).resolve()
    upload_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        google_api_key=google_api_key,
        db_user=os.getenv("DB_USER", "claw"),
        db_password=db_password,
        db_name=os.getenv("DB_NAME", "claw"),
        db_host=os.getenv("DB_HOST", "/var/run/postgresql"),
        table_name=validated_identifier("RAG_TABLE_NAME", "knowledge_base"),
        content_column=validated_identifier("RAG_CONTENT_COLUMN", "content"),
        source_column=validated_identifier("RAG_SOURCE_COLUMN", "file_path"),
        embedding_column=validated_identifier("RAG_EMBEDDING_COLUMN", "embedding"),
        metadata_column=validated_identifier("RAG_METADATA_COLUMN", "metadata"),
        vector_dim=int(os.getenv("RAG_VECTOR_DIM", "768")),
        similarity_metric=os.getenv("RAG_SIMILARITY_METRIC", "cosine"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
        embedding_provider=embedding_provider,
        generation_model=os.getenv("GENERATION_MODEL", "gemini-2.0-flash"),
        generation_provider=generation_provider,
        openai_api_key=openai_api_key,
        openai_base_url=openai_base_url,
        auth_secret_key=auth_secret_key,
        auth_algorithm=os.getenv("AUTH_ALGORITHM", "HS256"),
        access_token_expire_minutes=int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60")),
        upload_dir=upload_dir,
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        log_format=os.getenv(
            "LOG_FORMAT",
            "%(asctime)s %(levelname)s %(name)s - %(message)s",
        ),
        cors_origins=cors_origins,
        upload_max_bytes=int(os.getenv("UPLOAD_MAX_BYTES", str(20 * 1024 * 1024))),
        login_rate_limit_per_minute=int(os.getenv("LOGIN_RATE_LIMIT_PER_MINUTE", "10")),
        chat_rate_limit_per_minute=int(os.getenv("CHAT_RATE_LIMIT_PER_MINUTE", "60")),
        enable_indexing_worker=os.getenv("ENABLE_INDEXING_WORKER", "true").lower() == "true",
    )


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format=settings.log_format,
    )
