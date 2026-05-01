import base64
import io
from datetime import datetime

import requests
from PIL import Image

from app.ocr_engine import _preprocess, _save_debug

_DEFAULTS = {
    "model": "docker.io/ai/gemma3n:2B-F16",
    "prompt": (
        "Extract all text from this image exactly as it appears. "
        "Reply with only the extracted text, no explanations, no formatting."
    ),
}


def extract_text_ai(
    image: Image.Image,
    ai_ocr_config: dict,
    ocr_config: dict | None = None,
    ai_url: str = "http://localhost:12434",
) -> str:
    """Extract text from image using Docker Model Runner vision model."""
    cfg = ocr_config or {}
    debug = ai_ocr_config.get("debug", False)

    processed = _preprocess(image, cfg)

    if debug:
        tag = datetime.now().strftime("%H%M%S_%f")[:9]
        _save_debug(tag, image, "1_raw")
        _save_debug(tag, processed, "2_preprocessed_ai")

    buf = io.BytesIO()
    processed.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    model = ai_ocr_config.get("model", _DEFAULTS["model"])
    prompt = ai_ocr_config.get("prompt", _DEFAULTS["prompt"])

    try:
        resp = requests.post(
            f"{ai_url}/v1/chat/completions",
            json={
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                        ],
                    }
                ],
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except requests.exceptions.ConnectionError:
        return "[Error: Docker Model Runner not running]"
    except requests.exceptions.Timeout:
        return "[Error: AI-OCR timed out]"
    except Exception as e:
        return f"[Error: {e}]"
