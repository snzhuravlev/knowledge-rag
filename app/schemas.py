from typing import List, Optional

from pydantic import BaseModel


class ChatRequest(BaseModel):
    query: str


class ChatStreamRequest(BaseModel):
    query: str


class SourceChunk(BaseModel):
    id: int
    content: str
    source: Optional[str] = None
    score: float


class ChatResponse(BaseModel):
    answer: str
    sources: List[SourceChunk]


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class User(BaseModel):
    id: int
    username: str
    role: str


class SourceBase(BaseModel):
    title: str


class SourceOut(SourceBase):
    id: int
    original_name: str
    format: str
    status: str


class SourceUpdate(BaseModel):
    title: Optional[str] = None
