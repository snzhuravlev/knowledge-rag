## Deploying the RAG service on Ubuntu 24.04 with the `knowledge.home.arpa` domain

### 1. Server preparation

1. Install dependencies:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip nginx
```

2. Clone the project:

```bash
cd /opt
sudo git clone <URL_OF_YOUR_REPOSITORY> knowledge-rag
sudo chown -R $USER:$USER knowledge-rag
cd knowledge-rag
```

3. Create and fill in `.env`:

```bash
cp .env.example .env
nano .env
```

- Set a real `GOOGLE_API_KEY`.
- Configure PostgreSQL parameters.
- Set `AUTH_SECRET_KEY` (a random long string).
- Set `DB_PASSWORD` (required).
- Set `CORS_ALLOW_ORIGINS` to trusted origins only (comma-separated).
- Optional: set `RAG_TABLE_NAME=knowledge_base` explicitly.
- Optional (for debugging): set `LOG_LEVEL=DEBUG`.
- Optional hardening: set `UPLOAD_MAX_BYTES`, `LOGIN_RATE_LIMIT_PER_MINUTE`, `CHAT_RATE_LIMIT_PER_MINUTE`.

4. Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate
```

### 2. PostgreSQL and DB schema setup

Use Alembic migrations as the primary schema management flow:

```bash
source .venv/bin/activate
alembic upgrade head
```

Manual SQL is kept below as a fallback/bootstrap reference.

1. Enable pgvector and create the extension (if not already done):

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

2. Create the users table:

```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin', 'reader')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

3. Create the sources table:

```sql
CREATE TABLE sources (
    id            SERIAL PRIMARY KEY,
    title         TEXT NOT NULL,
    file_path     TEXT NOT NULL,
    original_name TEXT NOT NULL,
    format        TEXT NOT NULL,
    is_archive    BOOLEAN NOT NULL DEFAULT FALSE,
    status        TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

4. Table with chunks (`knowledge_base`) using pgvector:

```sql
CREATE TABLE knowledge_base (
    id        SERIAL PRIMARY KEY,
    file_path TEXT,
    content   TEXT,
    embedding VECTOR(768),
    metadata  JSONB
);

CREATE INDEX knowledge_base_embedding_idx
    ON knowledge_base
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
```

5. Create the first admin user (the password must be hashed via Python/Passlib or a temporary utility):

```python
from passlib.context import CryptContext
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
print(pwd_context.hash("your_admin_password"))
```

If you see an error with `bcrypt`/`passlib` compatibility, reinstall a known compatible bcrypt version:

```bash
source .venv/bin/activate
pip install "bcrypt==4.0.1"
```

```sql
INSERT INTO users (username, password_hash, role)
VALUES ('admin', '<PASSWORD_HASH>', 'admin');
```

### 3. Systemd service for Uvicorn

Create `/etc/systemd/system/knowledge-rag.service`:

```ini
[Unit]
Description=Knowledge RAG FastAPI service
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/opt/knowledge-rag
Environment="PYTHONUNBUFFERED=1"
EnvironmentFile=/opt/knowledge-rag/.env
ExecStart=/opt/knowledge-rag/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable knowledge-rag
sudo systemctl start knowledge-rag
sudo systemctl status knowledge-rag
```

For live log streaming:

```bash
sudo journalctl -u knowledge-rag -f
```

Readiness check:

```bash
curl -k https://knowledge.home.arpa/health/ready
```

### 4. DNS and Nginx for `knowledge.home.arpa`

#### DNS

- On the internal DNS server create a record:
  - Type: `A`
  - Name: `knowledge.home.arpa`
  - Value: internal IP of the Ubuntu server.

#### Nginx (reverse proxy)

Create `/etc/nginx/sites-available/knowledge-rag`:

```nginx
server {
    listen 80;
    server_name knowledge.home.arpa;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name knowledge.home.arpa;

    ssl_certificate     /etc/nginx/self-signed/knowledge.crt;
    ssl_certificate_key /etc/nginx/self-signed/knowledge.key;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}
```

Enable the site:

```bash
sudo ln -s /etc/nginx/sites-available/knowledge-rag /etc/nginx/sites-enabled/knowledge-rag
sudo nginx -t
sudo systemctl reload nginx
```

### 5. TLS strategy

#### Production recommendation

Use a trusted certificate (Let's Encrypt or corporate CA).  
Self-signed certificates should be limited to lab/dev environments.

#### Self-signed SSL for lab/dev `knowledge.home.arpa`

```bash
sudo mkdir -p /etc/nginx/self-signed
cd /etc/nginx/self-signed

sudo openssl req -x509 -nodes -days 365 \
  -newkey rsa:4096 \
  -keyout knowledge.key \
  -out knowledge.crt \
  -subj "/CN=knowledge.home.arpa"

sudo nginx -t
sudo systemctl reload nginx
```

The certificate must be imported into trusted certificates in browsers/client OSes if you want to get rid of warnings.

### 6. Updating the application (with rollback steps)

```bash
cd /opt/knowledge-rag
sudo -u www-data git pull
sudo -u www-data /opt/knowledge-rag/.venv/bin/pip install -r requirements.txt
sudo -u www-data /opt/knowledge-rag/.venv/bin/alembic upgrade head
sudo systemctl restart knowledge-rag
curl -k https://knowledge.home.arpa/health/ready
```

Rollback (example):

```bash
cd /opt/knowledge-rag
sudo -u www-data git checkout <previous_commit>
sudo -u www-data /opt/knowledge-rag/.venv/bin/alembic downgrade -1
sudo systemctl restart knowledge-rag
```

### 7. CI/CD baseline

GitHub Actions workflow is available at `.github/workflows/ci.yml`:

- compile check (`python -m compileall app`)
- dependency audit (`pip-audit`)

Recommended release gates:

- CI must pass before merge/deploy.
- Deploy only after `alembic upgrade head`.
- Run smoke checks on `/health/live` and `/health/ready`.

### 8. Backup and restore

Backup:

```bash
pg_dump -Fc -U <db_user> -d <db_name> > /var/backups/knowledge-rag-$(date +%F).dump
```

Restore:

```bash
pg_restore -U <db_user> -d <db_name> --clean --if-exists /var/backups/knowledge-rag-YYYY-MM-DD.dump
```

Operational policy:

- Keep at least daily backups with retention policy.
- Validate restore regularly on a staging environment.

