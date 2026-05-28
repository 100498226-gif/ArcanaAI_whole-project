from __future__ import annotations

"""
Vision analysis for images using Gemini (online mode only).

Analyzes images at ingestion time and stores detailed descriptions in the RAG,
enabling users to ask questions about image content (DNI, receipts, screenshots, etc.).

In offline mode, vision analysis is skipped - falls back to caption + OCR.
"""

import base64
import hashlib
from pathlib import Path

import structlog

from arcana.config import settings

log = structlog.get_logger()


def get_image_hash(abs_path: Path) -> str:
    """Compute SHA256 hash of image file for caching."""
    h = hashlib.sha256()
    h.update(abs_path.read_bytes())
    return h.hexdigest()


def analyze_image_with_vision_sync(abs_path: Path) -> str:
    """
    Analyze an image using Gemini vision (online mode only).

    In offline mode, returns empty string to trigger fallback chain (caption + OCR).
    """
    from arcana.services.settings_store import get_online_mode

    if not get_online_mode():
        log.info("vision_analyzer.skipped_offline", path=str(abs_path))
        return ""

    return _analyze_with_gemini(abs_path)


async def analyze_image_with_vision(abs_path: Path) -> str:
    """Async wrapper - calls sync version in a thread to avoid event loop issues."""
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as pool:
        return pool.submit(analyze_image_with_vision_sync, abs_path).result()


def _analyze_with_gemini(abs_path: Path) -> str:
    """Analyze an image using Gemini API."""
    try:
        from google import genai
    except Exception as e:
        log.warning("vision_analyzer.gemini_import_failed", error=str(e))
        return ""

    try:
        client = settings.build_google_client()
    except Exception as e:
        log.warning("vision_analyzer.gemini_client_failed", error=str(e))
        return ""

    try:
        image_bytes = abs_path.read_bytes()
    except Exception as e:
        log.warning("vision_analyzer.read_failed", path=str(abs_path), error=str(e))
        return ""

    prompt = """You are an expert at analyzing images and extracting all relevant information.
Analyze the provided image thoroughly and provide a detailed description that covers:

1. ALL text visible in the image (documents, signs, labels, handwritten text, etc.)
2. Numbers, codes, identifiers (ID numbers, phone numbers, addresses, dates, amounts)
3. Personal information (names, signatures, photos of people)
4. Document type and context (ID cards, receipts, screenshots, photos, diagrams)
5. Any other details a user might ask about (colors, objects, layouts, relationships)

Be extremely thorough - imagine you are describing the image to someone who cannot see it.
Include every piece of information that could be relevant for Q&A."""

    try:
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=[
                prompt,
                {"mime_type": "image/jpeg", "data": base64.b64encode(image_bytes).decode("utf-8")}
            ],
            config={
                "temperature": 0.3,
                "max_output_tokens": 1024,
            }
        )
        return response.text.strip()
    except Exception as e:
        log.warning("vision_analyzer.gemini_failed", path=str(abs_path), error=str(e))
        return ""


def get_existing_image_hashes(repo_name: str) -> set[str]:
    """Return set of image hashes already stored for this repo."""
    from arcana.vector_store import get_code_collection, get_doc_collection

    hashes: set[str] = set()
    for col in [get_code_collection(), get_doc_collection()]:
        try:
            result = col.get(
                where={"$and": [{"repo": {"$eq": repo_name}}, {"source_type": {"$eq": "image"}}]},
                include=["metadatas"],
            )
            for meta in (result.get("metadatas") or []):
                img_hash = (meta or {}).get("image_hash", "")
                if img_hash:
                    hashes.add(img_hash)
        except Exception:
            pass
    return hashes