import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import AsyncGenerator, List, Optional

import asyncpg
from ebooklib import epub
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    HTTPException,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from google import genai
from jose import JWTError, jwt
from lxml import etree
from passlib.context import CryptContext
from pydantic import BaseModel
from pypdf import PdfReader
from docx import Document
from app.config import configure_logging, load_settings


settings = load_settings()
configure_logging(settings)
logger = logging.getLogger("knowledge-rag")


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


class ChatRequest(BaseModel):
    query: str


class ChatStreamRequest(BaseModel):
    query: str


class SourceChunk(BaseModel):
    id: int
    content: str
    source: Optional[str] = None
    score: float


class ChatResponse(BaseModel):
    answer: str
    sources: List[SourceChunk]


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class User(BaseModel):
    id: int
    username: str
    role: str


class SourceBase(BaseModel):
    title: str


class SourceOut(SourceBase):
    id: int
    original_name: str
    format: str
    status: str


class SourceUpdate(BaseModel):
    title: Optional[str] = None


app = FastAPI(title="Local RAG UI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


client = genai.Client(api_key=settings.google_api_key)
db_pool: Optional[asyncpg.Pool] = None


@app.on_event("startup")
async def startup() -> None:
    global db_pool
    logger.info("Starting application and creating database pool")
    db_pool = await asyncpg.create_pool(
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_name,
        host=settings.db_host,
    )
    logger.info("Database pool created successfully")


@app.on_event("shutdown")
async def shutdown() -> None:
    global db_pool
    if db_pool is not None:
        logger.info("Shutting down application and closing database pool")
        await db_pool.close()
        db_pool = None
        logger.info("Database pool closed")


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.auth_secret_key, algorithm=settings.auth_algorithm)


async def get_db_connection() -> asyncpg.Connection:
    if db_pool is None:
        raise RuntimeError("Database pool is not initialized.")
    return await db_pool.acquire()


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.auth_secret_key, algorithms=[settings.auth_algorithm])
        user_id: str = payload.get("sub")
        role: str = payload.get("role")
        if user_id is None or role is None:
            raise credentials_exception
    except JWTError:
        logger.warning("JWT validation failed")
        raise credentials_exception

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, username, role FROM users WHERE id = $1",
            int(user_id),
        )
    if row is None:
        logger.warning("User from token not found in database: id=%s", user_id)
        raise credentials_exception
    return User(id=row["id"], username=row["username"], role=row["role"])


