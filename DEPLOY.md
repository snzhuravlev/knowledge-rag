## Деплой RAG-сервиса на Ubuntu 24.04 с доменом `knowledge.home.arpa`

### 1. Подготовка сервера

1. Установить зависимости:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip nginx
```

2. Клонировать проект:

```bash
cd /opt
sudo git clone <URL_ВАШЕГО_РЕПОЗИТОРИЯ> knowledge-rag
sudo chown -R $USER:$USER knowledge-rag
cd knowledge-rag
```

3. Создать и заполнить `.env`:

```bash
cp .env.example .env
nano .env
```

- Указать реальный `GOOGLE_API_KEY`.
- Настроить параметры PostgreSQL.
- Задать `AUTH_SECRET_KEY` (случайная длинная строка).

4. Создать виртуальное окружение и установить зависимости:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate
```

### 2. Настройка PostgreSQL и схемы БД

1. Включить pgvector и создать расширение (если ещё не сделано):

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

2. Создать таблицу пользователей:

```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin', 'reader')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

3. Создать таблицу источников:

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

4. Таблица с чанками (`my_notebook_data`) с pgvector:

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

5. Создать первого администратора (пароль нужно захешировать через Python/Passlib или временную утилиту):

```python
from passlib.context import CryptContext
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
print(pwd_context.hash("your_admin_password"))
```

```sql
INSERT INTO users (username, password_hash, role)
VALUES ('admin', '<ХЭШ_ПАРОЛЯ>', 'admin');
```

### 3. Systemd-сервис для Uvicorn

Создать файл `/etc/systemd/system/knowledge-rag.service`:

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

Затем:

```bash
sudo systemctl daemon-reload
sudo systemctl enable knowledge-rag
sudo systemctl start knowledge-rag
sudo systemctl status knowledge-rag
```

### 4. DNS и Nginx под `knowledge.home.arpa`

#### DNS

- На внутреннем DNS-сервере создать запись:
  - Тип: `A`
  - Имя: `knowledge.home.arpa`
  - Значение: внутренний IP Ubuntu-сервера.

#### Nginx (reverse proxy)

Создать `/etc/nginx/sites-available/knowledge-rag`:

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

Включить сайт:

```bash
sudo ln -s /etc/nginx/sites-available/knowledge-rag /etc/nginx/sites-enabled/knowledge-rag
sudo nginx -t
sudo systemctl reload nginx
```

### 5. Self-signed SSL для `knowledge.home.arpa`

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

Сертификат нужно импортировать в доверенные в браузерах/клиентских ОС, если вы хотите избавиться от предупреждений.

### 6. Обновление приложения

```bash
cd /opt/knowledge-rag
sudo -u www-data git pull
sudo -u www-data /opt/knowledge-rag/.venv/bin/pip install -r requirements.txt
sudo systemctl restart knowledge-rag
```

