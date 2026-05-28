from __future__ import annotations

"""
Local image analysis using ibm-granite/granite-vision-3.2-2b.

Runs at ingestion time (offline mode) as the primary image analyzer.
The model is lazy-loaded on first call and kept resident for the
duration of the ingest session. Call unload_model() when ingestion
is done to release memory.
"""

from functools import lru_cache
from pathlib import Path

import structlog

log = structlog.get_logger()

_MODEL_ID = "ibm-granite/granite-vision-3.2-2b"

_PROMPT = (
    "Describe this image completely and in detail. Extract and include:\n"
    "- All visible text, labels, numbers, codes, identifiers\n"
    "- If a diagram: nodes, edges, relationships, flow direction, all labels\n"
    "- If a chart or graph: axes, data values, trends, legend, title\n"
    "- If a UI screenshot: components, button labels, text fields, state, layout\n"
    "- If a document, slide, or form: full readable content\n"
    "- If a photograph: subjects, objects, setting, notable details\n"
    "- Document or image type if identifiable\n\n"
    "Be exhaustive — describe everything a user might ask about."
)


@lru_cache(maxsize=1)
def _load_model():
    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor  # type: ignore

    log.info("granite_vision.loading", model=_MODEL_ID)
    processor = AutoProcessor.from_pretrained(_MODEL_ID)

    if torch.backends.mps.is_available():
        device, dtype = "mps", torch.float16
    elif torch.cuda.is_available():
        device, dtype = "cuda", torch.float16
    else:
        device, dtype = "cpu", torch.float32

    model = AutoModelForImageTextToText.from_pretrained(
        _MODEL_ID,
        torch_dtype=dtype,
        low_cpu_mem_usage=True,
    ).to(device)
    model.eval()
    log.info("granite_vision.loaded", device=device, dtype=str(dtype))
    return processor, model


def is_model_loaded() -> bool:
    """Return True if the vision model is currently resident in memory."""
    return _load_model.cache_info().currsize > 0


def unload_model() -> None:
    """Release device memory after ingestion. Safe to call even if never loaded."""
    if _load_model.cache_info().currsize == 0:
        return
    _load_model.cache_clear()
    try:
        import torch
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
        elif torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    log.info("granite_vision.unloaded")


def analyze_image_granite(abs_path: Path) -> str:
    """
    Analyze an image with granite-vision-3.2-2b.
    Returns a rich text description, or "" on any failure.
    """
    try:
        from PIL import Image as PILImage  # type: ignore
        import torch

        processor, model = _load_model()

        image = PILImage.open(abs_path).convert("RGB")
        messages = [
            {
                "role": "user",
                "content": [{"type": "image"}, {"type": "text", "text": _PROMPT}],
            }
        ]
        text = processor.apply_chat_template(messages, add_generation_prompt=True)
        inputs = processor(images=image, text=text, return_tensors="pt")

        device = next(model.parameters()).device
        inputs = {k: v.to(device) for k, v in inputs.items()}

        with torch.no_grad():
            output_ids = model.generate(
                **inputs,
                max_new_tokens=512,
                do_sample=False,
            )

        # Decode only newly generated tokens — strip the echoed prompt
        new_tokens = output_ids[0][inputs["input_ids"].shape[-1]:]
        result = processor.decode(new_tokens, skip_special_tokens=True).strip()

        log.info("granite_vision.analyzed", path=str(abs_path), output_chars=len(result))
        return result

    except Exception as e:
        log.warning("granite_vision.failed", path=str(abs_path), error=str(e))
        return ""
