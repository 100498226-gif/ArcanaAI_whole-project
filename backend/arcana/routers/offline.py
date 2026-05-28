from __future__ import annotations

"""
Offline model management endpoints.

GET  /offline/models           — list installed Ollama models + vision model status
POST /offline/load-model       — SSE: warm up a chosen Ollama LLM
POST /offline/load-vision-model — SSE: load granite-vision-3.2-2b into memory
"""

import asyncio
import json
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from arcana.config import settings
from arcana.services.settings_store import get_offline_model, load_settings, save_settings

router = APIRouter()

_HF_VISION_CACHE = (
    Path.home()
    / ".cache/huggingface/hub/models--ibm-granite--granite-vision-3.2-2b"
)

_OLLAMA_TIMEOUT  = httpx.Timeout(connect=3.0, read=10.0, write=5.0, pool=3.0)
_WARMUP_TOTAL_S  = 150   # max seconds to wait for model cold-load
_PULL_TIMEOUT_S  = 1800  # 30 min ceiling for large model downloads


# ── helpers ───────────────────────────────────────────────────────────────────

async def _ollama_get(path: str) -> dict:
    url = f"{settings.ollama_base_url}{path}"
    async with httpx.AsyncClient(timeout=_OLLAMA_TIMEOUT) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.json()


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


# ── GET /offline/models ───────────────────────────────────────────────────────

@router.get("/models")
async def list_models() -> dict:
    from arcana.services.granite_vision_client import is_model_loaded as vision_loaded

    # Installed models from Ollama
    llm_models: list[dict] = []
    try:
        tags = await _ollama_get("/api/tags")
        for m in tags.get("models", []):
            llm_models.append({
                "name": m.get("name", ""),
                "size_gb": round(m.get("size", 0) / 1e9, 1),
            })
    except Exception:
        pass

    # Which models are currently loaded (resident in RAM)
    loaded_names: set[str] = set()
    try:
        ps = await _ollama_get("/api/ps")
        for m in ps.get("models", []):
            loaded_names.add(m.get("name", ""))
    except Exception:
        pass

    # Mark loaded state on each model
    for m in llm_models:
        m["loaded"] = m["name"] in loaded_names

    return {
        "llm_models": llm_models,
        "vision_model": {
            "name": "granite-vision-3.2-2b",
            "available": _HF_VISION_CACHE.exists(),
            "loaded": vision_loaded(),
        },
        "current_model": get_offline_model(),
    }


# ── POST /offline/load-model ─────────────────────────────────────────────────

class LoadModelRequest(BaseModel):
    model: Optional[str] = None


@router.post("/load-model")
async def load_model(body: LoadModelRequest = LoadModelRequest()) -> StreamingResponse:
    model_name = body.model or get_offline_model()

    async def _stream():
        # Persist the chosen model immediately
        s = load_settings()
        s["offline_model"] = model_name
        save_settings(s)

        pull_url  = f"{settings.ollama_base_url}/api/pull"
        warmup_url = f"{settings.ollama_base_url}/v1/chat/completions"

        # ── Phase 1: ollama pull (idempotent; instant if already installed) ──
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=5.0, read=_PULL_TIMEOUT_S, write=5.0, pool=5.0)
            ) as client:
                async with client.stream(
                    "POST", pull_url, json={"name": model_name, "stream": True}
                ) as resp:
                    if resp.status_code != 200:
                        yield _sse({"type": "error", "message": f"ollama pull returned {resp.status_code}"})
                        return
                    async for raw_line in resp.aiter_lines():
                        if not raw_line:
                            continue
                        try:
                            obj = json.loads(raw_line)
                        except Exception:
                            continue
                        status = obj.get("status", "")
                        if status == "success":
                            break
                        # Build human-readable pull status
                        total     = obj.get("total", 0)
                        completed = obj.get("completed", 0)
                        if total and completed:
                            pct = int(completed / total * 100)
                            label = f"Pulling {pct}%…"
                        elif status:
                            label = status.capitalize() + "…" if not status.endswith("…") else status
                        else:
                            continue
                        yield _sse({"type": "pull", "status": label})
        except httpx.ConnectError:
            yield _sse({"type": "error", "message": "Cannot connect to Ollama — run: ollama serve"})
            return
        except httpx.TimeoutException:
            yield _sse({"type": "error", "message": f"ollama pull timed out after {_PULL_TIMEOUT_S}s"})
            return
        except Exception as exc:
            yield _sse({"type": "error", "message": str(exc)})
            return

        # ── Phase 2: warmup chat (loads model weights into VRAM) ─────────────
        warmup_payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": "Hi"}],
            "stream": True,
            "max_tokens": 1,
            "keep_alive": 300,
        }

        elapsed = 0
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=5.0, read=_WARMUP_TOTAL_S, write=5.0, pool=5.0)
            ) as client:
                async with client.stream("POST", warmup_url, json=warmup_payload) as resp:
                    if resp.status_code != 200:
                        yield _sse({"type": "error", "message": f"Ollama returned {resp.status_code}"})
                        return

                    async for line in resp.aiter_lines():
                        if not line:
                            elapsed += 1
                            yield _sse({"type": "loading", "elapsed": elapsed})
                            continue
                        if not line.startswith("data: "):
                            continue
                        raw = line[6:]
                        if raw.strip() == "[DONE]":
                            break
                        try:
                            obj = json.loads(raw)
                            delta = obj.get("choices", [{}])[0].get("delta", {})
                            if delta.get("content") is not None:
                                yield _sse({"type": "ready"})
                                return
                        except Exception:
                            continue
                        yield _sse({"type": "loading", "elapsed": elapsed})

            yield _sse({"type": "ready"})

        except httpx.TimeoutException:
            yield _sse({"type": "error", "message": f"Model load timed out after {_WARMUP_TOTAL_S}s"})
        except httpx.ConnectError:
            yield _sse({"type": "error", "message": "Cannot connect to Ollama — run: ollama serve"})
        except Exception as exc:
            yield _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(_stream(), media_type="text/event-stream")


# ── POST /offline/load-vision-model ──────────────────────────────────────────

@router.post("/load-vision-model")
async def load_vision_model() -> StreamingResponse:
    async def _stream():
        from arcana.services.granite_vision_client import _load_model, is_model_loaded

        if is_model_loaded():
            yield _sse({"type": "ready"})
            return

        if not _HF_VISION_CACHE.exists():
            yield _sse({
                "type": "error",
                "message": "Model not downloaded. Run: hf download ibm-granite/granite-vision-3.2-2b",
            })
            return

        loop = asyncio.get_running_loop()
        load_task = loop.run_in_executor(None, _load_model)
        elapsed = 0
        try:
            while not load_task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(load_task), timeout=1.0)
                    break
                except asyncio.TimeoutError:
                    elapsed += 1
                    yield _sse({"type": "loading", "elapsed": elapsed})
            # Await to surface any exception from the load
            await load_task
            yield _sse({"type": "ready"})
        except Exception as exc:
            yield _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(_stream(), media_type="text/event-stream")
