from typing import AsyncGenerator, List

from google import genai
from google.genai.errors import ClientError
from openai import OpenAI

from app.config import Settings
from app.db.repositories import ChunkRepository
from app.schemas import SourceChunk


class RagService:
    def __init__(
        self,
        settings: Settings,
        chunk_repo: ChunkRepository,
        client: genai.Client,
        openai_client: OpenAI | None = None,
    ) -> None:
        self.settings = settings
        self.chunk_repo = chunk_repo
        self.client = client
        self.openai_client = openai_client

    async def embed_query(self, text: str) -> List[float]:
        if self.settings.embedding_provider == "openai":
            if self.openai_client is None:
                raise RuntimeError("OpenAI client is not configured.")
            response = self.openai_client.embeddings.create(
                model=self.settings.embedding_model,
                input=text,
                dimensions=self.settings.vector_dim,
            )
            return list(response.data[0].embedding)

        model_name = self._normalize_model_name(self.settings.embedding_model)
        fallback_models = [
            model_name,
            "text-embedding-004",
            "gemini-embedding-001",
            "embedding-001",
        ]
        unique_models = []
        for name in fallback_models:
            if name not in unique_models:
                unique_models.append(name)

        last_error: Exception | None = None
        response = None
        for candidate in unique_models:
            try:
                response = self.client.models.embed_content(
                    model=candidate,
                    contents=text,
                )
                break
            except ClientError as exc:
                if exc.code == 404:
                    last_error = exc
                    continue
                raise

        if response is None:
            raise RuntimeError(
                "No available embedding model found for this API key. "
                f"Tried: {', '.join(unique_models)}"
            ) from last_error
        embedding = getattr(response, "embeddings", None)
        if not embedding:
            raise RuntimeError("Embedding model did not return embeddings.")
        vector = embedding[0].values if hasattr(embedding[0], "values") else embedding[0]
        return list(vector)

    async def fetch_top_k_chunks(self, query_embedding: List[float], k: int = 5) -> List[SourceChunk]:
        return await self.chunk_repo.fetch_top_k(query_embedding, k)

    @staticmethod
    def build_rag_prompt(query: str, chunks: List[SourceChunk]) -> str:
        context_blocks = []
        for idx, chunk in enumerate(chunks, start=1):
            label = f"Source {idx}"
            if chunk.source:
                label += f" ({chunk.source})"
            context_blocks.append(f"{label}:\n{chunk.content}")

        context_text = "\n\n".join(context_blocks) if context_blocks else "No additional context."
        return (
            "You are an assistant that answers questions using the provided context.\n"
            "Use only the information from the context where possible, and clearly say when something is not covered.\n\n"
            f"User question:\n{query}\n\n"
            "Context:\n"
            f"{context_text}\n\n"
            "Answer in a clear and structured way."
        )

    async def generate_answer(self, prompt: str) -> str:
        model_name = self._normalize_model_name(self.settings.generation_model)
        response = self.client.models.generate_content(
            model=model_name,
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

    async def generate_answer_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        model_name = self._normalize_model_name(self.settings.generation_model)
        stream = self.client.models.generate_content_stream(
            model=model_name,
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

    @staticmethod
    def _normalize_model_name(model_name: str) -> str:
        # Keep backward compatibility with older docs that used "google/<model>".
        return model_name.split("/", 1)[1] if model_name.startswith("google/") else model_name
