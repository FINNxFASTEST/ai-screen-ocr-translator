import requests


def translate(text: str, ai_url: str, model: str, prompt_template: str = "Translate the following English text to Thai. Reply with only the Thai translation, nothing else.\n\n{text}") -> str:
    """Send text to Docker Model Runner and return Thai translation."""
    if not text.strip():
        return ""

    prompt = prompt_template.format(text=text)

    try:
        response = requests.post(
            f"{ai_url}/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
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
