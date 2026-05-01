import io
from datetime import datetime

from PIL import Image

from app.ai_integration import PROVIDER_OLLAMA, resolve_olm_ocr, vision_chat
from app.ocr_engine import _preprocess, _save_debug

_DEFAULTS = {
    "url": "http://localhost:8000",
    "model": "allenai/olmOCR-2-7B-1025",
    "prompt": (
        "Return the plain text shown in this image exactly as written. "
        "Do not add explanations, headers, or formatting."
    ),
}


def extract_text_olm(
    image: Image.Image,
    olm_cfg: dict,
    ocr_config: dict | None,
    config: dict,
) -> str:
    """Extract text via olmOCR or another configured multimodal endpoint."""
    cfg = ocr_config or {}
    # Only `olm_ocr.debug` controls olm dump files (see `ai_ocr.py` — `ocr.debug` is Paddle-only).
    debug = bool(olm_cfg.get("debug", False))
    tag = datetime.now().strftime("%H%M%S_%f")[:9] if debug else ""

    if debug:
        _save_debug(tag, image, "1_raw")

    processed = _preprocess(image, cfg)

    if debug:
        _save_debug(tag, processed, "2_preprocessed_olm")

    buf = io.BytesIO()
    processed.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    prompt = (olm_cfg.get("prompt") or _DEFAULTS["prompt"]).strip() or _DEFAULTS["prompt"]

    try:
        timeout_sec = int(olm_cfg.get("timeout") or 120)
    except (TypeError, ValueError):
        timeout_sec = 120
    timeout_sec = max(30, timeout_sec)

    temperature = None
    if "temperature" in olm_cfg:
        try:
            temperature = float(olm_cfg["temperature"])
        except (TypeError, ValueError):
            pass

    max_tokens = None
    if "max_tokens" in olm_cfg:
        try:
            max_tokens = int(olm_cfg["max_tokens"])
        except (TypeError, ValueError):
            pass

    # Merge legacy olmocr_local into cfg for URL/model; resolver reads config["olm_ocr"]
    ep = resolve_olm_ocr(config)

    err = vision_chat(
        ep,
        prompt=prompt,
        image_png_bytes=png_bytes,
        timeout=float(timeout_sec),
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if err.startswith("[Error:"):
        err = (
            err.replace("[Error: AI-OCR", "[Error: olmOCR", 1)
            .replace("[Error: Anthropic API not reachable]", "[Error: olmOCR server not reachable]")
            .replace("[Error: AI server not reachable]", "[Error: olmOCR server not reachable]")
        )
        if ep.provider == PROVIDER_OLLAMA and "not reachable" in err.lower():
            err = "[Error: olmOCR — Ollama not reachable (run ollama serve or check the server URL)]"
    return err
