# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Screen OCR translator for manga. Captures a circular region of the screen, extracts text via OCR, and translates English → Thai using a local Ollama model. Runs entirely locally with no cloud dependencies. **Windows-only** (relies on Win32 API for click-through windows).

## Working Rules For Agents

- Keep changes focused and minimal; prefer small targeted edits over broad refactors.
- Preserve the capture → OCR → translate → popup flow and avoid changing user-facing controls unless explicitly requested.
- Do not introduce cloud/API dependencies; this project is local-first and expects Ollama on localhost.
- Follow existing style in each file; avoid adding new frameworks or large abstractions.
- If adding config options, include sane defaults and document them in `config.json` comments/docs as appropriate.

## Setup & Running

```bash
pip install -r requirements.txt

# In a separate terminal, start Ollama and pull models
ollama serve
ollama pull qwen2.5:7b   # translation model
ollama pull llava:7b     # optional: vision OCR model
```

```bash
python main.py
```

No build step, no test suite, no linter configuration.

## Quick Validation Checklist

After code changes, run at least one quick validation path:

1. Start app with `python main.py`
2. Move mouse and confirm lens follows cursor
3. Middle-click and verify:
   - capture succeeds
   - OCR returns text (or graceful empty result)
   - translation call to Ollama succeeds
   - popup appears and auto-closes
4. If relevant, test hotkey exit (`Ctrl+Shift+Alt+Q` by default)

## Architecture

**Pipeline triggered on middle mouse click:**

```
capture.py → ocr_engine.py (or ai_ocr.py) → translator.py → popup.py
```

1. **Capture** (`capture.py`) — Screenshots a circular region around the cursor using `mss`, masks outside pixels to white
2. **OCR** (`ocr_engine.py`) — EasyOCR with image preprocessing (2× upscale, grayscale, median filter, Otsu binarization, contrast/sharpness boost, ALL-CAPS normalization for manga text); saves debug images to `debug/` when enabled
3. **AI OCR fallback** (`ai_ocr.py`) — Sends image to Ollama vision model (llava:7b); uses same preprocessing
4. **Translate** (`translator.py`) — POST to Ollama HTTP API at `localhost:11434`
5. **Display** (`popup.py`) — Transparent Tkinter overlay showing original + translation, auto-closes after configurable timeout

**Supporting components:**
- `lens.py` — Transparent circular overlay that follows the cursor; made click-through via `ctypes.windll` (WS_EX_LAYERED + WS_EX_TRANSPARENT)
- `exit_button.py` — Optional draggable exit button overlay
- `spinner.py` — CLI spinner shown during pipeline execution
- `main.py` — `App` class that wires listeners (pynput) and threads; all blocking work runs on daemon threads to keep Tkinter responsive

## File-Level Notes

- `main.py`: event wiring and thread orchestration; keep UI thread responsive.
- `lens.py` / `popup.py` / `exit_button.py`: Win32/Tkinter overlay behavior; be careful with click-through flags and focus handling.
- `capture.py`: region capture + masking; maintain lens radius semantics.
- `ocr_engine.py`: primary OCR path with preprocessing.
- `ai_ocr.py`: optional vision-based OCR fallback via Ollama.
- `translator.py`: translation API client; handle timeouts/errors clearly for user feedback.

## Configuration

All behavior is controlled by `config.json`:
- `model` / `ollama_url` — translation model and endpoint
- `lens_radius`, `lens_color`, `lens_border` — UI appearance
- `upscale_factor`, `contrast_factor`, `sharpness_factor`, `binarize` — OCR image preprocessing
- `ai_ocr` block — enable vision model fallback and custom prompt
- `hotkey_exit` — quit shortcut (default `<ctrl>+<shift>+<alt>+q`)
- `auto_close_ms` — popup duration
- `debug` — saves intermediate images to `debug/` for OCR troubleshooting

## Common Pitfalls

- Ollama not running (`localhost:11434` unreachable) causes translation/vision failures.
- EasyOCR first run can be slow due to model initialization.
- Win32 click-through behavior can break if layered/transparent styles are changed incorrectly.
- Heavy synchronous work on Tkinter/main thread can freeze overlays.

## Controls

| Input | Action |
|-------|--------|
| Mouse move | Lens follows cursor |
| Left Shift + Scroll | Resize lens (50–400 px, 20 px steps) |
| Middle click | Run capture → OCR → translate → popup |
| Escape / click popup | Dismiss popup |
| Ctrl+Shift+Alt+Q | Quit (configurable) |
