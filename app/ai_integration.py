"""Resolve AI endpoints (Docker, OpenAI, Anthropic, Ollama local, OpenAI-compatible) for translation and vision OCR."""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Any

import requests

# Provider ids stored in config
PROVIDER_DOCKER = "docker_local"
PROVIDER_OPENAI = "openai"
PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_COMPAT = "openai_compat"
PROVIDER_OLLAMA = "ollama"
PROVIDER_NLLB = "nllb"
PROVIDER_INHERIT = "inherit"
# Legacy configs used ``llama_local`` — normalized to ``PROVIDER_OLLAMA`` when loading.
LEGACY_PROVIDER_LLAMA_LOCAL = "llama_local"

# Deprecated import name — same as ``PROVIDER_OLLAMA``.
PROVIDER_LLAMA_LOCAL = PROVIDER_OLLAMA

_DEFAULT_OPENAI_BASE = "https://api.openai.com"
_DEFAULT_ANTHROPIC_BASE = "https://api.anthropic.com"
_DEFAULT_OLLAMA_BASE = "http://localhost:11434"
_DEFAULT_NLLB_BASE = "http://localhost:8100"
_DEFAULT_NLLB_MODEL = "nllb-200-1.3B"

_ENV_OPENAI = "OPENAI_API_KEY"
_ENV_ANTHROPIC = "ANTHROPIC_API_KEY"


def _strip_base(url: str) -> str:
    u = (url or "").strip().rstrip("/")
    if u.lower().endswith("/v1"):
        u = u[:-3].rstrip("/")
    return u


