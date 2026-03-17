# Local RAG UI (FastAPI + PostgreSQL + Gemini)

Минималистичный веб-интерфейс для локальной RAG-системы:

- Backend: FastAPI + asyncpg + PostgreSQL с pgvector.
- Хранение чанков в таблице `my_notebook_data`.
- Эмбеддинги: `google/text-embedding-004`.
- Генерация ответов: `google/gemini-flash-latest`.
- Веб-UI: Tailwind, чат + список источников, стриминг ответов.
- Роли пользователей: `admin`, `reader`.

## Структура проекта

- `app/main.py` — FastAPI-приложение, авторизация, чат, CRUD по источникам, индексация.
- `static/index.html` — фронтенд (чат, отображение источников, базовая работа с токеном).
- `requirements.txt` — зависимости.
- `.env.example` — пример настроек окружения.
- `DEPLOY.md` — подробная инструкция по деплою под `knowledge.home.arpa`.

## Настройка окружения

1. Создать виртуальное окружение:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

2. Создать `.env`:

```bash
cp .env.example .env
nano .env
```

Ключевые переменные:

- `GOOGLE_API_KEY` — ключ Gemini API.
- `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `DB_HOST` — доступ к PostgreSQL.
- `AUTH_SECRET_KEY` — секрет для подписи JWT.
- `RAG_TABLE_NAME` и другие `RAG_*` — имена таблиц/колонок и параметры векторного поиска.

3. Настроить БД (расширение pgvector, таблицы `users`, `sources`, `my_notebook_data`). SQL-примеры — в `DEPLOY.md`.

## Запуск в dev-режиме

```bash
source .venv/bin/activate
uvicorn app.main:app --reload
```

Интерфейс будет доступен по адресу:

- `http://127.0.0.1:8000/`

## Роли и аутентификация

- `admin`:
  - может загружать новые источники (книги/документы),
  - управлять ими (редактировать заголовок, удалять),
  - использовать чат.
- `reader`:
  - может только использовать чат и просматривать список источников.

Токены:

- Эндпоинт логина: `POST /auth/login` (OAuth2 Password Flow).
- Эндпоинт профиля: `GET /auth/me`.

## Индексация источников

- Файл (или архив) загружается через эндпоинт `POST /api/sources` (для admin).
- Поддерживаемые форматы: `pdf`, `docx`, `epub`, `fb2`, `txt` (по расширению файла).
- Текст извлекается, нормализуется и режется на чанки.
- Для каждого чанка вычисляется эмбеддинг и создаётся запись в `my_notebook_data`.
- Статус источника:
  - `pending` → создан, ждёт индексации;
  - `indexing` → идёт обработка;
  - `ready` → полностью проиндексирован;
  - `failed` → ошибка, текст ошибки сохраняется в `error_message`.

Индексация запускается в фоне (`BackgroundTasks`) после загрузки.

## Использование чата

- Чат-эндпоинты:
  - `POST /api/chat` — классический запрос/ответ.
  - `POST /api/chat-stream` — стриминговый ответ (Server-Sent Events).
- Чат требует авторизации (роль `reader` или `admin`).
- UI:
  - поле ввода запроса,
  - потоковый ответ ассистента,
  - панель источников с пагинацией.

## Деплой

Подробная инструкция (Ubuntu 24.04, домен `knowledge.home.arpa`, Nginx, self-signed SSL, systemd-сервис) — в файле `DEPLOY.md`.

