import requests


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

    system_parts = []
    if context.strip():
        system_parts.append(context.strip())
    if memory_pairs:
        lines = ["Past translations for consistency:"]
        for src, tr in memory_pairs:
            lines.append(f'- "{src}" → "{tr}"')
        system_parts.append("\n".join(lines))

    messages = []
    if system_parts:
        messages.append({"role": "system", "content": "\n\n".join(system_parts)})
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
