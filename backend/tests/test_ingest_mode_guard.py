"""
Tests for the local ingest endpoint.
"""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def app():
    from fastapi import FastAPI
    from arcana.routers.ingest import router
    app = FastAPI()
    app.include_router(router)
    return app


def test_local_ingest_always_allowed(app):
    """Local ingestion works in both online and offline modes."""
    mock_result = {"embedded": 5, "skipped_files": 2, "deleted_chunks": 0, "errors": []}
    with patch("arcana.routers.ingest.ingest_local", new_callable=AsyncMock, return_value=mock_result):
        with TestClient(app) as client:
            r = client.post("/local", json={"paths": ["/tmp"]})
    assert r.status_code == 200
    assert r.json()["embedded"] == 5


def test_local_ingest_requires_paths(app):
    """Omitting paths returns 422."""
    with TestClient(app) as client:
        r = client.post("/local", json={})
    assert r.status_code == 422
