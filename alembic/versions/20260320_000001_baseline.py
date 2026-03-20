"""Baseline schema for users, sources, knowledge base."""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260320_000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('admin', 'reader')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sources (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            file_path TEXT NOT NULL,
            original_name TEXT NOT NULL,
            format TEXT NOT NULL,
            is_archive BOOLEAN NOT NULL DEFAULT FALSE,
            status TEXT NOT NULL DEFAULT 'pending',
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_base (
            id SERIAL PRIMARY KEY,
            file_path TEXT,
            content TEXT,
            embedding VECTOR(768),
            metadata JSONB
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS knowledge_base_embedding_idx
            ON knowledge_base
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS knowledge_base_embedding_idx;")
    op.execute("DROP TABLE IF EXISTS knowledge_base;")
    op.execute("DROP TABLE IF EXISTS sources;")
    op.execute("DROP TABLE IF EXISTS users;")
