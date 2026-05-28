from __future__ import annotations

import httpx
from fastapi import APIRouter

from arcana.config import settings
from arcana.services.local_embedder import is_model_loaded
from arcana.services.settings_store import get_offline_model, get_online_mode
from arcana.vector_store import get_code_collection, get_doc_collection

router = APIRouter()

_OLLAMA_TIMEOUT = httpx.Timeout(connect=1.5, read=3.0, write=2.0, pool=1.5)


async def _check_ollama() -> bool:
    """Ping the Ollama server. Returns True if reachable."""
    try:
        async with httpx.AsyncClient(timeout=_OLLAMA_TIMEOUT) as client:
            r = await client.get(f"{settings.ollama_base_url}/")
            return r.status_code == 200
    except Exception:
        return False


async def _check_llm_loaded(model_name: str) -> bool:
    """Return True if the given model is currently resident in Ollama RAM."""
    try:
        async with httpx.AsyncClient(timeout=_OLLAMA_TIMEOUT) as client:
            r = await client.get(f"{settings.ollama_base_url}/api/ps")
            if r.status_code != 200:
                return False
            data = r.json()
            loaded = {m.get("name", "") for m in data.get("models", [])}
            return model_name in loaded
    except Exception:
        return False


@router.get("/")
async def health() -> dict:
    try:
        code_count = get_code_collection().count()
        doc_count = get_doc_collection().count()
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}

    from arcana.services.granite_vision_client import is_model_loaded as vision_loaded

    online_mode = get_online_mode()
    offline_model = get_offline_model()
    ollama_available = await _check_ollama()
    llm_model_loaded = await _check_llm_loaded(offline_model) if ollama_available else False

    return {
        "status": "ok",
        "online_mode": online_mode,
        "ollama_available": ollama_available,
        "embedding_model_ready": is_model_loaded(),
        "llm_model_name": offline_model,
        "llm_model_loaded": llm_model_loaded,
        "vision_model_loaded": vision_loaded(),
        "code_chunks": code_count,
        "doc_chunks": doc_count,
        "total_chunks": code_count + doc_count,
    }
