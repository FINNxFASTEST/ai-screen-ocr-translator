import base64
import io
from datetime import datetime

import requests
from PIL import Image

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
    ocr_config: dict | None = None,
    default_url: str = "http://localhost:12434",
) -> str:
    """Extract text via olmOCR served at an OpenAI-compatible HTTP endpoint (e.g. vLLM/SGLang)."""
    cfg = ocr_config or {}
    debug = bool(olm_cfg.get("debug", False)) or bool(cfg.get("debug", False))
    tag = datetime.now().strftime("%H%M%S_%f")[:9] if debug else ""

    if debug:
        _save_debug(tag, image, "1_raw")

    processed = _preprocess(image, cfg)

    if debug:
        _save_debug(tag, processed, "2_preprocessed_olm")

    buf = io.BytesIO()
    processed.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    raw_base = str(olm_cfg.get("url") or "").strip().rstrip("/")
    base = raw_base if raw_base else str(default_url or "").strip().rstrip("/")
    model = (olm_cfg.get("model") or _DEFAULTS["model"]).strip() or _DEFAULTS["model"]
    prompt = (olm_cfg.get("prompt") or _DEFAULTS["prompt"]).strip() or _DEFAULTS["prompt"]

    headers: dict[str, str] = {}
    api_key = str(olm_cfg.get("api_key") or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        timeout_sec = int(olm_cfg.get("timeout") or 120)
    except (TypeError, ValueError):
        timeout_sec = 120
    timeout_sec = max(30, timeout_sec)

    body: dict = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                    },
                ],
            }
        ],
    }
    if "temperature" in olm_cfg:
        try:
            body["temperature"] = float(olm_cfg["temperature"])
        except (TypeError, ValueError):
            pass
    if "max_tokens" in olm_cfg:
        try:
            body["max_tokens"] = int(olm_cfg["max_tokens"])
        except (TypeError, ValueError):
            pass

    try:
        resp = requests.post(
            f"{base}/v1/chat/completions",
            json=body,
            headers=headers or None,
            timeout=timeout_sec,
        )
        if not resp.ok:
            try:
                err_payload = resp.json()
                err = err_payload.get("error") or err_payload
                msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            except Exception:
                msg = resp.text.strip() or resp.reason
            return f"[Error: olmOCR {resp.status_code}: {msg}]"
        return resp.json()["choices"][0]["message"]["content"].strip()
    except requests.exceptions.ConnectionError:
        return "[Error: olmOCR server not reachable]"
    except requests.exceptions.Timeout:
        return "[Error: olmOCR timed out]"
    except Exception as e:
        return f"[Error: {e}]"
