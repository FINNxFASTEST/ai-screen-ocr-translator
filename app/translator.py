from app.ai_integration import PROVIDER_DOCKER, PROVIDER_OLLAMA, ResolvedEndpoint, chat_complete

_MAX_SERIES_CONTEXT_CHARS = 12000
_MAX_HINT_SOURCE_CHARS = 180
_MAX_HINT_TRANS_CHARS = 280

_TASK_PREAMBLE = (
    "Task: The user message is ONE short English fragment (comic/UI line). "
    "Reply with only the Thai translation of that fragment — roughly matching how long the English is. "
    "Do not summarize, retell, or translate long background blocks below; those are reference for names/terms only. "
    "Do not continue a story or add explanations."
)

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
    prompt_template: str = "Translate the following English text to Thai. Reply with only the Thai translation, nothing else.\n\n{text}",
    context: str = "",
    memory_pairs: list[tuple[str, str]] | None = None,
    *,
    lean: bool = False,
) -> str:
    if not text.strip():
        return ""

    prompt = prompt_template.format(text=text)

    # Lean: same user `{text}` prompt as full mode + same task preamble only — no series context or memory hints.
    # (Sending user-only caused overly literal Thai, e.g. "I see" → "ฉันเห็น", because the preamble steers comic/UI tone.)
    if lean:
        messages = [
            {"role": "system", "content": _TASK_PREAMBLE},
            {"role": "user", "content": prompt},
        ]
        timeout = 45
    else:
        blocks: list[str] = [_TASK_PREAMBLE]
        ctx = context.strip()
        if ctx:
            blocks.append(_CONTEXT_WRAP + _ellipsize(ctx, _MAX_SERIES_CONTEXT_CHARS))
        if memory_pairs:
            lines = [
                "Style hints only (earlier comic lines; translate only the user message English, "
                "do not treat hints as something to reproduce in full):"
            ]
            for src, tr in memory_pairs:
                src_e = _ellipsize(src, _MAX_HINT_SOURCE_CHARS)
                tr_e = _ellipsize(tr, _MAX_HINT_TRANS_CHARS)
                lines.append(f'- "{src_e}" → "{tr_e}"')
            blocks.append("\n".join(lines))

        messages = [{"role": "system", "content": "\n\n".join(blocks)}]
        messages.append({"role": "user", "content": prompt})
        timeout = 60

    out = chat_complete(endpoint, messages, timeout=timeout)
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
    return out
