"""olmOCR against a local OpenAI-compatible server using the official YAML v4 chat format."""

# Prompt text aligns with allenai/olmocr (Apache-2.0) build_no_anchoring_v4_yaml_prompt().
import base64
import io
from datetime import datetime

import requests
from PIL import Image

from app.ocr_engine import _preprocess, _save_debug

_FALLBACK_V4_PROMPT = (
    "Attached is one page of a document that you must process. "
    "Just return the plain text representation of this document as if you were reading it naturally. "
    "Convert equations to LateX and tables to HTML.\n"
    "If there are any figures or charts, label them with the following markdown syntax "
    "![Alt text describing the contents of the figure](page_startx_starty_width_height.png)\n"
    "Return your output as markdown, with a front matter section on top specifying values for the "
    "primary_language, is_rotation_valid, rotation_correction, is_table, and is_diagram parameters."
)

_DEFAULTS = {
    # olmocr pipeline default `--port` for embedded vLLM; use `--server URL` when running vLLM separately.
    "url": "http://127.0.0.1:30024",
    "model": "allenai/olmOCR-2-7B-1025-FP8",
    "temperature": 0.1,
    "max_tokens": 8000,
    "timeout": 300,
}


def _v4_yaml_user_prompt() -> str:
    try:
        from olmocr.prompts import build_no_anchoring_v4_yaml_prompt

        return build_no_anchoring_v4_yaml_prompt()
    except Exception:
        return _FALLBACK_V4_PROMPT


try:
    import yaml as _yaml
except ImportError:
    _yaml = None


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _coerce_choice_content(raw) -> str:
    """OpenAI-compatible APIs may return string or multimodal parts list."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        parts = []
        for block in raw:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(str(block.get("text") or ""))
                elif block.get("type") == "image_url":
                    continue
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(raw)


def _strip_optional_code_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        nl = t.find("\n")
        if nl != -1:
            t = t[nl + 1 :].strip()
        if t.endswith("```"):
            t = t[: t.rfind("```")].strip()
    return t


def _natural_text_from_yaml_markdown(content: str) -> tuple[str, str]:
    """Return (extracted_plain_text_or_empty, full_normalized_content_for_fallback).

    olmocr puts readable text in the markdown body below the closing ``---`; some stacks
    or models omit the body and set ``natural_text`` only inside the YAML—we load that when possible.
    """
    c = _normalize_newlines(content.strip())
    if not c:
        return "", ""
    if not c.startswith("---"):
        un = _strip_optional_code_fence(c)
        return un, un

    # Front matter delimiter: --- then newline-ish (already normalized).
    inner_start = None
    if c.startswith("---\n"):
        inner_start = 4
    elif c.startswith("--- "):
        inner_start = c.find("\n") + 1 if "\n" in c else len(c)

    if inner_start is None:
        un = _strip_optional_code_fence(c)
        return un, un

    end_index = c.find("\n---", inner_start)
    if end_index == -1:
        un = _strip_optional_code_fence(c)
        return un, un

    fm_yaml = c[inner_start:end_index].strip()
    body = _strip_optional_code_fence(c[end_index + 4 :].strip())

    if body:
        return body, c

    if _yaml is not None and fm_yaml:
        try:
            data = _yaml.safe_load(fm_yaml)
            if isinstance(data, dict):
                nt = data.get("natural_text")
                if isinstance(nt, str) and nt.strip():
                    return nt.strip(), c
        except Exception:
            pass

    return "", c


def _text_from_completion_json(data: dict) -> tuple[str | None, str]:
    """(error_message_if_any, text)."""
    choices = data.get("choices")
    if not choices:
        return "no choices in response", ""
    msg = choices[0].get("message") if isinstance(choices[0], dict) else {}
    raw = msg.get("content") if isinstance(msg, dict) else None
    return None, _coerce_choice_content(raw)


def extract_text_olmocr_local(
    image: Image.Image,
    local_cfg: dict,
    ocr_config: dict | None = None,
    default_url: str = "http://localhost:12434",
) -> str:
    """Call local vLLM/SGLang (OpenAI-compatible) with olmOCR-style YAML output; parsed body → plain-ish text."""
    cfg = ocr_config or {}
    # Match other engines: OCR tab "preprocess debug" applies; engine-specific checkbox too.
    debug = bool(local_cfg.get("debug", False)) or bool(cfg.get("debug", False))
    tag = datetime.now().strftime("%H%M%S_%f")[:9] if debug else ""

    # Save raw BEFORE preprocess — _preprocess can raise; otherwise no PNGs appeared to "crash before debug".
    if debug:
        _save_debug(tag, image, "1_raw")

    processed = _preprocess(image, cfg)

    if debug:
        _save_debug(tag, processed, "2_preprocessed_olmocr_local")

    buf = io.BytesIO()
    processed.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    raw_base = str(local_cfg.get("url") or "").strip().rstrip("/")
    base = raw_base if raw_base else str(default_url or "").strip().rstrip("/")
    model = (local_cfg.get("model") or _DEFAULTS["model"]).strip() or _DEFAULTS["model"]

    temperature = local_cfg.get("temperature", _DEFAULTS["temperature"])
    try:
        temperature = float(temperature)
    except (TypeError, ValueError):
        temperature = float(_DEFAULTS["temperature"])

    max_tokens = local_cfg.get("max_tokens", _DEFAULTS["max_tokens"])
    try:
        max_tokens = int(max_tokens)
    except (TypeError, ValueError):
        max_tokens = int(_DEFAULTS["max_tokens"])

    custom = str(local_cfg.get("prompt") or "").strip()
    prompt = custom if custom else _v4_yaml_user_prompt()

    headers = {}
    api_key = str(local_cfg.get("api_key") or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    body = {
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
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    try:
        to = local_cfg.get("timeout", _DEFAULTS["timeout"])
        try:
            timeout_sec = max(30, int(to))
        except (TypeError, ValueError):
            timeout_sec = int(_DEFAULTS["timeout"])
        resp = requests.post(
            f"{base}/v1/chat/completions",
            json=body,
            headers=headers or None,
            timeout=timeout_sec,
        )
        if not resp.ok:
            try:
                j = resp.json()
                err = j.get("error") or j
                msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            except Exception:
                msg = resp.text.strip() or resp.reason
            return f"[Error: olmOCR-local {resp.status_code}: {msg}]"
        try:
            payload = resp.json()
        except Exception:
            return f"[Error: olmOCR-local invalid JSON: {resp.text[:200]}]"
        cerr, stripped = _text_from_completion_json(payload)
        if cerr:
            return f"[Error: olmOCR-local {cerr}]"
        stripped = stripped.strip()
        if not stripped:
            return ""

        fenced = _strip_optional_code_fence(stripped)
        extracted, normalized = _natural_text_from_yaml_markdown(fenced)
        if extracted:
            return extracted
        if normalized:
            return normalized
        return fenced
    except requests.exceptions.ConnectionError:
        return "[Error: olmOCR local server not reachable — start vLLM with olmOCR weights (see README / CLAUDE.md)]"
    except requests.exceptions.Timeout:
        return "[Error: olmOCR local timed out]"
    except Exception as e:
        return f"[Error: {e}]"
