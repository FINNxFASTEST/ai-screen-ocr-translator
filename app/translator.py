from app.ai_integration import PROVIDER_DOCKER, PROVIDER_NLLB, PROVIDER_OLLAMA, ResolvedEndpoint, chat_complete
from app.lang_prefs import (
    DEFAULT_SOURCE_LANG,
    DEFAULT_TARGET_LANG,
    DEFAULT_TRANSLATE_PROMPT,
    format_translate_prompt,
    memory_hint_header,
    task_preamble,
)

_MAX_SERIES_CONTEXT_CHARS = 12000
_MAX_HINT_SOURCE_CHARS = 180
_MAX_HINT_TRANS_CHARS = 280

_CONTEXT_WRAP = (
    "Series reference only (terminology/glossary — not the line to translate; do not output this as your answer):\n"
)


def _ellipsize(s: str, max_chars: int) -> str:
    s = (s or "").strip()
    if len(s) <= max_chars:
        return s
    if max_chars < 2:
        return s[:max_chars]
    return s[: max_chars - 1].rstrip() + "…"


def translate(
    text: str,
    endpoint: ResolvedEndpoint,
    prompt_template: str = DEFAULT_TRANSLATE_PROMPT,
    context: str = "",
    memory_pairs: list[tuple[str, str]] | None = None,
    *,
    lean: bool = False,
    source_lang: str = DEFAULT_SOURCE_LANG,
    target_lang: str = DEFAULT_TARGET_LANG,
    debug: bool = False,
) -> str:
    if not text.strip():
        return ""

    src = (source_lang or DEFAULT_SOURCE_LANG).strip() or DEFAULT_SOURCE_LANG
    tgt = (target_lang or DEFAULT_TARGET_LANG).strip() or DEFAULT_TARGET_LANG
    preamble = task_preamble(src, tgt)
    prompt = format_translate_prompt(prompt_template, text, src, tgt)

    # Lean: same user `{text}` prompt as full mode + same task preamble only — no series context or memory hints.
    # (Sending user-only caused overly literal Thai, e.g. "I see" → "ฉันเห็น", because the preamble steers comic/UI tone.)
    if lean:
        messages = [
            {"role": "system", "content": preamble},
            {"role": "user", "content": prompt},
        ]
        timeout = 45
    else:
        blocks: list[str] = [preamble]
        ctx = context.strip()
        if ctx:
            blocks.append(_CONTEXT_WRAP + _ellipsize(ctx, _MAX_SERIES_CONTEXT_CHARS))
        if memory_pairs:
            lines = [memory_hint_header(src)]
            for src, tr in memory_pairs:
                src_e = _ellipsize(src, _MAX_HINT_SOURCE_CHARS)
                tr_e = _ellipsize(tr, _MAX_HINT_TRANS_CHARS)
                lines.append(f'- "{src_e}" → "{tr_e}"')
            blocks.append("\n".join(lines))

        messages = [{"role": "system", "content": "\n\n".join(blocks)}]
        messages.append({"role": "user", "content": prompt})
        timeout = 60

    out = chat_complete(endpoint, messages, timeout=timeout, debug=debug)
    if out.startswith("[Error:"):
        low = out.lower()
        if endpoint.provider == PROVIDER_DOCKER and (
            "not reachable" in low or "connection" in low
        ):
            return "[Error: Docker Model Runner not running]"
        if endpoint.provider == PROVIDER_OLLAMA and (
            "not reachable" in low or "connection" in low
        ):
            return "[Error: Ollama not reachable — run ollama serve or check http://localhost:11434]"
        if endpoint.provider == PROVIDER_NLLB and (
            "not reachable" in low or "connection" in low
        ):
            return "[Error: NLLB server not running — docker compose -f docker-compose.nllb.yml up -d]"
    return out
