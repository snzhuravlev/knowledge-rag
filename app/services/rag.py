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

    async def fetch_hybrid_chunks(
        self,
        query_text: str,
        query_embedding: List[float],
        vector_k: int = 20,
        lexical_k: int = 40,
    ) -> List[SourceChunk]:
        vector_chunks = await self.chunk_repo.fetch_top_k(query_embedding, vector_k)
        lexical_chunks = await self.chunk_repo.fetch_by_source_path_terms(query_text, lexical_k)
        merged: List[SourceChunk] = []
        seen = set()
        for chunk in lexical_chunks + vector_chunks:
            key = (chunk.source, chunk.id)
            if key in seen:
                continue
            seen.add(key)
            merged.append(chunk)
        return merged

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
        if self.settings.generation_provider == "openai":
            return await self._generate_answer_openai(prompt)
        model_name = self._normalize_model_name(self.settings.generation_model)
        generation_models = [
            model_name,
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-flash-latest",
        ]
        unique_models = []
        for name in generation_models:
            if name not in unique_models:
                unique_models.append(name)

        last_error: Exception | None = None
        response = None
        for candidate in unique_models:
            try:
                response = self.client.models.generate_content(
                    model=candidate,
                    contents=prompt,
                )
                break
            except ClientError as exc:
                if exc.code == 404:
                    last_error = exc
                    continue
                raise
        if response is None:
            if self.openai_client is not None:
                return await self._generate_answer_openai(prompt)
            raise RuntimeError(
                "No available generation model found for this API key. "
                f"Tried: {', '.join(unique_models)}"
            ) from last_error
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
        if self.settings.generation_provider == "openai":
            async for piece in self._generate_answer_stream_openai(prompt):
                yield piece
            return
        model_name = self._normalize_model_name(self.settings.generation_model)
        generation_models = [
            model_name,
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-flash-latest",
        ]
        unique_models = []
        for name in generation_models:
            if name not in unique_models:
                unique_models.append(name)

        last_error: Exception | None = None
        stream = None
        for candidate in unique_models:
            try:
                stream = self.client.models.generate_content_stream(
                    model=candidate,
                    contents=prompt,
                )
                break
            except ClientError as exc:
                if exc.code == 404:
                    last_error = exc
                    continue
                raise
        if stream is None:
            if self.openai_client is not None:
                async for piece in self._generate_answer_stream_openai(prompt):
                    yield piece
                return
            raise RuntimeError(
                "No available stream generation model found for this API key. "
                f"Tried: {', '.join(unique_models)}"
            ) from last_error

        if hasattr(stream, "__aiter__"):
            async for event in stream:
                for part in getattr(event, "candidates", []) or []:
                    content = getattr(part, "content", None)
                    if not content:
                        continue
                    for sub in getattr(content, "parts", []):
                        value = getattr(sub, "text", None)
                        if isinstance(value, str) and value:
                            yield value
        else:
            for event in stream:
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

    def _openai_generation_model(self) -> str:
        model = self.settings.generation_model
        # If generation model is set to a Gemini id, use OpenAI default.
        if model.startswith("gemini"):
            return "gpt-4o-mini"
        return model

    async def _generate_answer_openai(self, prompt: str) -> str:
        if self.openai_client is None:
            raise RuntimeError("OpenAI client is not configured for generation.")
        model = self._openai_generation_model()
        response = self.openai_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        text = response.choices[0].message.content if response.choices else ""
        return (text or "").strip()

    async def _generate_answer_stream_openai(self, prompt: str) -> AsyncGenerator[str, None]:
        if self.openai_client is None:
            raise RuntimeError("OpenAI client is not configured for generation.")
        model = self._openai_generation_model()
        stream = self.openai_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            stream=True,
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
