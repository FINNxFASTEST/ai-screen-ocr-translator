"""Short human-readable labels for active OCR engine and translation backend (status UI)."""

from __future__ import annotations

from typing import Any

from app.ai_integration import (
    PROVIDER_ANTHROPIC,
    PROVIDER_COMPAT,
    PROVIDER_DOCKER,
    PROVIDER_OLLAMA,
    PROVIDER_OPENAI,
    resolve_translate,
)

_OCR_KEY_LABEL = {
    "paddleocr": "PaddleOCR",
    "ai_vision": "AI Vision OCR",
    "olm_ocr": "olmOCR",
}

_TRANSLATE_PROVIDER_LABEL = {
    PROVIDER_DOCKER: "Docker Model Runner",
    PROVIDER_OLLAMA: "Ollama",
    PROVIDER_OPENAI: "OpenAI",
    PROVIDER_ANTHROPIC: "Anthropic",
    PROVIDER_COMPAT: "OpenAI-compatible",
}


def effective_ocr_engine_key(config: dict[str, Any]) -> str:
    """Same effective engine as the capture pipeline (see app.main._run_pipeline)."""
    ocr_root = config.get("ocr") or {}
    ai_ocr_cfg = config.get("ai_ocr") or {}
    engine = str(ocr_root.get("engine") or "").strip().lower()
    if engine == "olmocr_local":
        engine = "olm_ocr"
    if not engine:
        engine = "ai_vision" if ai_ocr_cfg.get("enabled", False) else "paddleocr"
    if engine not in ("paddleocr", "ai_vision", "olm_ocr"):
        engine = "paddleocr"
    return engine


def format_pipeline_backend_summary(config: dict[str, Any]) -> str:
    """Multi-line status text: OCR, translation backend, then model id on its own line."""
    ocr_key = effective_ocr_engine_key(config)
    ocr_lab = _OCR_KEY_LABEL.get(ocr_key, ocr_key)
    tr = resolve_translate(config)
    tr_lab = _TRANSLATE_PROVIDER_LABEL.get(tr.provider, tr.provider)
    model = str(tr.model or "").strip()
    lines = [f"OCR: {ocr_lab}", f"Translate: {tr_lab}"]
    if model:
        lines.append(f"Model: {model}")
    return "\n".join(lines)
