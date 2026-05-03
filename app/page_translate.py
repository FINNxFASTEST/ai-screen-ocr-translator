"""
Full-page translate pipeline orchestrator.

Supports two entry points:
  - Auto-capture: scroll-and-stitch the foreground window, then OCR + translate.
  - Manual upload: caller provides a PIL Image, skip capture.

After translation, opens a PageViewer window with the stitched image and
translated text drawn over each detected speech bubble.
"""
from __future__ import annotations

import re
import threading
import tkinter as tk
from typing import Callable

from PIL import Image

from app.ai_integration import chat_complete, resolve_translate
from app.lang_prefs import DEFAULT_TRANSLATE_PROMPT, source_target_from_config, task_preamble
from app.series_config import get_active_series_translation
from app.spinner import Spinner


# ---------------------------------------------------------------------------
# Batch translation
# ---------------------------------------------------------------------------

def _parse_numbered_response(response: str, count: int) -> list[str]:
    """
    Parse a response formatted as:
        [1] translated text
        [2] translated text
        ...
    Falls back to empty strings for any missing indices.
    """
    results = [""] * count
    for match in re.finditer(r"\[(\d+)\]\s*(.*?)(?=\[\d+\]|\Z)", response, re.DOTALL):
        idx = int(match.group(1)) - 1
        if 0 <= idx < count:
            results[idx] = match.group(2).strip()
    return results


def _batch_translate(
    texts: list[str],
    config: dict,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[str]:
    """
    Translate all non-empty texts in a single LLM call using a numbered list format.

    Falls back to per-text sequential calls if batch parsing fails.
    """
    src_lang, tgt_lang = source_target_from_config(config)
    endpoint = resolve_translate(config)
    _, context = get_active_series_translation(config)
    translate_cfg = config.get("translate", {})
    quick = bool(translate_cfg.get("quick_translate", False))

    results = [""] * len(texts)

    # Index only non-empty texts so we don't waste tokens
    indexed = [(i, t) for i, t in enumerate(texts) if t.strip()]
    if not indexed:
        return results

    # Build numbered input
    numbered_input = "\n".join(f"[{n + 1}] {t}" for n, (_, t) in enumerate(indexed))

    preamble = task_preamble(src_lang, tgt_lang)
    ctx_block = ""
    if not quick and context.strip():
        ctx_block = (
            "Series reference (terminology/glossary — do not output this):\n"
            + context.strip()[:4000]
            + "\n\n"
        )

    system_msg = (
        f"{preamble}\n\n"
        f"{ctx_block}"
        f"Translate each numbered item below from {src_lang} to {tgt_lang}.\n"
        f"Reply with ONLY the numbered translations, one per line, in the exact format:\n"
        f"[N] translation\n"
        f"Do not add any explanations, headers, or extra text."
    )

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": numbered_input},
    ]

    if progress_callback:
        progress_callback(0, len(indexed))

    response = chat_complete(endpoint, messages, timeout=180)

    if response.startswith("[Error"):
        # Return the error for every slot so the viewer can show it
        return [response] * len(texts)

    parsed = _parse_numbered_response(response, len(indexed))

    # Check if we got reasonable results (at least half filled)
    filled = sum(1 for p in parsed if p)
    if filled < len(indexed) // 2:
        # Fallback: translate one by one
        return _sequential_translate(texts, config, progress_callback)

    for n, (i, _) in enumerate(indexed):
        results[i] = parsed[n]

    if progress_callback:
        progress_callback(len(indexed), len(indexed))

    return results


