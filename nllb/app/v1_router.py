"""
OpenAI-compatible /v1 router for NLLB-200.

Model name format:  nllb-200-1.3B                     (uses DEFAULT_SRC → DEFAULT_TGT)
                    nllb-200-1.3B/eng_Latn/tha_Thai    (explicit lang pair)

System message (optional override):
  Plain text:  "Translate from English to Thai"   (fuzzy-matched against language names)
               "Reply with only the Thai translation" + "ONE short English fragment"
  JSON:        {"src_lang": "eng_Latn", "tgt_lang": "tha_Thai"}

User message:
  Raw text OR "Translate the following ... text to ...\n\nACTUAL TEXT" — the router
  strips the instruction prefix and translates only the text after the last blank line.
"""

import json
import re
import time
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from languages import NLLB_LANGUAGES

router = APIRouter(prefix="/v1")

MODEL_SHORT = "nllb-200-1.3B"
DEFAULT_SRC = "eng_Latn"
DEFAULT_TGT = "tha_Thai"

# reverse lookup: lowercase display name → code  (e.g. "thai" → "tha_Thai")
_NAME_TO_CODE: dict[str, str] = {v.lower(): k for k, v in NLLB_LANGUAGES.items()}


# ── helpers ──────────────────────────────────────────────────────────────────

def _parse_model_langs(model: str) -> tuple[str, str]:
    """Extract src/tgt from  'nllb-200-1.3B/eng_Latn/tha_Thai'  or return defaults."""
    parts = model.split("/")
    if len(parts) == 3:
        src, tgt = parts[1], parts[2]
        if src in NLLB_LANGUAGES and tgt in NLLB_LANGUAGES:
            return src, tgt
    return DEFAULT_SRC, DEFAULT_TGT


def _parse_system_langs(system_text: str) -> tuple[str, str] | None:
    """Try to extract lang pair from system message. Returns None if unparseable."""
    # try JSON first
    try:
        data = json.loads(system_text)
        src = data.get("src_lang", "")
        tgt = data.get("tgt_lang", "")
        if src in NLLB_LANGUAGES and tgt in NLLB_LANGUAGES:
            return src, tgt
    except (json.JSONDecodeError, AttributeError):
        pass

    # "Translate from English to Thai" style
    match = re.search(
        r"(?:from|source)[:\s]+([a-zA-Z\s]+?)(?:\s+to|\s+target)[:\s]+([a-zA-Z\s]+)",
        system_text,
        re.IGNORECASE,
    )
    if match:
        src_name = match.group(1).strip().lower()
        tgt_name = match.group(2).strip().lower()
        src_code = _NAME_TO_CODE.get(src_name)
        tgt_code = _NAME_TO_CODE.get(tgt_name)
        if src_code and tgt_code:
            return src_code, tgt_code

    # manga-translator task_preamble format:
    #   "Task: The user message is ONE short English fragment ..."
    #   "Reply with only the Thai translation of that fragment ..."
    tgt_match = re.search(r"Reply with only the ([A-Za-z]+) translation", system_text, re.IGNORECASE)
    if tgt_match:
        tgt_code = _NAME_TO_CODE.get(tgt_match.group(1).lower())
        if tgt_code:
            src_match = re.search(r"ONE short ([A-Za-z]+) fragment", system_text, re.IGNORECASE)
            src_code = _NAME_TO_CODE.get(src_match.group(1).lower()) if src_match else None
            return (src_code or DEFAULT_SRC), tgt_code

    return None


def _extract_user_text(messages: list[dict]) -> str:
    """Return the actual text to translate from user messages.

    The manga-translator prompt template ends with '\n\n{text}', so if the
    user message contains a double-newline we take only the content after the
    last one — that strips the instruction prefix and leaves the raw text.
    """
    parts = [m["content"] for m in messages if m.get("role") == "user"]
    text = "\n".join(parts)
    if "\n\n" in text:
        last_part = text.rsplit("\n\n", 1)[-1].strip()
        if last_part:
            return last_part
    return text


def _openai_message(text: str, model: str) -> dict:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


# ── schemas ───────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = MODEL_SHORT
    messages: list[ChatMessage]
    stream: Optional[bool] = False
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None  # accepted but ignored


# ── endpoints ─────────────────────────────────────────────────────────────────

@router.get("/models")
def list_models():
    """Return all available lang-pair models plus the generic one."""
    models = [
        {
            "id": MODEL_SHORT,
            "object": "model",
            "created": 0,
            "owned_by": "meta",
        }
    ]
    return {"object": "list", "data": models}


@router.get("/models/{model_id:path}")
def get_model(model_id: str):
    return {"id": model_id, "object": "model", "created": 0, "owned_by": "meta"}


@router.post("/chat/completions")
def chat_completions(req: ChatCompletionRequest):
    # import here to avoid circular at module load time
    from main import translator, MAX_LENGTH

    if translator is None:
        raise HTTPException(503, "Model not ready — still loading")

    messages = [m.model_dump() for m in req.messages]

    # determine lang pair: system message wins over model name
    system_msgs = [m["content"] for m in messages if m["role"] == "system"]
    src_lang, tgt_lang = _parse_model_langs(req.model)
    if system_msgs:
        override = _parse_system_langs(system_msgs[0])
        if override:
            src_lang, tgt_lang = override

    text = _extract_user_text(messages)
    if not text.strip():
        raise HTTPException(400, "No user message content to translate")

    max_len = req.max_tokens or MAX_LENGTH
    try:
        result = translator(text, src_lang=src_lang, tgt_lang=tgt_lang, max_length=max_len)
        translated = result[0]["translation_text"]
    except Exception as e:
        raise HTTPException(500, str(e))

    return _openai_message(translated, req.model)
