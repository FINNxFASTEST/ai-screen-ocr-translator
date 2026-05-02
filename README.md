# Screen OCR Translator

Captures text from your screen with a circular or rectangular lens, runs **OCR** (PaddleOCR or a vision HTTP server), translates from a **configurable source language** to a **target language** (defaults **English → Thai**) via a local **Docker Model Runner** endpoint, and shows the result in a popup.

## Multi-language translation

**Settings → Translation → Languages** sets the **source (OCR) language** and **target language** (any pair you describe in plain language, e.g. Japanese → English). The translation prompt uses **`{source_lang}`**, **`{target_lang}`**, and **`{text}`** so the model knows what to translate.

For **PaddleOCR**, set **`Paddle language`** on **Settings → OCR** (`ocr.paddle_lang` in config) to the Paddle language code for your script (e.g. `en`, `japan`, `korean`, `ch`). That picks the right recognition model; it is separate from the human-readable source language label used for translation.

**If your on-screen text is not English**, **AI Vision OCR** (`ocr.engine`: **`ai_vision`**) or **olmOCR** (`olm_ocr`) is usually **much better** than PaddleOCR alone. PaddleOCR is a classical pipeline per language code: stylized fonts, furigana, vertical text, and noisy comic panels are easy to misread. **AI Vision** sends the cropped image to a multimodal model that “reads” the pixels and returns text in context, so it generalizes across scripts and layouts without relying on a fixed recognizer tuned mostly for common cases. **olmOCR** (HTTP) follows the same idea on your GPU server. Use Paddle when you want fast local Latin/English-style runs; switch to vision OCR when accuracy on Japanese, Korean, Chinese, or mixed UI matters more.

## How to use

