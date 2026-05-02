"""Translation language labels and prompt formatting (source/target)."""

from __future__ import annotations

DEFAULT_SOURCE_LANG = "English"
DEFAULT_TARGET_LANG = "Thai"

DEFAULT_TRANSLATE_PROMPT = (
    "Translate the following {source_lang} text to {target_lang}. "
    "Reply with only the {target_lang} translation, nothing else.\n\n{text}"
)


def source_target_from_config(config: dict) -> tuple[str, str]:
    t = config.get("translate") or {}
    src = str(t.get("source_lang") or DEFAULT_SOURCE_LANG).strip() or DEFAULT_SOURCE_LANG
    tgt = str(t.get("target_lang") or DEFAULT_TARGET_LANG).strip() or DEFAULT_TARGET_LANG
    return src, tgt


def format_translate_prompt(
    template: str,
    text: str,
    source_lang: str,
    target_lang: str,
) -> str:
    tpl = (template or "").strip() or DEFAULT_TRANSLATE_PROMPT
    return tpl.format(text=text, source_lang=source_lang, target_lang=target_lang)


def task_preamble(source_lang: str, target_lang: str) -> str:
    return (
        f"Task: The user message is ONE short {source_lang} fragment (comic/UI line). "
        f"Reply with only the {target_lang} translation of that fragment — roughly matching how long the source is. "
        "Do not summarize, retell, or translate long background blocks below; those are reference for names/terms only. "
        "Do not continue a story or add explanations."
    )


def memory_hint_header(source_lang: str) -> str:
    return (
        f"Style hints only (earlier comic lines; translate only the user message ({source_lang}), "
        "do not treat hints as something to reproduce in full):"
    )
