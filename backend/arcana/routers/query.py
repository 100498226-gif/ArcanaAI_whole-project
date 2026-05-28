"""
POST /query  — stream an answer via SSE (no authentication required).
"""
import json
from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse  # type: ignore[import]

from arcana.services.query_service import run_query_stream

router = APIRouter()


class HistoryMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    history: Optional[List[HistoryMessage]] = Field(default_factory=list)


@router.post("/")
async def query_endpoint(body: QueryRequest) -> EventSourceResponse:
    """Submit a question and receive a streaming SSE response."""
    history = [{"role": m.role, "content": m.content} for m in (body.history or [])]

    async def event_generator():
        async for event in run_query_stream(body.question.strip(), history=history):
            yield {"event": event["event"], "data": json.dumps(event["data"])}

    return EventSourceResponse(event_generator())