def _sequential_translate(
    texts: list[str],
    config: dict,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[str]:
    """Translate each text individually — fallback when batch parsing fails."""
    from app.translator import translate

    src_lang, tgt_lang = source_target_from_config(config)
    endpoint = resolve_translate(config)
    translate_cfg = config.get("translate", {})
    prompt_template = translate_cfg.get("prompt", DEFAULT_TRANSLATE_PROMPT)
    quick = bool(translate_cfg.get("quick_translate", False))
    _, context = get_active_series_translation(config)

    results = []
    for i, text in enumerate(texts):
        if not text.strip():
            results.append("")
        else:
            translated = translate(
                text,
                endpoint,
                prompt_template,
                "" if quick else context,
                None,
                lean=quick,
                source_lang=src_lang,
                target_lang=tgt_lang,
            )
            results.append(translated)
        if progress_callback:
            progress_callback(i + 1, len(texts))

    return results


# ---------------------------------------------------------------------------
# Progress window
# ---------------------------------------------------------------------------

class _ProgressWindow:
    """Small non-blocking status window shown during the pipeline."""

    def __init__(self, root: tk.Tk):
        self._win = tk.Toplevel(root)
        self._win.title("Page Translate")
        self._win.resizable(False, False)
        self._win.attributes("-topmost", True)
        self._win.overrideredirect(True)
        self._win.configure(bg="#1e1e1e")

        screen_w = root.winfo_screenwidth()
        self._win.geometry(f"340x70+{screen_w // 2 - 170}+40")

        self._label = tk.Label(
            self._win,
            text="Initialising...",
            bg="#1e1e1e",
            fg="#00e6ff",
            font=("Segoe UI", 11),
            wraplength=320,
            justify="left",
            padx=12,
            pady=14,
        )
        self._label.pack(fill=tk.BOTH, expand=True)

    def update(self, msg: str) -> None:
        try:
            self._label.config(text=msg)
            self._win.update_idletasks()
        except tk.TclError:
            pass

    def close(self) -> None:
        try:
            self._win.destroy()
        except tk.TclError:
            pass


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_page_pipeline(
    root: tk.Tk,
    config: dict,
    image: Image.Image | None = None,
    on_done: Callable | None = None,
    on_error: Callable[[str], None] | None = None,
) -> None:
    """
    Run the full-page translate pipeline on a background thread.

    image=None  → auto-capture by scrolling the foreground window.
    image=<PIL> → skip capture, use provided image (manual upload path).

    Calls on_done() after the viewer opens, on_error(msg) on failure.
    """
    progress_win: list[_ProgressWindow] = []
    spinner = Spinner()

    def _open_progress():
        pw = _ProgressWindow(root)
        progress_win.append(pw)

    def _set_progress(msg: str):
        spinner.update(msg)
        if progress_win:
            root.after(0, lambda m=msg: progress_win[0].update(m))

    root.after(0, _open_progress)

    def _worker():
        try:
            page_image: Image.Image

            # ── Step 1: Capture ──────────────────────────────────────────
            if image is None:
                spinner.start("Scrolling page...")
                _set_progress("Scrolling page to capture...")

                from app.page_capture import capture_full_page

                def _cap_progress(step, msg):
                    _set_progress(msg)

                page_image = capture_full_page(progress_callback=_cap_progress)
            else:
                spinner.start("Loading image...")
                _set_progress("Loading uploaded image...")
                page_image = image

            # ── Step 2: OCR ───────────────────────────────────────────────
            _set_progress("Running OCR on full page...")
            from app.page_ocr import extract_blocks

            ocr_cfg = dict(config.get("ocr") or {})
            ocr_cfg["debug"] = False
            blocks = extract_blocks(page_image, ocr_cfg)

            if not blocks:
                spinner.stop("  No text found on page.")
                root.after(0, lambda: progress_win[0].close() if progress_win else None)
                if on_error:
                    root.after(0, lambda: on_error("No text detected on this page."))
                return

            # ── Step 3: Batch translate ───────────────────────────────────
            total = len(blocks)
            _set_progress(f"Translating {total} text blocks...")
            spinner.update(f"Translating {total} blocks...")

            texts = [b["text"] for b in blocks]

            def _tr_progress(done, total_):
                _set_progress(f"Translating {done}/{total_} blocks...")

            translations = _batch_translate(texts, config, progress_callback=_tr_progress)

            translated_blocks = [
                {**b, "translated": t}
                for b, t in zip(blocks, translations)
            ]

            spinner.stop(f"  Done — {total} blocks translated.")
            root.after(0, lambda: progress_win[0].close() if progress_win else None)

            # ── Step 4: Open viewer ───────────────────────────────────────
            from app.page_viewer import PageViewer

            def _open_viewer():
                PageViewer(root, page_image, translated_blocks)
                if on_done:
                    on_done()

            root.after(0, _open_viewer)

        except Exception as e:
            spinner.stop(f"  Page translate error: {e}")
            root.after(0, lambda: progress_win[0].close() if progress_win else None)
            if on_error:
                root.after(0, lambda err=str(e): on_error(err))

    threading.Thread(target=_worker, daemon=True).start()
