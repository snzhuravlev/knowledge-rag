# Local RAG UI (FastAPI + PostgreSQL + Gemini)

Minimalist web interface for a local RAG system:

- Backend: FastAPI + asyncpg + PostgreSQL with pgvector.
- Chunk storage in the `knowledge_base` table.
- Embeddings: `google/text-embedding-004`.
- Answer generation: `google/gemini-flash-latest`.
- Web UI: Tailwind, chat + sources list, streaming answers.
- User roles: `admin`, `reader`.

## Project structure

- `app/main.py` — FastAPI application, authentication, chat, CRUD for sources, indexing.
- `app/config.py` — centralized application settings (env loading, defaults, logging config).
- `static/index.html` — frontend (chat, sources display, basic token handling).
- `requirements.txt` — dependencies.
- `.env.example` — example environment configuration.
- `DEPLOY.md` — detailed deployment guide for `knowledge.home.arpa`.

## Environment setup

1. Create a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

2. Create `.env`:

```bash
cp .env.example .env
nano .env
```

Key environment variables:

- `GOOGLE_API_KEY` — Gemini API key.
- `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `DB_HOST` — PostgreSQL connection settings.
- `AUTH_SECRET_KEY` — secret key for signing JWT.
- `RAG_TABLE_NAME` and other `RAG_*` — table/column names and vector search parameters.

## Configuration reference

Core settings are loaded from environment variables in `app/config.py`.

- `GOOGLE_API_KEY` / `GEMINI_API_KEY` — API key for Gemini.
- `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `DB_HOST` — database connection settings.
- `RAG_TABLE_NAME` (default `knowledge_base`) — table with chunks/embeddings.
- `RAG_CONTENT_COLUMN`, `RAG_SOURCE_COLUMN`, `RAG_EMBEDDING_COLUMN`, `RAG_METADATA_COLUMN` — column mapping for RAG reads/writes.
- `RAG_VECTOR_DIM` (default `768`) and `RAG_SIMILARITY_METRIC` (`cosine` or `inner_product`) — retrieval behavior.
- `EMBEDDING_MODEL`, `GENERATION_MODEL` — model IDs for embeddings and generation.
- `AUTH_SECRET_KEY`, `AUTH_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES` — JWT settings.
- `UPLOAD_DIR` — where uploaded files are stored before indexing.
- `LOG_LEVEL`, `LOG_FORMAT` — application logging verbosity/format.

3. Configure the database (pgvector extension, `users`, `sources`, `knowledge_base` tables). SQL examples are in `DEPLOY.md`.

## Running in dev mode

```bash
source .venv/bin/activate
uvicorn app.main:app --reload
```

The interface will be available at:

- `http://127.0.0.1:8000/`

## Roles and authentication

- `admin`:
  - can upload new sources (books/documents),
  - manage them (edit title, delete),
  - use the chat.
- `reader`:
  - can only use the chat and view the list of sources.

Tokens:

- Login endpoint: `POST /auth/login` (OAuth2 Password Flow).
- Profile endpoint: `GET /auth/me`.

## Source indexing

- A file (or archive) is uploaded via `POST /api/sources` (for admin).
- Supported formats: `pdf`, `docx`, `epub`, `fb2`, `txt` (by file extension).
- Text is extracted, normalized, and split into chunks.
- For each chunk, an embedding is computed and a record is created in `knowledge_base` (with JSON metadata linking back to the source).
- Source status:
  - `pending` → created, waiting for indexing;
  - `indexing` → processing in progress;
  - `ready` → fully indexed;
  - `failed` → error occurred, error message is stored in `error_message`.

Indexing is started in the background (`BackgroundTasks`) after upload.

## Chat usage

- Chat endpoints:
  - `POST /api/chat` — classic request/response.
  - `POST /api/chat-stream` — streaming responses (Server-Sent Events).
- Chat requires authorization (role `reader` or `admin`).
- UI:
  - input field for the query,
  - streaming assistant response,
  - sources panel with pagination.

## Deployment

A detailed guide (Ubuntu 24.04, `knowledge.home.arpa` domain, Nginx, self-signed SSL, systemd service) is in `DEPLOY.md`.

