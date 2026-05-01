# Screen OCR Translator

Captures text from your screen with a circular or rectangular lens, runs **OCR** (PaddleOCR or a vision HTTP server), translates **English → Thai** via a local **Docker Model Runner** endpoint, and shows the result in a popup.

---

## Requirements

- **Windows** (capture / overlays rely on Win32 APIs)
- **Python 3.10+**
- **Docker Desktop** with **Docker Model Runner** enabled (translation + optional **AI Vision** OCR)

**Optional OCR backends**

- **olmOCR (HTTP)** / **olmOCR (local vLLM)**: OpenAI-compatible server (vLLM, SGLang, etc.). For a ready-made GPU container see [docker-compose.vllm.yml](docker-compose.vllm.yml).

---

## Setup

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Pull translation / vision models (Docker Model Runner)

```bash
docker model pull docker.io/ai/gemma3:4B-F16
```

**AI Vision OCR** (`ocr.engine`: `ai_vision`) expects a **multimodal** Gemma artifact. Hub `gemma3n` builds are often **text-only**; keep the vision model on something like **`docker.io/ai/gemma3:4B-F16`** or **`docker.io/ai/gemma3:4B-Q4_K_M`** (see app settings).

Or use **`start.bat`** if your repo ships it.

### 3. Optional — olmOCR behind vLLM in Docker

The root [docker-compose.yml](docker-compose.yml) is only for **Docker Model Runner**. For **`olmocr_local`** OCR, run vLLM separately:

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

Use **Settings** to edit most values. Important OCR-related keys:

| Key | Description |
|-----|-------------|
| `ocr.engine` | **`paddleocr`** (local PaddleOCR), **`ai_vision`** (Docker vision chat via `ai_url`), **`olm_ocr`** (OpenAI-compatible server + custom prompt), **`olmocr_local`** (same API, AllenAI YAML v4 prompt / parsing for olm-style models). If missing: falls back from `ai_ocr.enabled`. |
| `ocr.*` | Shared image preprocessing (`upscale`, `contrast`, `binarize`, `debug`, etc.). |
| `ai_url` | Docker Model Runner base URL (translation + AI Vision OCR). |
| `model` | Translation model id. |
| `ai_ocr.*` | AI Vision OCR: mirrored **`enabled`** when `ocr.engine` is `ai_vision`; `model`, `prompt`, `debug`. |
| `olm_ocr.*` | URL, model id, prompt, debug for HTTP olm-style servers. |
| `olmocr_local.*` | URL, model id, temperature, `max_tokens`, timeout, optional `api_key`, optional prompt override, debug — for **local vLLM** on `127.0.0.1:30024` (or your port). |

**List models**: In **Settings → OCR**, **List models…** queries `GET /v1/models` on the server URL for AI Vision (**`ai_url`**) / **olm OCR URL** / **olmocr_local URL**.

### Example snippet

```json
{
  "ai_url": "http://localhost:12434",
  "model": "docker.io/ai/gemma3:4B-F16",
  "ocr": {
    "engine": "paddleocr"
  },
  "ai_ocr": {
    "enabled": false,
    "model": "docker.io/ai/gemma3:4B-F16",
    "debug": false
  },
  "olmocr_local": {
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
│   ├── olm_ocr.py        # Generic OpenAI multimodal OCR
│   ├── olmocr_local.py   # olmOCR YAML v4 + local `/v1` server
│   ├── translator.py     # Translate via OpenAI-compatible API
│   ├── popup.py          # Translation popup UI
│   ├── config_panel.py   # F12 settings (incl. OCR engine tabs)
│   ├── memory.py         # Optional SQLite + embedding recall
│   └── ...
├── main.py               # Entry: wizard + app.main.run()
├── docker-compose.yml    # Docker Model Runner (provider entries)
├── docker-compose.vllm.yml  # Optional GPU vLLM for olmOCR-local
├── config.default.json   # Default settings template
├── config.user.json      # Preferred override (if present)
└── requirements.txt
```
