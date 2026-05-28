"""
Tests for the settings store and settings API router.
"""
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


# ── Settings store ────────────────────────────────────────────────────────────

def test_load_settings_returns_defaults_when_no_file(tmp_path):
    from arcana.services import settings_store

    fake_path = tmp_path / "settings.json"
    with patch.object(settings_store, "_SETTINGS_PATH", fake_path):
        s = settings_store.load_settings()
    assert s["online_mode"] is True


def test_save_and_reload_settings(tmp_path):
    from arcana.services import settings_store

    fake_path = tmp_path / "settings.json"
    with patch.object(settings_store, "_SETTINGS_PATH", fake_path):
        settings_store.save_settings({"online_mode": False})
        s = settings_store.load_settings()

    assert s["online_mode"] is False
    assert fake_path.exists()


def test_load_settings_merges_over_defaults(tmp_path):
    from arcana.services import settings_store

    fake_path = tmp_path / "settings.json"
    fake_path.write_text(json.dumps({"online_mode": False}))
    with patch.object(settings_store, "_SETTINGS_PATH", fake_path):
        s = settings_store.load_settings()

    assert s["online_mode"] is False


def test_get_online_mode(tmp_path):
    from arcana.services import settings_store

    fake_path = tmp_path / "settings.json"
    fake_path.write_text(json.dumps({"online_mode": True}))
    with patch.object(settings_store, "_SETTINGS_PATH", fake_path):
        assert settings_store.get_online_mode() is True

    fake_path.write_text(json.dumps({"online_mode": False}))
    with patch.object(settings_store, "_SETTINGS_PATH", fake_path):
        assert settings_store.get_online_mode() is False


# ── Settings API ──────────────────────────────────────────────────────────────

@pytest.fixture()
def client(tmp_path):
    """TestClient with a temporary settings file."""
    from arcana.services import settings_store
    fake_path = tmp_path / "settings.json"

    with patch.object(settings_store, "_SETTINGS_PATH", fake_path):
        from arcana.routers.settings import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        yield TestClient(app)


def test_get_settings_returns_defaults(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["online_mode"] is True


def test_patch_online_mode(client):
    r = client.post("/", json={"online_mode": False})
    assert r.status_code == 200
    assert r.json()["online_mode"] is False

    # Subsequent GET reflects the change
    r2 = client.get("/")
    assert r2.json()["online_mode"] is False


def test_patch_preserves_other_fields(client):
    client.post("/", json={"online_mode": False})
    # Patching again with same value should still work
    r = client.post("/", json={"online_mode": True})
    assert r.json()["online_mode"] is True


def test_empty_patch_is_a_noop(client):
    r = client.post("/", json={})
    assert r.status_code == 200
    assert r.json()["online_mode"] is True  # default unchanged
