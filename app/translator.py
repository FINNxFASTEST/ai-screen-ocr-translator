import requests

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
    ai_url: str,
    model: str,
    prompt_template: str = "Translate the following English text to Thai. Reply with only the Thai translation, nothing else.\n\n{text}",
    context: str = "",
    memory_pairs: list[tuple[str, str]] | None = None,
) -> str:
    if not text.strip():
        return ""

    prompt = prompt_template.format(text=text)

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

    try:
        response = requests.post(
            f"{ai_url}/v1/chat/completions",
            json={
                "model": model,
                "messages": messages,
            },
            timeout=60,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
    except requests.exceptions.ConnectionError:
        return "[Error: Docker Model Runner not running]"
    except requests.exceptions.Timeout:
        return "[Error: Translation timed out]"
    except Exception as e:
        return f"[Error: {e}]"
