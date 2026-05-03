import io
from datetime import datetime

from PIL import Image

from app.ai_integration import PROVIDER_DOCKER, PROVIDER_OLLAMA, resolve_ai_ocr, vision_chat
from app.ocr_engine import _OCR_DEFAULTS, _fix_case, _join_lines, _preprocess, _save_debug, _segment_words

# Default vision OCR image on Docker Model Runner (multimodal). Text-only hub builds lack mmproj.
AI_VISION_MODEL_DEFAULT = "docker.io/ai/gemma4:4B"

_DEFAULTS = {
    "model": AI_VISION_MODEL_DEFAULT,
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
    # Only `ai_ocr.debug` controls AI Vision dump files (OCR-tab `ocr.debug` is for PaddleOCR).
    debug = bool(ai_ocr_config.get("debug", False))
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

    raw = vision_chat(ep, prompt=prompt, image_png_bytes=png_bytes, timeout=60)
    if raw.startswith("[Error:"):
        low = raw.lower()
        if ep.provider == PROVIDER_DOCKER and "not reachable" in low:
            return "[Error: Docker Model Runner not running]"
        if ep.provider == PROVIDER_OLLAMA and "not reachable" in low:
            return "[Error: Ollama not reachable — run ollama serve or check http://localhost:11434]"
        return raw

    # Apply the same post-processing as PaddleOCR: join lines, fix case, segment words.
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    text = _join_lines(lines) if lines else raw.strip()
    if cfg.get("fix_case", _OCR_DEFAULTS["fix_case"]):
        text = _fix_case(text)
    if cfg.get("word_segment", _OCR_DEFAULTS["word_segment"]):
        text = _segment_words(text)
    return text
