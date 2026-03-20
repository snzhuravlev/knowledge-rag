import json
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.dependencies import get_state, require_reader
from app.schemas import ChatRequest, ChatResponse, ChatStreamRequest, User
from app.state import AppState

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    payload: ChatRequest,
    _: User = Depends(require_reader),
    state: AppState = Depends(get_state),
) -> ChatResponse:
    client_ip = request.client.host if request.client else "unknown"
    state.rate_limiter.check(f"chat:{client_ip}", state.settings.chat_rate_limit_per_minute)
    if not payload.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")
    query_embedding = await state.rag_service.embed_query(payload.query)
    chunks = await state.rag_service.fetch_top_k_chunks(query_embedding, k=5)
    prompt = state.rag_service.build_rag_prompt(payload.query, chunks)
    answer = await state.rag_service.generate_answer(prompt)
    return ChatResponse(answer=answer, sources=chunks)


@router.post("/chat-stream")
async def chat_stream(
    request: Request,
    payload: ChatStreamRequest,
    _: User = Depends(require_reader),
    state: AppState = Depends(get_state),
) -> StreamingResponse:
    client_ip = request.client.host if request.client else "unknown"
    state.rate_limiter.check(f"chat:{client_ip}", state.settings.chat_rate_limit_per_minute)
    if not payload.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")
    query_embedding = await state.rag_service.embed_query(payload.query)
    chunks = await state.rag_service.fetch_top_k_chunks(query_embedding, k=20)
    prompt = state.rag_service.build_rag_prompt(payload.query, chunks)

    async def event_generator() -> AsyncGenerator[bytes, None]:
        meta = {"type": "meta", "sources": [chunk.dict() for chunk in chunks]}
        yield f"data: {json.dumps(meta, ensure_ascii=False)}\n\n".encode("utf-8")
        async for piece in state.rag_service.generate_answer_stream(prompt):
            payload_delta = {"type": "delta", "text": piece}
            yield f"data: {json.dumps(payload_delta, ensure_ascii=False)}\n\n".encode("utf-8")
        yield b"data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
