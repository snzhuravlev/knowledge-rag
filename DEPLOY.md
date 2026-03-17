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
sudo git clone <URL_ВАШЕГО_РЕПОЗИТОРИЯ> knowledge-rag
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

4. Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate
```

### 2. PostgreSQL and DB schema setup

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

4. Table with chunks (`my_notebook_data`) using pgvector:

```sql
CREATE TABLE my_notebook_data (
    id           SERIAL PRIMARY KEY,
    content      TEXT NOT NULL,
    source       TEXT,
    source_id    INTEGER REFERENCES sources(id) ON DELETE CASCADE,
    chunk_index  INTEGER,
    section_title TEXT,
    embedding    VECTOR(768)
);

CREATE INDEX my_notebook_data_embedding_idx
    ON my_notebook_data
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
```

5. Create the first admin user (the password must be hashed via Python/Passlib or a temporary utility):

```python
from passlib.context import CryptContext
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
print(pwd_context.hash("your_admin_password"))
```

```sql
INSERT INTO users (username, password_hash, role)
VALUES ('admin', '<ХЭШ_ПАРОЛЯ>', 'admin');
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

### 5. Self-signed SSL for `knowledge.home.arpa`

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

### 6. Updating the application

```bash
cd /opt/knowledge-rag
sudo -u www-data git pull
sudo -u www-data /opt/knowledge-rag/.venv/bin/pip install -r requirements.txt
sudo systemctl restart knowledge-rag
```

