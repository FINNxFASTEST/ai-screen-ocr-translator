# Screen OCR Translator

Captures text from your screen using a circular lens, translates English → Thai via a local Ollama model, and shows the result in a popup.

---

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com) installed and running locally

---

## Setup

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Install and start Ollama

Download Ollama from https://ollama.com then run:

```bash
ollama serve
```

### 3. Pull the translation model

```bash
ollama pull qwen2.5:7b
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
| **Ctrl+Q** (configurable) | Quit via keyboard shortcut |
| **Red Exit button** | Quit via on-screen button (can be hidden in config) |

---

## Configuration (`config.json`)

```json
{
  "hotkey": "middle_click",
  "model": "qwen2.5:7b",
  "ollama_url": "http://localhost:11434",
  "lens_radius": 150,
  "lens_color": "#00ff88",
  "lens_border_width": 3,
  "popup_font_size": 14,
  "popup_auto_close_ms": 15000
}
```

| Key | Description |
|---|---|
| `model` | Ollama model name to use for translation |
| `ollama_url` | URL of your local Ollama server |
| `lens_radius` | Starting radius of the capture circle (px) |
| `lens_color` | Color of the circle border (hex) |
| `lens_border_width` | Thickness of the circle border (px) |
| `popup_font_size` | Font size of the translation popup |
| `popup_auto_close_ms` | How long the popup stays open (milliseconds) |
| `exit_hotkey` | Keyboard shortcut to quit (e.g. `"<ctrl>+q"`, `"<ctrl>+<shift>+x"`) |
| `show_exit_button` | `true` / `false` — show or hide the red Exit button |

---

## Project Structure

```
manga-translator/
├── main.py          # Entry point
├── lens.py          # Circular overlay that follows your mouse
├── capture.py       # Screenshots the lens area
├── ocr_engine.py    # EasyOCR extracts text from image
├── translator.py    # Sends text to Ollama, returns Thai
├── popup.py         # Displays the translation result
├── config.json      # Settings
└── requirements.txt # Python dependencies
```
