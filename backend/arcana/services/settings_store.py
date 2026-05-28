"""
Persistent settings store backed by backend/data/settings.json.

Stored keys:
  online_mode    bool  — True = online (Gemini), False = offline (Ollama)
  offline_model  str   — Ollama model name to use in offline mode
"""
from __future__ import annotations

import json
from pathlib import Path

import structlog

log = structlog.get_logger()

_SETTINGS_PATH = Path(__file__).parent.parent.parent / "data" / "settings.json"

_DEFAULTS: dict = {
    "online_mode": True,
    "offline_model": "qwen2.5:3b",
    "offline_use_context": True,
}


def load_settings() -> dict:
    """Return current settings merged over defaults."""
    if _SETTINGS_PATH.exists():
        try:
            stored = json.loads(_SETTINGS_PATH.read_text())
            return {**_DEFAULTS, **stored}
        except Exception as exc:
            log.warning("settings_store.load_error", path=str(_SETTINGS_PATH), error=str(exc))
    return _DEFAULTS.copy()


def save_settings(settings: dict) -> None:
    """Write settings atomically."""
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_PATH.write_text(json.dumps(settings, indent=2))


def get_online_mode() -> bool:
    return bool(load_settings().get("online_mode", True))


def get_offline_model() -> str:
    return str(load_settings().get("offline_model", "qwen2.5:3b"))
