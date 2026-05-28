from __future__ import annotations

from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from arcana.config import settings

_client: Optional[chromadb.ClientAPI] = None


def get_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        path = settings.chromadb_path
        Path(path).mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(
            path=path,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    return _client


def reset_client() -> None:
    """Force the singleton to re-initialise on the next get_client() call.
    Used by the demo seed script to switch between production and demo stores."""
    global _client
    _client = None


def get_code_collection() -> chromadb.Collection:
    """Embedded code: functions, classes, file sections — Gemini embeddings (online mode)."""
    return get_client().get_or_create_collection(
        name="code_chunks",
        metadata={"hnsw:space": "cosine"},
    )


def get_doc_collection() -> chromadb.Collection:
    """Documentation sections from Notion and uploaded overviews — Gemini embeddings (online mode)."""
    return get_client().get_or_create_collection(
        name="doc_chunks",
        metadata={"hnsw:space": "cosine"},
    )


def get_cache_collection() -> chromadb.Collection:
    """Semantic query cache — stores query embeddings + full responses."""
    return get_client().get_or_create_collection(
        name="query_cache",
        metadata={"hnsw:space": "cosine"},
    )


def health_check() -> bool:
    try:
        get_client().heartbeat()
        return True
    except Exception:
        return False
