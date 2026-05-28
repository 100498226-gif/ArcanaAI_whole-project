from __future__ import annotations
"""
POST /ingest/local — ingest local .md and .txt files from a directory path.
"""
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from arcana.services.ingestion import ingest_local

router = APIRouter()


class IngestLocalRequest(BaseModel):
    paths: Optional[List[str]] = None       # absolute directory paths to ingest


@router.post("/local")
async def ingest_local_endpoint(body: IngestLocalRequest = IngestLocalRequest()) -> dict:
    """Ingest local directories (.md and .txt). Available in both online and offline modes."""
    if not body.paths:
        raise HTTPException(
            status_code=422,
            detail="paths must be a non-empty list of absolute directory paths",
        )
    return await ingest_local(body.paths)