**Before you start:** Install **[Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/)** (required for translation and optional AI Vision OCR). Open Docker Desktop and enable **Docker Model Runner** in its settings. See also [Install Docker Desktop on Windows](https://docs.docker.com/desktop/setup/install/windows-install/) if you need setup help.

From the project folder, run **`start.bat`** (double-click it, or run it in Command Prompt / PowerShell). That launches the app. On first launch, the setup wizard can install Python dependencies and pull Docker models if needed.

---

## Requirements

- **Windows** (capture / overlays rely on Win32 APIs)
- **Python 3.10+**
- **Docker Desktop** (required) — [Download Docker Desktop](https://www.docker.com/products/docker-desktop/) · [Windows install guide](https://docs.docker.com/desktop/setup/install/windows-install/). Enable **Docker Model Runner** in Docker Desktop (translation + optional **AI Vision** OCR).

**Optional OCR backends**

- **olmOCR (HTTP)** (`ocr.engine`: `olm_ocr`): OpenAI-compatible server (vLLM, SGLang, etc.). For a ready-made GPU container see [docker-compose.vllm.yml](docker-compose.vllm.yml).

---

## Setup

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Pull translation / vision models (Docker Model Runner)

```bash
docker model pull docker.io/ai/gemma4:E2B   # translation
docker model pull docker.io/ai/gemma4:4B    # AI Vision OCR
```

**AI Vision OCR** (`ocr.engine`: `ai_vision`) expects a **multimodal** model. Defaults use **`docker.io/ai/gemma4:E2B`** for translation and **`docker.io/ai/gemma4:4B`** for vision OCR. Some hub builds (e.g. certain `gemma3n` variants) are **text-only** — pick a vision-capable artifact in **Settings** if you switch models.

The first-run wizard (when you start via **`start.bat`**) can pull these for you.

### 3. Optional — olmOCR behind vLLM in Docker

The root [docker-compose.yml](docker-compose.yml) is only for **Docker Model Runner**. For **`olm_ocr`** pointing at a local OpenAI-compatible server, you can run vLLM separately:

```bash
docker compose -f docker-compose.vllm.yml pull
docker compose -f docker-compose.vllm.yml up -d
docker compose -f docker-compose.vllm.yml logs -f olmocr-vllm
```

- Listens on **`http://127.0.0.1:30024`** by default.
- Default served name **`olmocr`** — use that as **Model id** unless you changed `OLMOCR_SERVED_NAME`.
- Requires **NVIDIA GPU** + Docker GPU (Windows: Docker Desktop **WSL2** with GPU).

---

## Run

Same as **`start.bat`**:

```bash
python main.py
```

Open **Settings** with **F12** (default) to pick the OCR engine and URLs.

---

## Controls

| Action | Effect |
|--------|--------|
| **Move mouse** | Lens follows your cursor |
| **Modifiers + scroll / hotkeys** | Resize lens (see effective config for `lens_wheel_mod_*`) |
| **Capture hotkey** (default **middle click**) | Capture → OCR → translate → popup |
| **Esc** or **click popup** | Dismiss popup |
| **Exit hotkey** (e.g. **Shift+Q**) | Quit |
| **F12** (default) | Settings |
| **Exit button bar** | Settings / exit (toggle in config) |

---

## Configuration

Effective config file is the **first** that exists:

`config.user.json` → **`config.default.json`** → `config.json`

Use **Settings** to edit most values. Important keys:

| Key | Description |
|-----|-------------|
| `translate.source_lang` / `translate.target_lang` | Human-readable language names for prompts and UI (defaults English / Thai). |
| `translate.prompt` | Template with `{text}` (required) and optional `{source_lang}`, `{target_lang}`. |
| `ocr.engine` | **`paddleocr`** (local PaddleOCR), **`ai_vision`** (Docker vision chat via `ai_url`), **`olm_ocr`** (OpenAI-compatible server + custom prompt). If missing: falls back from `ai_ocr.enabled`. |
| `ocr.paddle_lang` | PaddleOCR language code when using **`paddleocr`** (e.g. `en`, `japan`, `korean`). |
| `ocr.*` | Shared image preprocessing (`upscale`, `contrast`, `binarize`, `debug`, etc.). |
| `ai_url` | Docker Model Runner base URL (translation + AI Vision OCR). |
| `model` | Translation model id. |
| `ai_ocr.*` | AI Vision OCR: mirrored **`enabled`** when `ocr.engine` is `ai_vision`; `model`, `prompt`, `debug`. |
| `olm_ocr.*` | URL, model id, prompt, debug for HTTP olm-style servers; optional `timeout`, `api_key`, `temperature`, `max_tokens` for OpenAI-compatible backends. |

**List models**: In **Settings → OCR**, **List models…** queries `GET /v1/models` on the server URL for AI Vision (**`ai_url`**) / **olm OCR URL**.

### Example snippet

```json
{
  "ai_url": "http://localhost:12434",
  "model": "docker.io/ai/gemma4:E2B",
  "translate": {
    "source_lang": "English",
    "target_lang": "Thai",
    "prompt": "Translate the following {source_lang} text to {target_lang}. Reply with only the {target_lang} translation, nothing else.\n\n{text}"
  },
  "ocr": {
    "engine": "paddleocr",
    "paddle_lang": "en"
  },
  "ai_ocr": {
    "enabled": false,
    "model": "docker.io/ai/gemma4:4B",
    "debug": false
  },
  "olm_ocr": {
    "url": "http://127.0.0.1:30024",
    "model": "olmocr",
    "debug": false
  }
}
```

---

## Project Structure

```
manga-translator/
├── app/
│   ├── main.py           # Pipeline, hotkeys, settings hook
│   ├── lens.py           # Transparent lens overlay
│   ├── capture.py        # Screenshots lens region (mss)
│   ├── ocr_engine.py     # PaddleOCR + shared preprocess/debug
│   ├── ai_ocr.py        # Vision OCR → Docker `/v1/chat/completions`
│   ├── olm_ocr.py        # OpenAI-compatible multimodal OCR (HTTP)
│   ├── translator.py     # Translate via OpenAI-compatible API
│   ├── popup.py          # Translation popup UI
│   ├── config_panel.py   # F12 settings (incl. OCR engine tabs)
│   ├── memory.py         # Optional SQLite + embedding recall
│   └── ...
├── main.py               # Entry: wizard + app.main.run()
├── start.bat             # Windows: runs `python main.py`
├── docker-compose.yml    # Docker Model Runner (provider entries)
├── docker-compose.vllm.yml  # Optional GPU vLLM for olmOCR (HTTP)
├── config.default.json   # Default settings template
├── config.user.json      # Preferred override (if present)
└── requirements.txt
```
