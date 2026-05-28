from __future__ import annotations

"""
Image captioning utility.

Ingested images get a textual caption so they can be indexed by the RAG KB.
This module provides a fallback captioner and an optional remote captioning
path if IMAGE_CAPTION_API_URL is configured.
"""

from pathlib import Path
from typing import Optional
import os
import json
import urllib.request
import urllib.parse

from arcana.config import settings


def _caption_from_file_metadata(abs_path: Path) -> str:
    try:
        size = abs_path.stat().st_size
        return f"Image file: {abs_path.name} (size {size} bytes)."
    except Exception:
        return f"Image file: {abs_path.name}."


def _caption_from_api(abs_path: Path) -> Optional[str]:
    # Prefer explicit config first, then environment variable
    url = getattr(settings, "image_caption_api_url", "") or os.environ.get("IMAGE_CAPTION_API_URL", "")
    if not url:
        return None
    try:
        # Simple multipart/form-data POST with image bytes
        boundary = "ArcanaBoundary123456"
        with abs_path.open("rb") as f:
            body = f.read()

        data = []
        data.append(('--' + boundary))
        data.append('Content-Disposition: form-data; name="image"; filename="%s"' % abs_path.name)
        data.append('Content-Type: application/octet-stream')
        data.append('')
        data.append(body)
        data.append('--' + boundary + '--')
        data.append('')
        body_bytes = b"\r\n".join([d if isinstance(d, (bytes, bytearray)) else d.encode() for d in data])

        req = urllib.request.Request(url, data=body_bytes)
        req.add_header('Content-Type', 'multipart/form-data; boundary=%s' % boundary)
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_text = resp.read().decode("utf-8")
            try:
                payload = json.loads(resp_text)
                caption = payload.get("caption") or payload.get("text")
                if isinstance(caption, str) and caption:
                    return caption
            except Exception:
                pass
    except Exception:
        return None
    return None


def caption_image(abs_path: Path) -> str:
    """Return a textual caption for an image.

    Priority:
      1) Remote caption API (if configured)
      2) Fallback to basic metadata-based caption
    """
    caption = _caption_from_api(abs_path)
    if caption:
        return caption
    return _caption_from_file_metadata(abs_path)
