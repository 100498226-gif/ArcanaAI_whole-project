from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path


def get_file_mtime(abs_path: Path) -> str:
    """Return the ISO 8601 modification time of a local file (UTC)."""
    ts = abs_path.stat().st_mtime
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
