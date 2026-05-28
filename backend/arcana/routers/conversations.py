"""
GET  /conversations/     — list all conversations (history sidebar)
GET  /conversations/{id} — get messages for a conversation
DELETE /conversations/{id} — delete conversation + messages
"""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from arcana.database import get_db
from arcana.models import Conversation, Message

router = APIRouter()


# ── Response schemas ──────────────────────────────────────────────────────────

class SourceItem(BaseModel):
    file_name: str
    path: str
    abs_path: str = ""


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    sources: list[SourceItem]
    created_at: datetime

    @classmethod
    def from_orm(cls, msg: Message) -> "MessageOut":
        try:
            raw = json.loads(msg.sources_json or "[]")
            sources = [SourceItem(**s) for s in raw if isinstance(s, dict)]
        except Exception:
            sources = []
        return cls(
            id=msg.id,
            role=msg.role,
            content=msg.content,
            sources=sources,
            created_at=msg.created_at,
        )


class ConversationSummary(BaseModel):
    id: int
    title: str
    model: str
    out_of_scope: bool
    created_at: datetime


class ConversationDetail(ConversationSummary):
    messages: list[MessageOut]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/", response_model=list[ConversationSummary])
async def list_conversations(db: AsyncSession = Depends(get_db)) -> list[ConversationSummary]:
    result = await db.execute(
        select(Conversation).order_by(Conversation.created_at.desc())
    )
    rows = result.scalars().all()
    return [
        ConversationSummary(
            id=c.id,
            title=c.title,
            model=c.model,
            out_of_scope=c.out_of_scope,
            created_at=c.created_at,
        )
        for c in rows
    ]


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: int, db: AsyncSession = Depends(get_db)
) -> ConversationDetail:
    result = await db.execute(
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(Conversation.id == conversation_id)
    )
    conv = result.scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationDetail(
        id=conv.id,
        title=conv.title,
        model=conv.model,
        out_of_scope=conv.out_of_scope,
        created_at=conv.created_at,
        messages=[MessageOut.from_orm(m) for m in conv.messages],
    )


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: int, db: AsyncSession = Depends(get_db)
) -> None:
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conv = result.scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await db.delete(conv)
    await db.commit()
