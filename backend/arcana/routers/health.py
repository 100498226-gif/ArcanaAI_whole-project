from __future__ import annotations

from fastapi import APIRouter

from arcana.vector_store import get_code_collection, get_doc_collection

router = APIRouter()


@router.get("/")
async def health() -> dict:
    try:
        code_count = get_code_collection().count()
        doc_count = get_doc_collection().count()
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}

    return {
        "status": "ok",
        "chunks": {
            "code": code_count,
            "doc": doc_count,
            "total": code_count + doc_count,
        },
    }
