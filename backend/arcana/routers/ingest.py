"""
POST /ingest/local  — ingest local directories (.md and .txt)
POST /ingest/upload — upload a single .md or .txt file from the browser
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel

from arcana.config import settings
from arcana.services.ingestion import ingest_local

router = APIRouter()

_ALLOWED_EXTENSIONS = {".md", ".txt"}


def _uploads_dir() -> Path:
    """Return the uploads directory, creating it if needed."""
    uploads = Path(settings.chromadb_path).parent / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    return uploads


class IngestLocalRequest(BaseModel):
    paths: Optional[List[str]] = None


@router.post("/local")
async def ingest_local_endpoint(body: IngestLocalRequest = IngestLocalRequest()) -> dict:
    """Ingest local directories (.md and .txt)."""
    if not body.paths:
        raise HTTPException(
            status_code=422,
            detail="paths must be a non-empty list of absolute directory paths",
        )
    return await ingest_local(body.paths)


@router.post("/upload")
async def upload_file(file: UploadFile) -> dict:
    """
    Upload a single .md or .txt file.
    The file is saved to the uploads directory and immediately ingested.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Only .md and .txt files are accepted. Got: {ext or '(no extension)'}",
        )

    uploads = _uploads_dir()
    dest = uploads / file.filename

    try:
        with dest.open("wb") as f:
            shutil.copyfileobj(file.file, f)
    finally:
        await file.close()

    result = await ingest_local([str(uploads)])
    return {
        "status": "ok",
        "file_name": file.filename,
        "chunks_ingested": result.get("embedded", 0),
        "errors": result.get("errors", []),
    }
