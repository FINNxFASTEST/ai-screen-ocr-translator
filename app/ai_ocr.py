import io
from datetime import datetime

from PIL import Image

from app.ai_integration import PROVIDER_DOCKER, PROVIDER_OLLAMA, resolve_ai_ocr, vision_chat
from app.ocr_engine import _preprocess, _save_debug

_DEFAULTS = {
    # Docker `gemma3n` artifacts are text-only (no mmproj); use `gemma3` for vision.
    "model": "docker.io/ai/gemma3:4B-F16",
    "prompt": (
        "Extract all text from this image exactly as it appears. "
        "Reply with only the extracted text, no explanations, no formatting."
    ),
}


def extract_text_ai(
    image: Image.Image,
    ai_ocr_config: dict,
    ocr_config: dict | None,
    config: dict,
) -> str:
    """Extract text from image using configured vision backend (Docker, OpenAI, Anthropic, etc.)."""
    cfg = ocr_config or {}
    debug = bool(ai_ocr_config.get("debug", False)) or bool(cfg.get("debug", False))
    tag = datetime.now().strftime("%H%M%S_%f")[:9] if debug else ""

    if debug:
        _save_debug(tag, image, "1_raw")

    processed = _preprocess(image, cfg)

    if debug:
        _save_debug(tag, processed, "2_preprocessed_ai")

    buf = io.BytesIO()
    processed.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    ep = resolve_ai_ocr(config)
    prompt = ai_ocr_config.get("prompt", _DEFAULTS["prompt"])

    err = vision_chat(ep, prompt=prompt, image_png_bytes=png_bytes, timeout=60)
    if err.startswith("[Error:"):
        low = err.lower()
        if ep.provider == PROVIDER_DOCKER and "not reachable" in low:
            return "[Error: Docker Model Runner not running]"
        if ep.provider == PROVIDER_OLLAMA and "not reachable" in low:
            return "[Error: Ollama not reachable — run ollama serve or check http://localhost:11434]"
    return err
