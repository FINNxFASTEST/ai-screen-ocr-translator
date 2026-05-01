# Screen OCR Translator

Captures text from your screen using a circular lens, translates English -> Thai via local Docker Model Runner models, and shows the result in a popup.

---

## Requirements

- Python 3.10+
- Docker Desktop with Docker Model Runner enabled

---

## Setup

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Pull required models

You can pull models manually:

```bash
docker model pull docker.io/ai/gemma3:4B-F16
docker model pull docker.io/ai/gemma3n:2B-F16
```

Or use the helper script:

```bat
start.bat
```

---

## Run

```bash
python main.py
```

---

## Controls

| Action | Effect |
|---|---|
| **Move mouse** | Green circle lens follows your cursor |
| **Left Shift + Scroll wheel** | Resize the lens (larger = captures more text) |
| **Middle click** | Capture → OCR → Translate → show popup |
| **Esc** or **click popup** | Dismiss the translation popup |
| **Ctrl+Shift+Alt+Q** (configurable) | Quit via keyboard shortcut |
| **Red Exit button** | Quit via on-screen button (can be hidden in config) |

---

## Configuration (`config.json`)

```json
{
  "capture_hotkey": "middle_click",
  "model": "docker.io/ai/gemma3:4B-F16",
  "ai_url": "http://localhost:12434",
  "lens_radius": 150,
  "lens_color": "#00ff88",
  "lens_border_width": 3,
  "popup_font_size": 14,
  "popup_auto_close_ms": 15000,
  "exit_hotkey": "<ctrl>+<shift>+<alt>+q",
  "ai_ocr": {
    "enabled": true,
    "model": "docker.io/ai/gemma3n:2B-F16"
  }
}
```

| Key | Description |
|---|---|
| `model` | Translation model name |
| `ai_url` | URL of your local model server |
| `lens_radius` | Starting radius of the capture circle (px) |
| `lens_color` | Color of the circle border (hex) |
| `lens_border_width` | Thickness of the circle border (px) |
| `popup_font_size` | Font size of the translation popup |
| `popup_auto_close_ms` | How long the popup stays open (milliseconds) |
| `capture_hotkey` | Mouse token (e.g. `middle_click`) or keyboard chord (same format as other shortcuts); legacy key `hotkey` is still read |
| `exit_hotkey` | Keyboard shortcut to quit (default `"<ctrl>+<shift>+<alt>+q"`) |
| `ai_ocr.enabled` | Enable vision-model OCR before EasyOCR fallback |
| `ai_ocr.model` | Vision OCR model name |
| `show_exit_button` | `true` / `false` — show or hide the red Exit button |

---

## Project Structure

```
manga-translator/
├── app/
│   ├── main.py         # App orchestration and pipeline
│   ├── lens.py         # Circular overlay that follows your mouse
│   ├── capture.py      # Screenshots the lens area
│   ├── ocr_engine.py   # EasyOCR extracts text from image
│   ├── ai_ocr.py       # Vision-model OCR path
│   ├── translator.py   # Sends text to local model API, returns Thai
│   ├── popup.py        # Displays the translation result
│   ├── exit_button.py  # Floating controls (test connection + exit)
│   └── spinner.py      # CLI activity spinner
├── main.py             # Stable entrypoint for local run
├── config.json         # Settings
└── requirements.txt    # Python dependencies
```
