from typing import AsyncGenerator, List

from google import genai

from app.config import Settings
from app.db.repositories import ChunkRepository
from app.schemas import SourceChunk


class RagService:
    def __init__(self, settings: Settings, chunk_repo: ChunkRepository, client: genai.Client) -> None:
        self.settings = settings
        self.chunk_repo = chunk_repo
        self.client = client

    async def embed_query(self, text: str) -> List[float]:
        response = self.client.models.embed_content(
            model=self.settings.embedding_model,
            contents=text,
        )
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
        response = self.client.models.generate_content(
            model=self.settings.generation_model,
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
        stream = self.client.models.generate_content_stream(
            model=self.settings.generation_model,
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