async def require_reader(user: User = Depends(get_current_user)) -> User:
    if user.role not in ("reader", "admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


async def embed_query(text: str) -> List[float]:
    response = client.models.embed_content(
        model=settings.embedding_model,
        contents=text,
    )
    embedding = getattr(response, "embeddings", None)
    if not embedding:
        raise RuntimeError("Embedding model did not return embeddings.")
    vector = embedding[0].values if hasattr(embedding[0], "values") else embedding[0]
    return list(vector)


def _normalize_text(text: str) -> str:
    return " ".join(text.replace("\r", " ").split())


def extract_text_from_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    parts: List[str] = []
    for page in reader.pages:
        page_text = page.extract_text() or ""
        if page_text.strip():
            parts.append(page_text)
    return _normalize_text("\n\n".join(parts))


def extract_text_from_docx(path: Path) -> str:
    doc = Document(str(path))
    parts: List[str] = [p.text for p in doc.paragraphs if p.text.strip()]
    return _normalize_text("\n\n".join(parts))


def extract_text_from_epub(path: Path) -> str:
    book = epub.read_epub(str(path))
    parts: List[str] = []
    for item in book.get_items():
        if item.get_type() == epub.ITEM_DOCUMENT:
            html = item.get_body_content().decode("utf-8", errors="ignore")
            root = etree.HTML(html)
            if root is not None:
                text = " ".join(root.itertext())
                if text.strip():
                    parts.append(text)
    return _normalize_text("\n\n".join(parts))


def extract_text_from_fb2(path: Path) -> str:
    parser = etree.XMLParser(recover=True)
    tree = etree.parse(str(path), parser=parser)
    root = tree.getroot()
    texts: List[str] = []
    for body in root.findall(".//{*}body"):
        for p in body.iterfind(".//{*}p"):
            if p.text:
                texts.append(p.text)
    return _normalize_text("\n\n".join(texts))


def extract_text_from_txt(path: Path) -> str:
    data = path.read_text(encoding="utf-8", errors="ignore")
    return _normalize_text(data)


def split_into_chunks(text: str, max_chars: int = 2000, overlap: int = 200) -> List[str]:
    chunks: List[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + max_chars, length)
        chunk = text[start:end]
        chunks.append(chunk.strip())
        if end == length:
            break
        start = max(0, end - overlap)
    return [c for c in chunks if c]


async def fetch_top_k_chunks(query_embedding: List[float], k: int = 5) -> List[SourceChunk]:
    if db_pool is None:
        raise RuntimeError("Database pool is not initialized.")

    async with db_pool.acquire() as conn:
        if settings.similarity_metric == "inner_product":
            score_expression = f"{settings.embedding_column} <#> $1::vector"
            order_expression = f"{settings.embedding_column} <#> $1::vector"
        else:
            score_expression = f"1 - ({settings.embedding_column} <-> $1::vector)"
            order_expression = f"{settings.embedding_column} <-> $1::vector"

        query = f"""
            SELECT id, {settings.content_column} AS content, {settings.source_column} AS source, {score_expression} AS score
            FROM {settings.table_name}
            ORDER BY {order_expression}
            LIMIT $2
        """

        rows = await conn.fetch(
            query,
            query_embedding,
            k,
        )
        logger.debug("Fetched %d chunks from %s", len(rows), settings.table_name)

    chunks: List[SourceChunk] = []
    for row in rows:
        chunks.append(
            SourceChunk(
                id=row["id"],
                content=row["content"],
                source=row.get("source"),
                score=float(row["score"]),
            )
        )
    return chunks


def build_rag_prompt(query: str, chunks: List[SourceChunk]) -> str:
    context_blocks = []
    for idx, chunk in enumerate(chunks, start=1):
        label = f"Source {idx}"
        if chunk.source:
            label += f" ({chunk.source})"
        context_blocks.append(f"{label}:\n{chunk.content}")

    context_text = "\n\n".join(context_blocks) if context_blocks else "No additional context."

    prompt = (
        "You are an assistant that answers questions using the provided context.\n"
        "Use only the information from the context where possible, and clearly say when something is not covered.\n\n"
        f"User question:\n{query}\n\n"
        "Context:\n"
        f"{context_text}\n\n"
        "Answer in a clear and structured way."
    )
    return prompt


async def generate_answer(prompt: str) -> str:
    response = client.models.generate_content(
        model=settings.generation_model,
        contents=prompt,
    )
    text_parts: List[str] = []
    for part in getattr(response, "candidates", []) or []:
        content = getattr(part, "content", None)
        if not content:
            continue
        for sub in getattr(content, "parts", []):
            value = getattr(sub, "text", None) or getattr(sub, "inline_data", None)
            if isinstance(value, str):
                text_parts.append(value)
    if not text_parts and hasattr(response, "text"):
        return str(response.text)
    return "\n".join(text_parts).strip()


async def generate_answer_stream(prompt: str) -> AsyncGenerator[str, None]:
    stream = client.models.generate_content_stream(
        model=settings.generation_model,
        contents=prompt,
    )
    async for event in stream:
        for part in getattr(event, "candidates", []) or []:
            content = getattr(part, "content", None)
            if not content:
                continue
            for sub in getattr(content, "parts", []):
                value = getattr(sub, "text", None)
                if isinstance(value, str) and value:
                    yield value


async def index_source(source_id: int) -> None:
    if db_pool is None:
        raise RuntimeError("Database pool is not initialized.")

    async with db_pool.acquire() as conn:
        src = await conn.fetchrow(
            "SELECT id, title, file_path, original_name, format, is_archive FROM sources WHERE id = $1",
            source_id,
        )
        if src is None:
            logger.warning("Source not found for indexing: source_id=%d", source_id)
            return
        logger.info("Indexing started: source_id=%d title=%s", source_id, src["title"])
        await conn.execute(
            "UPDATE sources SET status = 'indexing', updated_at = now(), error_message = NULL WHERE id = $1",
            source_id,
        )

    path = Path(src["file_path"])
    if not path.exists():
        logger.error("Source file not found on disk: source_id=%d path=%s", source_id, path)
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE sources SET status = 'failed', error_message = $2, updated_at = now() WHERE id = $1",
                source_id,
                "File not found on disk",
            )
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
        inserted = 0

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                for idx, chunk in enumerate(chunks):
                    emb = await embed_query(chunk)
                    metadata = {
                        "source_id": source_id,
                        "chunk_index": idx,
                        "title": src["title"],
                        "original_name": src["original_name"],
                        "format": src["format"],
                    }
                    await conn.execute(
                        f"""
                        INSERT INTO {settings.table_name} ({settings.content_column}, {settings.source_column}, {settings.embedding_column}, {settings.metadata_column})
                        VALUES ($1, $2, $3, $4::jsonb)
                        """,
                        chunk,
                        src["file_path"],
                        emb,
                        json.dumps(metadata),
                    )
                    inserted += 1

        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE sources SET status = 'ready', updated_at = now() WHERE id = $1",
                source_id,
            )
        logger.info("Indexing completed: source_id=%d chunks=%d", source_id, inserted)
    except Exception as exc:
        logger.exception("Indexing failed: source_id=%d", source_id)
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE sources SET status = 'failed', error_message = $2, updated_at = now() WHERE id = $1",
                source_id,
                str(exc),
            )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, _: User = Depends(require_reader)) -> ChatResponse:
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    try:
        logger.info("Chat request received")
        query_embedding = await embed_query(request.query)
        chunks = await fetch_top_k_chunks(query_embedding, k=5)
        prompt = build_rag_prompt(request.query, chunks)
        answer = await generate_answer(prompt)
    except Exception as exc:
        logger.exception("Chat request failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ChatResponse(answer=answer, sources=chunks)


@app.post("/api/chat-stream")
async def chat_stream(request: ChatStreamRequest, _: User = Depends(require_reader)) -> StreamingResponse:
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    try:
        logger.info("Streaming chat request received")
        query_embedding = await embed_query(request.query)
        chunks = await fetch_top_k_chunks(query_embedding, k=20)
        prompt = build_rag_prompt(request.query, chunks)
    except Exception as exc:
        logger.exception("Streaming chat setup failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    async def event_generator() -> AsyncGenerator[bytes, None]:
        meta = {
            "type": "meta",
            "sources": [chunk.dict() for chunk in chunks],
        }
        yield f"data: {json.dumps(meta, ensure_ascii=False)}\n\n".encode("utf-8")

        async for piece in generate_answer_stream(prompt):
            payload = {"type": "delta", "text": piece}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")

        yield b"data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/auth/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()) -> Token:
    if db_pool is None:
        raise RuntimeError("Database pool is not initialized.")

    async with db_pool.acquire() as conn:
        user_row = await conn.fetchrow(
            "SELECT id, username, password_hash, role FROM users WHERE username = $1",
            form_data.username,
        )

    if user_row is None or not verify_password(form_data.password, user_row["password_hash"]):
        logger.warning("Login failed for username=%s", form_data.username)
        raise HTTPException(status_code=400, detail="Incorrect username or password")

    token = create_access_token(
        {"sub": str(user_row["id"]), "role": user_row["role"]},
    )
    logger.info("Login succeeded for username=%s", form_data.username)
    return Token(access_token=token)


@app.get("/auth/me", response_model=User)
async def me(current: User = Depends(get_current_user)) -> User:
    return current


@app.post("/api/sources", response_model=SourceOut)
async def create_source(
    background_tasks: BackgroundTasks,
    title: str,
    file: UploadFile = File(...),
    _: User = Depends(require_admin),
) -> SourceOut:
    if db_pool is None:
        raise RuntimeError("Database pool is not initialized.")

    safe_name = file.filename or "uploaded"
    dest_path = settings.upload_dir / f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{safe_name}"
    content = await file.read()
    dest_path.write_bytes(content)
    logger.info("Source uploaded: name=%s path=%s bytes=%d", safe_name, dest_path, len(content))

    file_format = dest_path.suffix.lower().lstrip(".") or "txt"

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO sources (title, file_path, original_name, format, is_archive, status)
            VALUES ($1, $2, $3, $4, FALSE, 'pending')
            RETURNING id, title, original_name, format, status
            """,
            title,
            str(dest_path),
            safe_name,
            file_format,
        )
        source_id = row["id"]

    background_tasks.add_task(index_source, source_id)

    return SourceOut(
        id=row["id"],
        title=row["title"],
        original_name=row["original_name"],
        format=row["format"],
        status=row["status"],
    )


@app.get("/api/sources", response_model=List[SourceOut])
async def list_sources(_: User = Depends(require_reader)) -> List[SourceOut]:
    if db_pool is None:
        raise RuntimeError("Database pool is not initialized.")
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, title, original_name, format, status FROM sources ORDER BY created_at DESC"
        )
    return [
        SourceOut(
            id=row["id"],
            title=row["title"],
            original_name=row["original_name"],
            format=row["format"],
            status=row["status"],
        )
        for row in rows
    ]


@app.patch("/api/sources/{source_id}", response_model=SourceOut)
async def update_source(
    source_id: int,
    payload: SourceUpdate,
    _: User = Depends(require_admin),
) -> SourceOut:
    if db_pool is None:
        raise RuntimeError("Database pool is not initialized.")
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, title, original_name, format, status FROM sources WHERE id = $1",
            source_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Source not found")
        new_title = payload.title if payload.title is not None else row["title"]
        await conn.execute(
            "UPDATE sources SET title = $2, updated_at = now() WHERE id = $1",
            source_id,
            new_title,
        )
        row = await conn.fetchrow(
            "SELECT id, title, original_name, format, status FROM sources WHERE id = $1",
            source_id,
        )
    return SourceOut(
        id=row["id"],
        title=row["title"],
        original_name=row["original_name"],
        format=row["format"],
        status=row["status"],
    )


@app.delete("/api/sources/{source_id}")
async def delete_source(
    source_id: int,
    _: User = Depends(require_admin),
) -> dict:
    if db_pool is None:
        raise RuntimeError("Database pool is not initialized.")
    async with db_pool.acquire() as conn:
        src = await conn.fetchrow(
            "SELECT file_path FROM sources WHERE id = $1",
            source_id,
        )
        # Remove related chunks from the shared knowledge_base by matching on metadata.source_id
        await conn.execute(
            f"DELETE FROM {settings.table_name} WHERE {settings.metadata_column} ->> 'source_id' = $1::text",
            str(source_id),
        )
        await conn.execute("DELETE FROM sources WHERE id = $1", source_id)
    if src and src["file_path"]:
        try:
            Path(src["file_path"]).unlink(missing_ok=True)
        except Exception:
            pass
    logger.info("Source deleted: source_id=%d", source_id)
    return {"status": "ok"}


app.mount("/static", StaticFiles(directory="static", html=False), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse("static/index.html")

