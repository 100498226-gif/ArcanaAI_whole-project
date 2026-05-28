from pathlib import Path

import pytest

from arcana.services.chunker import chunk_file


def _make_img(tmp_path: Path) -> Path:
    p = tmp_path / "sample.png"
    # Minimal PNG header; content not important for this test
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    return p


def test_image_chunk_generation(tmp_path: Path, monkeypatch):
    img_path = _make_img(tmp_path)
    file_info = {
        "abs_path": img_path,
        "file_path": img_path.name,
        "language": "image",
        "last_modified": None,
    }

    # Gemini: skip (offline mode)
    monkeypatch.setattr(
        "arcana.services.vision_analyzer.analyze_image_with_vision_sync",
        lambda p: "",
        raising=False,
    )
    # granite-vision: simulate failure so OCR fallback is exercised
    monkeypatch.setattr(
        "arcana.services.granite_vision_client.analyze_image_granite",
        lambda p: "",
        raising=False,
    )
    # OCR: return deterministic text
    monkeypatch.setattr(
        "arcana.services.vision_ocr.ocr_image",
        lambda p: "DNI: 12345678",
        raising=False,
    )

    chunks = chunk_file(
        abs_path=img_path,
        file_info=file_info,
        repo_name="local_test",
        access_scope="all",
        ingested_at="2026-01-01T00:00:00Z",
    )

    assert isinstance(chunks, list)
    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.metadata.get("chunk_type") == "image_vision"
    assert chunk.metadata.get("source_type") == "image"
    assert "DNI" in chunk.text


def test_image_granite_primary(tmp_path: Path, monkeypatch):
    """When granite succeeds, its description is used and OCR is not called."""
    img_path = _make_img(tmp_path)
    file_info = {
        "abs_path": img_path,
        "file_path": img_path.name,
        "language": "image",
        "last_modified": None,
    }

    monkeypatch.setattr(
        "arcana.services.vision_analyzer.analyze_image_with_vision_sync",
        lambda p: "",
        raising=False,
    )
    monkeypatch.setattr(
        "arcana.services.granite_vision_client.analyze_image_granite",
        lambda p: "A screenshot showing a login form with email and password fields.",
        raising=False,
    )
    ocr_called = []
    monkeypatch.setattr(
        "arcana.services.vision_ocr.ocr_image",
        lambda p: ocr_called.append(p) or "",
        raising=False,
    )

    chunks = chunk_file(
        abs_path=img_path,
        file_info=file_info,
        repo_name="local_test",
        access_scope="all",
        ingested_at="2026-01-01T00:00:00Z",
    )

    assert len(chunks) == 1
    assert "login form" in chunks[0].text
    assert len(ocr_called) == 0  # OCR not reached when granite succeeds


def test_image_last_resort_caption(tmp_path: Path, monkeypatch):
    """When all analyzers fail, filename caption is used."""
    img_path = _make_img(tmp_path)
    file_info = {
        "abs_path": img_path,
        "file_path": img_path.name,
        "language": "image",
        "last_modified": None,
    }

    monkeypatch.setattr(
        "arcana.services.vision_analyzer.analyze_image_with_vision_sync",
        lambda p: "",
        raising=False,
    )
    monkeypatch.setattr(
        "arcana.services.granite_vision_client.analyze_image_granite",
        lambda p: "",
        raising=False,
    )
    monkeypatch.setattr(
        "arcana.services.vision_ocr.ocr_image",
        lambda p: "",
        raising=False,
    )

    chunks = chunk_file(
        abs_path=img_path,
        file_info=file_info,
        repo_name="local_test",
        access_scope="all",
        ingested_at="2026-01-01T00:00:00Z",
    )

    assert len(chunks) == 1
    assert "sample.png" in chunks[0].text
