"""
Scrollable viewer window that displays a stitched manga page with translated
text overlaid on each detected speech bubble.

The overlay is composited directly onto a copy of the page image using PIL
RGBA blending, so no Tkinter transparency tricks are needed.
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageDraw, ImageFont, ImageTk

# Overlay appearance
_BOX_FILL = (20, 20, 20, 210)        # dark semi-transparent background
_BOX_OUTLINE = (0, 230, 255, 180)    # cyan accent border
_TEXT_COLOR = (255, 255, 255, 255)   # white text
_ERROR_COLOR = (255, 100, 100, 255)  # red for error strings
_BOX_PAD = 5
_DEFAULT_FONT_SIZE = 13


def _find_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Return a TrueType font that supports Thai characters."""
    candidates = [
        "C:/Windows/Fonts/leelawad.ttf",   # Thai UI font (Windows 10+)
        "C:/Windows/Fonts/tahoma.ttf",     # broad Unicode coverage
        "C:/Windows/Fonts/calibri.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _wrap_text(text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont, max_width: int) -> list[str]:
    """Word-wrap text to fit inside max_width pixels."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip()
        try:
            bbox = font.getbbox(candidate)
            w = bbox[2] - bbox[0]
        except AttributeError:
            w = font.getlength(candidate)  # type: ignore[attr-defined]
        if w <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [text]


def _render_overlay(
    base: Image.Image,
    blocks: list[dict],
    font_size: int = _DEFAULT_FONT_SIZE,
    scale: float = 1.0,
) -> Image.Image:
    """
    Composite translated text boxes onto a copy of the base image.

    blocks must already be in display-image coordinates (after any scaling).
    """
    img = base.convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = _find_font(font_size)

    for block in blocks:
        translated = (block.get("translated") or "").strip()
        if not translated:
            continue

        x, y, bw, bh = block["bbox"]
        is_error = translated.startswith("[Error")
        text_color = _ERROR_COLOR if is_error else _TEXT_COLOR

        # Wrap text to the bubble width (min 80px)
        max_text_w = max(bw - _BOX_PAD * 2, 80)
        lines = _wrap_text(translated, font, max_text_w)

        # Measure total text height
        try:
            line_h = font.getbbox("Ag")[3] + 3
        except AttributeError:
            line_h = font.size + 3  # type: ignore[attr-defined]
        text_h = line_h * len(lines)

        # Box covers at minimum the original bubble area
        box_w = max(bw, max_text_w + _BOX_PAD * 2)
        box_h = max(bh, text_h + _BOX_PAD * 2)

        x2 = x + box_w
        y2 = y + box_h

        draw.rectangle((x - _BOX_PAD, y - _BOX_PAD, x2 + _BOX_PAD, y2 + _BOX_PAD), fill=_BOX_FILL)
        draw.rectangle(
            (x - _BOX_PAD, y - _BOX_PAD, x2 + _BOX_PAD, y2 + _BOX_PAD),
            outline=_BOX_OUTLINE,
            width=1,
        )

        ty = y
        for line in lines:
            draw.text((x, ty), line, font=font, fill=text_color)
            ty += line_h

    result = Image.alpha_composite(img, overlay)
    return result.convert("RGB")


def _scale_blocks(blocks: list[dict], scale: float) -> list[dict]:
    out = []
    for b in blocks:
        x, y, w, h = b["bbox"]
        out.append({
            **b,
            "bbox": [int(x * scale), int(y * scale), max(1, int(w * scale)), max(1, int(h * scale))],
        })
    return out


class PageViewer:
    """
    Scrollable window showing the full stitched page with translated overlay.

    Keyboard:
      Escape       — close
      Ctrl+scroll  — zoom in / out
      Up/Down/PgUp/PgDn — scroll
    """

    def __init__(
        self,
        root: tk.Tk,
        stitched_image: Image.Image,
        translated_blocks: list[dict],
        *,
        title: str = "Page Translator — Translated View",
        display_width: int = 960,
        font_size: int = _DEFAULT_FONT_SIZE,
    ):
        self._root = root
        self._source_image = stitched_image
        self._source_blocks = translated_blocks
        self._font_size = font_size

        self._win = tk.Toplevel(root)
        self._win.title(title)
        self._win.configure(bg="#1e1e1e")
        self._win.attributes("-topmost", True)

        # Derive initial display scale
        orig_w = stitched_image.width
        self._scale = min(1.0, display_width / orig_w)
        self._display_img: Image.Image | None = None
        self._photo: ImageTk.PhotoImage | None = None

        # ── Layout ──────────────────────────────────────────────────────
        toolbar = tk.Frame(self._win, bg="#2a2a2a", pady=4)
        toolbar.pack(fill=tk.X, side=tk.TOP)

        tk.Label(toolbar, text="Scroll:", bg="#2a2a2a", fg="#aaa",
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(8, 2))
        tk.Label(toolbar, text="mouse wheel  |  Zoom:", bg="#2a2a2a", fg="#aaa",
                 font=("Segoe UI", 9)).pack(side=tk.LEFT)
        tk.Label(toolbar, text="Ctrl+scroll  |  Close:", bg="#2a2a2a", fg="#aaa",
                 font=("Segoe UI", 9)).pack(side=tk.LEFT)
        tk.Label(toolbar, text="Escape", bg="#2a2a2a", fg="#00e6ff",
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(2, 8))

        # Zoom buttons
        tk.Button(
            toolbar, text="−", command=self._zoom_out,
            bg="#333", fg="#fff", relief=tk.FLAT, padx=6,
        ).pack(side=tk.RIGHT, padx=2)
        tk.Button(
            toolbar, text="+", command=self._zoom_in,
            bg="#333", fg="#fff", relief=tk.FLAT, padx=6,
        ).pack(side=tk.RIGHT, padx=2)
        tk.Label(toolbar, text="Zoom:", bg="#2a2a2a", fg="#aaa",
                 font=("Segoe UI", 9)).pack(side=tk.RIGHT, padx=(8, 2))

        canvas_frame = tk.Frame(self._win, bg="#1e1e1e")
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        self._scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL)
        self._scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._canvas = tk.Canvas(
            canvas_frame,
            bg="#1e1e1e",
            yscrollcommand=self._scrollbar.set,
            highlightthickness=0,
        )
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._scrollbar.config(command=self._canvas.yview)

        # ── Bindings ────────────────────────────────────────────────────
        self._win.bind("<Escape>", lambda _e: self._win.destroy())
        self._canvas.bind("<MouseWheel>", self._on_scroll)
        self._win.bind("<Control-MouseWheel>", self._on_ctrl_scroll)
        self._win.bind("<Up>",    lambda _e: self._canvas.yview_scroll(-1, "units"))
        self._win.bind("<Down>",  lambda _e: self._canvas.yview_scroll(1, "units"))
        self._win.bind("<Prior>", lambda _e: self._canvas.yview_scroll(-1, "pages"))
        self._win.bind("<Next>",  lambda _e: self._canvas.yview_scroll(1, "pages"))

        # Initial render
        self._render()

        # Window size: full screen height minus taskbar
        screen_h = root.winfo_screenheight()
        win_w = min(int(stitched_image.width * self._scale) + 20, root.winfo_screenwidth() - 50)
        win_h = screen_h - 80
        self._win.geometry(f"{win_w}x{win_h}+40+30")
        self._win.focus_force()

    # ── Rendering ───────────────────────────────────────────────────────

    def _render(self) -> None:
        """Re-render the overlay at the current scale and update the canvas."""
        orig_w, orig_h = self._source_image.size
        new_w = max(1, int(orig_w * self._scale))
        new_h = max(1, int(orig_h * self._scale))

        display = self._source_image.resize((new_w, new_h), Image.LANCZOS)
        scaled_blocks = _scale_blocks(self._source_blocks, self._scale)
        rendered = _render_overlay(display, scaled_blocks, font_size=self._font_size)

        self._display_img = rendered
        self._photo = ImageTk.PhotoImage(rendered)

        self._canvas.delete("all")
        self._canvas.create_image(0, 0, anchor=tk.NW, image=self._photo)
        self._canvas.configure(scrollregion=(0, 0, new_w, new_h))

    # ── Zoom ────────────────────────────────────────────────────────────

    def _zoom_in(self) -> None:
        self._scale = min(self._scale * 1.2, 3.0)
        self._render()

    def _zoom_out(self) -> None:
        self._scale = max(self._scale / 1.2, 0.2)
        self._render()

    # ── Event handlers ──────────────────────────────────────────────────

    def _on_scroll(self, event: tk.Event) -> None:
        self._canvas.yview_scroll(-1 * (event.delta // 120), "units")

    def _on_ctrl_scroll(self, event: tk.Event) -> None:
        if event.delta > 0:
            self._zoom_in()
        else:
            self._zoom_out()
