"""
GET /files/reveal?path=<abs_path>  — reveal a file in Finder (macOS).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()


@router.get("/reveal")
async def reveal_file(path: str = Query(..., description="Absolute path to the file")) -> dict:
    """Open Finder with the specified file selected."""
    p = Path(path)
    if not p.is_absolute():
        raise HTTPException(status_code=400, detail="Path must be absolute")
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    subprocess.run(["open", "-R", str(p)], check=False)
    return {"status": "ok"}
