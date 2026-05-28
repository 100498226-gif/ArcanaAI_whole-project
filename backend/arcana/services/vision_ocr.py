from __future__ import annotations

"""OCR utilities for images (optional).

Tries to perform OCR using pytesseract if available. If not installed, returns
an empty string, allowing the caller to fall back to the caption-only path.
"""

from pathlib import Path
from typing import Optional

try:
    from PIL import Image  # type: ignore
    import pytesseract  # type: ignore
except Exception:
    Image = None  # type: ignore
    pytesseract = None  # type: ignore


def ocr_image(abs_path: Path) -> str:
    if Image is None or pytesseract is None:
        return ""
    try:
        img = Image.open(abs_path)
        text = pytesseract.image_to_string(img)
        return text.strip()
    except Exception:
        return ""
