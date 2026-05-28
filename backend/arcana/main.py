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

from arcana.routers import health, query, ingest, conversations, files
from arcana.vector_store import get_code_collection, get_doc_collection

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Ensure online ChromaDB collections exist on startup
    get_code_collection()
    get_doc_collection()
    yield


app = FastAPI(
    title="Arcana",
    description="RAG-powered personal knowledge assistant",
    version="0.2.0",
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
app.include_router(conversations.router, prefix="/conversations", tags=["conversations"])
app.include_router(files.router, prefix="/files", tags=["files"])