def _normalize_openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ensure each message has string content (Anthropic conversion assumes text)."""
    out: list[dict[str, Any]] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if role is None:
            continue
        if isinstance(content, list):
            # Vision-style blocks — keep as-is for OpenAI; translator only sends text.
            out.append({"role": role, "content": content})
        else:
            out.append({"role": role, "content": str(content) if content is not None else ""})
    return out


def _openai_to_anthropic_text(messages: list[dict[str, Any]]) -> tuple[str | None, str]:
    """Split OpenAI-style messages into Anthropic system + single user text."""
    system_parts: list[str] = []
    user_text = ""
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if isinstance(content, list):
            text_bits = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_bits.append(str(block.get("text", "")))
            text = "\n".join(text_bits)
        else:
            text = str(content or "")
        if role == "system":
            system_parts.append(text)
        elif role == "user":
            user_text = text
        elif role == "assistant":
            # Continuation-style prompts are rare; append for safety
            system_parts.append(f"(prior assistant): {text}")
    system = "\n\n".join(system_parts) if system_parts else None
    return system, user_text


@dataclass(frozen=True)
class ResolvedEndpoint:
    """Enough context to call one chat completion."""

    provider: str  # docker_local | ollama | openai | openai_compat | anthropic
    base_url: str  # no trailing /v1
    api_key: str | None
    model: str

    def use_anthropic_messages_api(self) -> bool:
        return self.provider == PROVIDER_ANTHROPIC


def _integration_block(cfg: dict, *path: str) -> dict:
    cur: Any = cfg
    for p in path:
        if not isinstance(cur, dict):
            return {}
        cur = cur.get(p)
    return cur if isinstance(cur, dict) else {}


def _effective_api_key(integration: dict, provider: str, legacy_key: str | None = None) -> str | None:
    raw = str(integration.get("api_key") or "").strip()
    if raw:
        return raw
    env_name = str(integration.get("api_key_env") or "").strip()
    if env_name:
        v = os.environ.get(env_name, "").strip()
        return v or None
    if legacy_key:
        v = str(legacy_key).strip()
        if v:
            return v
    if provider == PROVIDER_OPENAI or provider == PROVIDER_COMPAT:
        v = os.environ.get(_ENV_OPENAI, "").strip()
        return v or None
    if provider == PROVIDER_ANTHROPIC:
        v = os.environ.get(_ENV_ANTHROPIC, "").strip()
        return v or None
    return None


def resolve_translate(config: dict) -> ResolvedEndpoint:
    root_url = _strip_base(str(config.get("ai_url") or "http://localhost:12434"))
    root_model = str(config.get("model") or "").strip()
    ig = _integration_block(config, "translate", "integration")
    provider = str(ig.get("provider") or PROVIDER_DOCKER).strip().lower()
    if provider in ("docker", "local"):
        provider = PROVIDER_DOCKER
    elif provider == LEGACY_PROVIDER_LLAMA_LOCAL:
        provider = PROVIDER_OLLAMA
    override_model = str(ig.get("model") or "").strip()
    model = override_model or root_model

    if provider == PROVIDER_DOCKER:
        return ResolvedEndpoint(
            provider=PROVIDER_DOCKER,
            base_url=root_url,
            api_key=None,
            model=model,
        )

    if provider == PROVIDER_OPENAI:
        base = str(ig.get("base_url") or "").strip() or root_url or _DEFAULT_OPENAI_BASE
        return ResolvedEndpoint(
            provider=PROVIDER_OPENAI,
            base_url=_strip_base(base),
            api_key=_effective_api_key(ig, PROVIDER_OPENAI),
            model=model,
        )

    if provider == PROVIDER_ANTHROPIC:
        base = str(ig.get("base_url") or "").strip() or root_url or _DEFAULT_ANTHROPIC_BASE
        return ResolvedEndpoint(
            provider=PROVIDER_ANTHROPIC,
            base_url=_strip_base(base),
            api_key=_effective_api_key(ig, PROVIDER_ANTHROPIC),
            model=model,
        )

    if provider == PROVIDER_OLLAMA:
        ex = str(ig.get("base_url") or "").strip()
        if ex:
            base = ex
        elif ":11434" in root_url:
            base = root_url
        else:
            base = _DEFAULT_OLLAMA_BASE
        return ResolvedEndpoint(
            provider=PROVIDER_OLLAMA,
            base_url=_strip_base(base),
            api_key=_effective_api_key(ig, PROVIDER_COMPAT),
            model=model,
        )

    if provider == PROVIDER_NLLB:
        base = str(ig.get("base_url") or "").strip() or _DEFAULT_NLLB_BASE
        return ResolvedEndpoint(
            provider=PROVIDER_NLLB,
            base_url=_strip_base(base),
            api_key=None,
            model=model or _DEFAULT_NLLB_MODEL,
        )

    # openai_compat — custom OpenAI-compatible server
    base = str(ig.get("base_url") or "").strip() or root_url
    return ResolvedEndpoint(
        provider=PROVIDER_COMPAT,
        base_url=_strip_base(base),
        api_key=_effective_api_key(ig, PROVIDER_COMPAT),
        model=model,
    )


def resolve_ai_ocr(config: dict) -> ResolvedEndpoint:
    """Vision OCR endpoint (AI Vision engine)."""
    ai_ocr = config.get("ai_ocr") or {}
    ig = ai_ocr.get("integration") or {}
    provider = str(ig.get("provider") or PROVIDER_INHERIT).strip().lower()
    if provider == LEGACY_PROVIDER_LLAMA_LOCAL:
        provider = PROVIDER_OLLAMA
    vision_model = str(ai_ocr.get("model") or "").strip()
    root_url = _strip_base(str(config.get("ai_url") or "http://localhost:12434"))

    if provider in ("", PROVIDER_INHERIT, "same", "same_as_translate"):
        tr = resolve_translate(config)
        om = str(ig.get("model") or "").strip()
        model = om or vision_model or tr.model
        return ResolvedEndpoint(
            provider=tr.provider,
            base_url=tr.base_url,
            api_key=tr.api_key,
            model=model,
        )

    if provider in ("docker", "local"):
        provider = PROVIDER_DOCKER

    override_model = str(ig.get("model") or "").strip()
    model = override_model or vision_model

    if provider == PROVIDER_DOCKER:
        base = str(ig.get("base_url") or "").strip() or root_url
        return ResolvedEndpoint(
            provider=PROVIDER_DOCKER,
            base_url=_strip_base(base),
            api_key=None,
            model=model,
        )

    if provider == PROVIDER_OPENAI:
        base = str(ig.get("base_url") or "").strip() or root_url or _DEFAULT_OPENAI_BASE
        return ResolvedEndpoint(
            provider=PROVIDER_OPENAI,
            base_url=_strip_base(base),
            api_key=_effective_api_key(ig, PROVIDER_OPENAI, ai_ocr.get("api_key")),
            model=model,
        )

    if provider == PROVIDER_ANTHROPIC:
        base = str(ig.get("base_url") or "").strip() or root_url or _DEFAULT_ANTHROPIC_BASE
        return ResolvedEndpoint(
            provider=PROVIDER_ANTHROPIC,
            base_url=_strip_base(base),
            api_key=_effective_api_key(ig, PROVIDER_ANTHROPIC, ai_ocr.get("api_key")),
            model=model,
        )

    if provider == PROVIDER_OLLAMA:
        ex = str(ig.get("base_url") or "").strip()
        if ex:
            base = ex
        elif ":11434" in root_url:
            base = root_url
        else:
            base = _DEFAULT_OLLAMA_BASE
        return ResolvedEndpoint(
            provider=PROVIDER_OLLAMA,
            base_url=_strip_base(base),
            api_key=_effective_api_key(ig, PROVIDER_COMPAT, ai_ocr.get("api_key")),
            model=model,
        )

    base = str(ig.get("base_url") or "").strip() or root_url
    return ResolvedEndpoint(
        provider=PROVIDER_COMPAT,
        base_url=_strip_base(base),
        api_key=_effective_api_key(ig, PROVIDER_COMPAT, ai_ocr.get("api_key")),
        model=model,
    )


def resolve_olm_ocr(config: dict) -> ResolvedEndpoint:
    """olmOCR HTTP endpoint."""
    olm = config.get("olm_ocr") or {}
    ig = olm.get("integration") or {}
    provider = str(ig.get("provider") or PROVIDER_COMPAT).strip().lower()
    if provider == LEGACY_PROVIDER_LLAMA_LOCAL:
        provider = PROVIDER_OLLAMA
    olm_model = str(olm.get("model") or "").strip()
    root_url = _strip_base(str(config.get("ai_url") or "http://localhost:12434"))
    olm_url = _strip_base(str(olm.get("url") or ""))

    if provider in ("", PROVIDER_INHERIT, "same", "same_as_translate"):
        tr = resolve_translate(config)
        om = str(ig.get("model") or "").strip()
        model = om or olm_model or tr.model
        return ResolvedEndpoint(
            provider=tr.provider,
            base_url=tr.base_url,
            api_key=tr.api_key,
            model=model,
        )

    if provider in ("docker", "local"):
        provider = PROVIDER_DOCKER

    override_model = str(ig.get("model") or "").strip()
    model = override_model or olm_model

    if provider == PROVIDER_DOCKER:
        base = olm_url or root_url
        return ResolvedEndpoint(
            provider=PROVIDER_DOCKER,
            base_url=_strip_base(base),
            api_key=None,
            model=model,
        )

    if provider == PROVIDER_OPENAI:
        base = str(ig.get("base_url") or "").strip() or root_url or _DEFAULT_OPENAI_BASE
        return ResolvedEndpoint(
            provider=PROVIDER_OPENAI,
            base_url=_strip_base(base),
            api_key=_effective_api_key(ig, PROVIDER_OPENAI, olm.get("api_key")),
            model=model,
        )

    if provider == PROVIDER_ANTHROPIC:
        base = str(ig.get("base_url") or "").strip() or root_url or _DEFAULT_ANTHROPIC_BASE
        return ResolvedEndpoint(
            provider=PROVIDER_ANTHROPIC,
            base_url=_strip_base(base),
            api_key=_effective_api_key(ig, PROVIDER_ANTHROPIC, olm.get("api_key")),
            model=model,
        )

    if provider == PROVIDER_OLLAMA:
        ex = str(ig.get("base_url") or "").strip()
        if ex:
            base = ex
        elif olm_url and ":11434" in olm_url:
            base = olm_url
        else:
            base = _DEFAULT_OLLAMA_BASE
        return ResolvedEndpoint(
            provider=PROVIDER_OLLAMA,
            base_url=_strip_base(base),
            api_key=_effective_api_key(ig, PROVIDER_COMPAT, olm.get("api_key")),
            model=model,
        )

    base = str(ig.get("base_url") or "").strip() or olm_url or root_url
    return ResolvedEndpoint(
        provider=PROVIDER_COMPAT,
        base_url=_strip_base(base),
        api_key=_effective_api_key(ig, PROVIDER_COMPAT, olm.get("api_key")),
        model=model,
    )


def chat_complete(
    endpoint: ResolvedEndpoint,
    messages: list[dict[str, Any]],
    *,
    timeout: float,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """Returns model text or a user-facing ``[Error: …]`` string."""
    messages = _normalize_openai_messages(messages)
    if endpoint.use_anthropic_messages_api():
        return _anthropic_chat(endpoint, messages, timeout=timeout, max_tokens=max_tokens)
    return _openai_compatible_chat(
        endpoint,
        messages,
        timeout=timeout,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def vision_chat(
    endpoint: ResolvedEndpoint,
    *,
    prompt: str,
    image_png_bytes: bytes,
    timeout: float,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """Single-turn vision: prompt + one PNG image."""
    b64 = base64.b64encode(image_png_bytes).decode("utf-8")
    if endpoint.use_anthropic_messages_api():
        return _anthropic_vision(endpoint, prompt, b64, timeout=timeout, max_tokens=max_tokens)
    return _openai_compatible_vision(
        endpoint,
        prompt,
        b64,
        timeout=timeout,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _headers_openai(endpoint: ResolvedEndpoint) -> dict[str, str]:
    h: dict[str, str] = {}
    if endpoint.api_key:
        h["Authorization"] = f"Bearer {endpoint.api_key}"
    return h


def _openai_compatible_chat(
    endpoint: ResolvedEndpoint,
    messages: list[dict[str, Any]],
    *,
    timeout: float,
    temperature: float | None,
    max_tokens: int | None,
) -> str:
    url = f"{endpoint.base_url}/v1/chat/completions"
    body: dict[str, Any] = {
        "model": endpoint.model,
        "messages": messages,
    }
    if temperature is not None:
        body["temperature"] = temperature
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    try:
        r = requests.post(url, json=body, headers=_headers_openai(endpoint) or None, timeout=timeout)
        if not r.ok:
            try:
                err = r.json().get("error") or {}
                msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            except Exception:
                msg = r.text.strip() or r.reason
            return f"[Error: HTTP {r.status_code}: {msg}]"
        data = r.json()
        return str(data["choices"][0]["message"]["content"] or "").strip()
    except requests.exceptions.ConnectionError:
        return "[Error: AI server not reachable]"
    except requests.exceptions.Timeout:
        return "[Error: Request timed out]"
    except Exception as e:
        return f"[Error: {e}]"


def _openai_compatible_vision(
    endpoint: ResolvedEndpoint,
    prompt: str,
    image_b64: str,
    *,
    timeout: float,
    temperature: float | None,
    max_tokens: int | None,
) -> str:
    url = f"{endpoint.base_url}/v1/chat/completions"
    body: dict[str, Any] = {
        "model": endpoint.model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                ],
            }
        ],
    }
    if temperature is not None:
        body["temperature"] = temperature
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    try:
        r = requests.post(url, json=body, headers=_headers_openai(endpoint) or None, timeout=timeout)
        if not r.ok:
            try:
                err = r.json().get("error") or {}
                msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            except Exception:
                msg = r.text.strip() or r.reason
            return f"[Error: AI-OCR HTTP {r.status_code}: {msg}]"
        data = r.json()
        return str(data["choices"][0]["message"]["content"] or "").strip()
    except requests.exceptions.ConnectionError:
        return "[Error: AI server not reachable]"
    except requests.exceptions.Timeout:
        return "[Error: AI-OCR timed out]"
    except Exception as e:
        return f"[Error: {e}]"


def _anthropic_chat(
    endpoint: ResolvedEndpoint,
    messages: list[dict[str, Any]],
    *,
    timeout: float,
    max_tokens: int | None,
) -> str:
    if not endpoint.api_key:
        return "[Error: Anthropic API key missing — set it in Settings or ANTHROPIC_API_KEY]"
    system, user_text = _openai_to_anthropic_text(messages)
    if not user_text.strip():
        return "[Error: No user message for Anthropic]"
    mt = max_tokens if max_tokens is not None else 1024
    mt = max(256, min(mt, 8192))
    url = f"{endpoint.base_url}/v1/messages"
    body: dict[str, Any] = {
        "model": endpoint.model,
        "max_tokens": mt,
        "messages": [{"role": "user", "content": user_text}],
    }
    if system:
        body["system"] = system
    headers = {
        "x-api-key": endpoint.api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    try:
        r = requests.post(url, json=body, headers=headers, timeout=timeout)
        if not r.ok:
            try:
                err = r.json().get("error") or {}
                msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            except Exception:
                msg = r.text.strip() or r.reason
            return f"[Error: Anthropic HTTP {r.status_code}: {msg}]"
        data = r.json()
        blocks = data.get("content") or []
        parts = []
        for b in blocks:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(str(b.get("text", "")))
        return "\n".join(parts).strip()
    except requests.exceptions.ConnectionError:
        return "[Error: Anthropic API not reachable]"
    except requests.exceptions.Timeout:
        return "[Error: Request timed out]"
    except Exception as e:
        return f"[Error: {e}]"


def _anthropic_vision(
    endpoint: ResolvedEndpoint,
    prompt: str,
    image_b64: str,
    *,
    timeout: float,
    max_tokens: int | None,
) -> str:
    if not endpoint.api_key:
        return "[Error: Anthropic API key missing — set it in Settings or ANTHROPIC_API_KEY]"
    mt = max_tokens if max_tokens is not None else 4096
    mt = max(256, min(mt, 8192))
    url = f"{endpoint.base_url}/v1/messages"
    body = {
        "model": endpoint.model,
        "max_tokens": mt,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }
    headers = {
        "x-api-key": endpoint.api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    try:
        r = requests.post(url, json=body, headers=headers, timeout=timeout)
        if not r.ok:
            try:
                err = r.json().get("error") or {}
                msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            except Exception:
                msg = r.text.strip() or r.reason
            return f"[Error: AI-OCR HTTP {r.status_code}: {msg}]"
        data = r.json()
        blocks = data.get("content") or []
        parts = []
        for b in blocks:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(str(b.get("text", "")))
        return "\n".join(parts).strip()
    except requests.exceptions.ConnectionError:
        return "[Error: Anthropic API not reachable]"
    except requests.exceptions.Timeout:
        return "[Error: AI-OCR timed out]"
    except Exception as e:
        return f"[Error: {e}]"


def ping_translate(endpoint: ResolvedEndpoint) -> tuple[bool, str]:
    """Light reachability check for the floating bar."""
    if endpoint.use_anthropic_messages_api():
        if not endpoint.api_key:
            return False, "No API key"
        url = f"{endpoint.base_url}/v1/models"
        headers = {
            "x-api-key": endpoint.api_key,
            "anthropic-version": "2023-06-01",
        }
        try:
            r = requests.get(url, headers=headers, timeout=8)
            if r.ok:
                return True, "OK (Anthropic)"
            return False, f"HTTP {r.status_code}"
        except requests.exceptions.ConnectionError:
            return False, "Cannot connect"
        except requests.exceptions.Timeout:
            return False, "Timed out"
        except Exception as e:
            return False, str(e)[:120]

    headers = _headers_openai(endpoint)
    url = f"{endpoint.base_url}/v1/models"
    try:
        r = requests.get(url, headers=headers or None, timeout=8)
        if not r.ok:
            # Some proxies return 404 on /v1/models — try minimal completion if Bearer set
            if endpoint.api_key and r.status_code in (401, 404):
                return _ping_openai_minimal_completion(endpoint)
            return False, f"HTTP {r.status_code}"
        data = r.json()
        n = len(data.get("data") or []) if isinstance(data, dict) else 0
        return True, f"OK ({n} models)" if n else "OK"
    except requests.exceptions.ConnectionError:
        return False, "Cannot connect"
    except requests.exceptions.Timeout:
        return False, "Timed out"
    except Exception as e:
        return False, str(e)[:120]


def _ping_openai_minimal_completion(endpoint: ResolvedEndpoint) -> tuple[bool, str]:
    url = f"{endpoint.base_url}/v1/chat/completions"
    body = {
        "model": endpoint.model or "gpt-4o-mini",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    try:
        r = requests.post(url, json=body, headers=_headers_openai(endpoint), timeout=12)
        if r.ok:
            return True, "OK (chat)"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, str(e)[:120]
