"""
GET  /settings/  — return current settings
POST /settings/  — patch online_mode
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from arcana.services.settings_store import load_settings, save_settings

router = APIRouter()


class SettingsPatch(BaseModel):
    online_mode: Optional[bool] = None
    offline_model: Optional[str] = None
    offline_use_context: Optional[bool] = None


@router.get("/")
def get_settings() -> dict:
    return load_settings()


@router.post("/")
def update_settings(patch: SettingsPatch) -> dict:
    current = load_settings()
    if patch.online_mode is not None:
        current["online_mode"] = patch.online_mode
    if patch.offline_model is not None:
        current["offline_model"] = patch.offline_model
    if patch.offline_use_context is not None:
        current["offline_use_context"] = patch.offline_use_context
    save_settings(current)
    return current
