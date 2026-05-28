import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

import structlog
from fastapi import FastAPI

# Route stdlib logging → stdout so structlog's LoggerFactory has somewhere to write
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from arcana.config import settings
from arcana.routers import health, query, ingest, offline as offline_router, settings as settings_router
from arcana.vector_store import get_code_collection, get_doc_collection, get_code_collection_local, get_doc_collection_local

log = structlog.get_logger()



async def _prewarm_llm_model() -> None:
    """Warm up the saved Ollama LLM model on startup when in offline mode."""
    from arcana.services.settings_store import get_offline_model, get_online_mode
    if get_online_mode():
        return
    model = get_offline_model()
    if not model:
        return
    try:
        import httpx
        from arcana.config import settings as _s
        url = f"{_s.ollama_base_url}/v1/chat/completions"
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Hi"}],
            "stream": False,
            "max_tokens": 1,
            "keep_alive": 300,
        }
        log.info("startup.prewarm_llm.start", model=model)
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=150.0, write=5.0, pool=5.0)) as client:
            await client.post(url, json=payload)
        log.info("startup.prewarm_llm.ready", model=model)
    except Exception as exc:
        log.warning("startup.prewarm_llm.failed", model=model, error=str(exc))


async def _prewarm_local_model() -> None:
    """Load the BGE embedding model into memory at startup.

    This runs in the background so the server is ready immediately, but the
    model is warm before the first offline query arrives — avoiding a 30-60s
    cold-start (download on first use / load from disk cache).
    """
    try:
        from arcana.services.local_embedder import embed_query_local
        log.info("startup.prewarm_local_embedder.start")
        await embed_query_local("warmup")
        log.info("startup.prewarm_local_embedder.ready")
    except Exception as exc:
        log.warning("startup.prewarm_local_embedder.failed", error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Ensure all ChromaDB collections exist on startup
    get_code_collection()
    get_doc_collection()
    get_code_collection_local()
    get_doc_collection_local()
    # OCR startup checks removed; proceed with normal startup
    asyncio.create_task(_prewarm_local_model())
    asyncio.create_task(_prewarm_llm_model())
    yield


app = FastAPI(
    title="Arcana",
    description="RAG-powered developer knowledge base",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(query.router, prefix="/query", tags=["query"])
app.include_router(ingest.router, prefix="/ingest", tags=["ingest"])
app.include_router(offline_router.router, prefix="/offline", tags=["offline"])
app.include_router(settings_router.router, prefix="/settings", tags=["settings"])

# Serve the test UI
try:
    app.mount("/", StaticFiles(directory="../ui", html=True), name="ui")
except Exception:
    pass
