"""Modal configuration editor for config.json."""

from __future__ import annotations

import copy
import json
import re
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Callable

from app.series_config import (
    READING_COMBO_NONE,
    combo_display_for_key,
    migrate_translate_to_profiles,
    profile_label,
    profile_system_context,
    reading_pick_to_series_key,
    slugify_series_key,
)
from app.lens import MAX_RADIUS, MIN_RADIUS
from app.ai_integration import chat_complete, resolve_translate
from app.lang_prefs import DEFAULT_TRANSLATE_PROMPT
import requests

_PADDLE_LANG_CODES = (
    "en",
    "ch",
    "japan",
    "korean",
    "french",
    "german",
    "arabic",
    "cyrillic",
    "latin",
)

from app.hotkeys import (
    config_capture_trigger_raw,
    normalize_lens_wheel_mod,
    normalize_modifier_keysym_for_held,
    tk_key_event_to_hotkey,
    tk_listen_combine_modifiers,
    validate_keyboard_hotkey_string,
)

_ListenCb = Callable[[str], None]

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.user.json"
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_effective_config_dict() -> dict:
    """Same resolution order as app.main.load_config — for merging keys not edited in this panel."""
    for name in ("config.user.json", "config.default.json", "config.json"):
        p = _REPO_ROOT / name
        if p.exists():
            try:
                with open(p, encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
    return {}

# tk.Label default fg is often "" before map; config(fg="") can hide text on Windows.
_SHORTCUT_VALUE_FG = "#1a1a1a"
_SHORTCUT_MUTED_FG = "#666666"

# Space after fixed-width labels before the next control (Spinbox, Entry, Combobox, shortcut text).
_SETTINGS_ROW_LABEL_GAP = (0, 12)

_OCR_ENGINE_LABELS = (
    "PaddleOCR (local)",
    "AI Vision OCR (Docker)",
    "olmOCR (HTTP)",
)
_OCR_ENGINE_KEYS = ("paddleocr", "ai_vision", "olm_ocr")

_CAPTURE_MOUSE_CHOICES: list[tuple[str, str]] = [
    ("Middle mouse button", "middle_click"),
    ("Left mouse button", "left_click"),
    ("Right mouse button", "right_click"),
    ("Mouse side / back (X1)", "mouse_x1"),
    ("Mouse side / forward (X2)", "mouse_x2"),
]

_CAPTURE_LABEL_TO_TOKEN = {label: token for label, token in _CAPTURE_MOUSE_CHOICES}


def _normalize_openai_compatible_base(url: str) -> str:
    """Strip slashes and optional ``/v1`` so we can append ``/v1/models`` reliably."""
    u = (url or "").strip().rstrip("/")
    if u.lower().endswith("/v1"):
        u = u[:-3].rstrip("/")
    return u


def _parse_models_from_openai_json(payload: dict) -> list[str]:
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    out: list[str] = []
    for x in data:
        if isinstance(x, dict):
            mid = x.get("id")
            if isinstance(mid, str) and mid.strip():
                out.append(mid.strip())
    return sorted(set(out))
_CAPTURE_MOUSE_TOKEN_SET = {token.lower() for _, token in _CAPTURE_MOUSE_CHOICES}.union(
    {"x1", "x2", "back", "forward"}
)

_TRANSLATE_PROVIDER_LABELS = (
    "Docker Model Runner (local)",
    "Ollama (local)",
    "OpenAI (ChatGPT API)",
    "Anthropic (Claude)",
    "Custom (OpenAI-compatible)",
)
_TRANSLATE_PROVIDER_KEYS = ("docker_local", "ollama", "openai", "anthropic", "openai_compat")
_TRANSLATE_PROVIDER_DEFAULT_URL = {
    "docker_local": "http://localhost:12434",
    "ollama": "http://localhost:11434",
    "openai": "https://api.openai.com",
    "anthropic": "https://api.anthropic.com",
    "openai_compat": "http://localhost:12434",
}

_AI_OCR_BACKEND_LABELS = (
    "Same as translation",
    "Docker Model Runner (local)",
    "Ollama (local)",
    "OpenAI (ChatGPT API)",
    "Anthropic (Claude)",
    "Custom (OpenAI-compatible)",
)
_AI_OCR_BACKEND_KEYS = ("inherit", "docker_local", "ollama", "openai", "anthropic", "openai_compat")

_OLM_BACKEND_LABELS = (
    "Same as translation",
    "Docker Model Runner (local)",
    "Ollama (local)",
    "OpenAI (ChatGPT API)",
    "Anthropic (Claude)",
    "Custom (OpenAI-compatible)",
)
_OLM_BACKEND_KEYS = ("inherit", "docker_local", "ollama", "openai", "anthropic", "openai_compat")


def _migrate_legacy_ollama_provider_key(raw: str) -> str:
    """Old configs used ``llama_local``; canonical key is ``ollama``."""
    s = (raw or "").strip().lower()
    return "ollama" if s == "llama_local" else s


def _format_hotkey_plain_display(s: str) -> str:
    """Spaces around '+' for labels only (stored config string unchanged)."""
    t = s.strip()
    if not t or "+" not in t:
        return t
    return " + ".join(p.strip() for p in t.split("+"))


def _capture_token_to_mouse_label(token_lc: str) -> str | None:
    alias = {"x1": "mouse_x1", "back": "mouse_x1", "x2": "mouse_x2", "forward": "mouse_x2"}
    canon = alias.get(token_lc, token_lc)
    for label, tok in _CAPTURE_MOUSE_CHOICES:
        if tok.lower() == canon:
            return label
    return None


def _win32_force_window_visible(hwnd: int) -> None:
    """Lift above other HWND_TOPMOST overlays (Tk topmost sibling race on Windows)."""
    if sys.platform != "win32" or not hwnd:
        return
    try:
        import ctypes

        HWND_TOPMOST = -1
        SW_RESTORE = 9
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_SHOWWINDOW = 0x0040

        ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)
        ctypes.windll.user32.SetWindowPos(
            hwnd,
            HWND_TOPMOST,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
        )
    except Exception:
        pass


def _win32_resolve_hwnd(toplevel: tk.Misc) -> int:
    if sys.platform != "win32":
        return 0
    tid = int(toplevel.winfo_id())
    try:
        import ctypes

        user32 = ctypes.windll.user32
        ga_root = 2
        for candidate in (
            tid,
            user32.GetParent(tid),
            user32.GetAncestor(tid, ga_root),
        ):
            ci = int(candidate) if candidate else 0
            if ci > 0:
                return ci
    except Exception:
        pass
    return tid


def _bring_settings_to_foreground(panel: tk.Toplevel) -> None:
    panel.update_idletasks()
    try:
        panel.deiconify()
        panel.attributes("-topmost", True)
        panel.lift()
        panel.focus_force()
    except tk.TclError:
        pass
    _win32_force_window_visible(_win32_resolve_hwnd(panel))


class ConfigPanel(tk.Toplevel):
    """Save/Cancel are packed first at the bottom so they stay visible."""

    def _scroll_viewport(self, container: tk.Misc) -> tuple[tk.Frame, tk.Canvas]:
        """Scrollable interior (Windows MouseWheel); inner frame + canvas."""
        canvas = tk.Canvas(container, highlightthickness=0, borderwidth=0)
        vsb = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll_inner = tk.Frame(canvas)
        win_id = canvas.create_window((0, 0), window=scroll_inner, anchor="nw")

        def _sync_scroll(_evt=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        scroll_inner.bind("<Configure>", lambda e: _sync_scroll())

        def _canvas_resize(evt):
            try:
                canvas.itemconfigure(win_id, width=max(1, int(evt.width)))
            except tk.TclError:
                pass

        canvas.bind("<Configure>", _canvas_resize)

        if sys.platform == "win32":

            def _wheel_canvas(evt):
                canvas.yview_scroll(int(-evt.delta / 120), "units")

            def _bind_wheel(w):
                try:
                    c = (w.winfo_class() or "").lower()
                except tk.TclError:
                    return
                if c in ("scale", "spinbox", "text", "listbox"):
                    return
                w.bind("<MouseWheel>", _wheel_canvas)
                for ch in w.winfo_children():
                    _bind_wheel(ch)

            canvas.bind("<MouseWheel>", _wheel_canvas)
            scroll_inner.bind("<MouseWheel>", _wheel_canvas)
            self.after(100, lambda: _bind_wheel(scroll_inner))

        return scroll_inner, canvas

    def __init__(
        self,
        root: tk.Tk,
        initial: dict,
        on_save: Callable[[dict], None],
    ):
        super().__init__(root)
        self._on_save = on_save
        self._data = copy.deepcopy(initial)
        migrate_translate_to_profiles(self._data.setdefault("translate", {}))
        self._series_pick_suppress = 0

        self.resizable(True, True)

        btn_fr = tk.Frame(self)
        btn_fr.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=8)
        ttk.Button(btn_fr, text="Save", command=self._save).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(btn_fr, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)

        viewport = tk.Frame(self)
        viewport.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=0, pady=(8, 0))

        self.title("Manga Translator — Settings")
        self.minsize(520, 480)

        inner, scroll_canvas = self._scroll_viewport(viewport)
        nb = ttk.Notebook(inner)

        def _notebook_scroll_sync(_evt=None) -> None:
            inner.update_idletasks()
            try:
                box = scroll_canvas.bbox("all")
                if box:
                    scroll_canvas.configure(scrollregion=box)
            except tk.TclError:
                pass
            scroll_canvas.yview_moveto(0)

        nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))

        self._tab_general(nb)
        self._tab_ai(nb)
        self._tab_lens(nb)
        self._tab_popup(nb)
        self._tab_ocr(nb)

        nb.bind("<<NotebookTabChanged>>", _notebook_scroll_sync)
        self.after(150, _notebook_scroll_sync)

        # Do NOT transient() to withdrawn root Tk() — prevents mapping on some Windows setups.
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = min(640, sw - 48)
        h = min(620, sh - 80)
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.geometry(f"{int(w)}x{int(h)}+{x}+{y}")
        try:
            self.attributes("-toolwindow", False)
        except tk.TclError:
            pass

        try:
            self.state("normal")
        except tk.TclError:
            pass

        _bring_settings_to_foreground(self)
        self.after(50, lambda: _bring_settings_to_foreground(self))
        self.after(200, lambda: _bring_settings_to_foreground(self))

    def _color_picker_row(self, parent, label: str, var: tk.StringVar):
        fr = tk.Frame(parent)
        fr.pack(fill=tk.X, pady=(0, 6))
        tk.Label(fr, text=label, width=18, anchor="w").pack(side=tk.LEFT, padx=_SETTINGS_ROW_LABEL_GAP)
        ent = tk.Entry(fr, textvariable=var)
        ent.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

        def pick():
            c = colorchooser.askcolor(color=var.get(), title=label)
            if c and c[1]:
                var.set(c[1])

        ttk.Button(fr, text="Pick…", width=8, command=pick).pack(side=tk.LEFT)

    def _tab_lens(self, nb: ttk.Notebook):
        tab = tk.Frame(nb, padx=12, pady=12)
        nb.add(tab, text="Lens")
        self._populate_lens_form(tab)

    def _populate_lens_form(self, tab: tk.Frame) -> None:
        lr = int(self._data.get("lens_radius", 150))
        default_side = 2 * lr
        lw = int(self._data.get("lens_width", default_side))
        lh = int(self._data.get("lens_height", default_side))

        shape_row = tk.Frame(tab)
        shape_row.pack(fill=tk.X, pady=(0, 8))
        tk.Label(shape_row, text="Lens shape:", width=18, anchor="w").pack(
            side=tk.LEFT,
            padx=_SETTINGS_ROW_LABEL_GAP,
        )
        ls = str(self._data.get("lens_shape", "circle")).strip().lower()
        if ls not in ("circle", "square"):
            ls = "circle"
        self.var_lens_shape = tk.StringVar(value=ls)
        ttk.Combobox(
            shape_row,
            textvariable=self.var_lens_shape,
            values=("circle", "square"),
            state="readonly",
            width=12,
        ).pack(side=tk.LEFT)

        dim_container = tk.Frame(tab)
        dim_container.pack(fill=tk.X, pady=(0, 8))

        self.var_lens_width = tk.IntVar(value=lw)
        self.var_lens_height = tk.IntVar(value=lh)
        self._lens_wh_fr = tk.LabelFrame(dim_container, text="Lens width × height (px)")
        tk.Label(self._lens_wh_fr, text="Width:", anchor="w").pack(fill=tk.X, padx=10, pady=(8, 0))
        tk.Scale(
            self._lens_wh_fr,
            variable=self.var_lens_width,
            orient=tk.HORIZONTAL,
            from_=MIN_RADIUS * 2,
            to=MAX_RADIUS * 2,
            resolution=10,
            length=400,
        ).pack(fill=tk.X, padx=8, pady=4)
        tk.Label(self._lens_wh_fr, text="Height:", anchor="w").pack(fill=tk.X, padx=10, pady=(4, 0))
        tk.Scale(
            self._lens_wh_fr,
            variable=self.var_lens_height,
            orient=tk.HORIZONTAL,
            from_=MIN_RADIUS * 2,
            to=MAX_RADIUS * 2,
            resolution=10,
            length=400,
        ).pack(fill=tk.X, padx=8, pady=(4, 8))

        def _hint_for_shape(*_: object) -> None:
            sq = self.var_lens_shape.get().strip().lower() == "square"
            self._lens_wh_fr.configure(
                text=(
                    "Square — width × height (capture rectangle)"
                    if sq
                    else "Circle — width × height (ellipse inside this box)"
                ),
            )

        self.var_lens_shape.trace_add("write", _hint_for_shape)
        _hint_for_shape()
        self._lens_wh_fr.pack(fill=tk.X)

        self.var_lens_color = tk.StringVar(value=str(self._data.get("lens_color", "#00ff88")))
        self._color_picker_row(tab, "Ring color:", self.var_lens_color)

        bw_fr = tk.LabelFrame(tab, text="Lens border line (px)")
        bw_fr.pack(fill=tk.X, pady=(8, 0))
        self.var_lens_border = tk.IntVar(value=int(self._data.get("lens_border_width", 3)))
        tk.Spinbox(bw_fr, from_=1, to=20, textvariable=self.var_lens_border, width=10).pack(
            anchor="w", padx=10, pady=8
        )

        op_fr = tk.LabelFrame(tab, text="Lens opacity")
        op_fr.pack(fill=tk.X, pady=(8, 0))
        self.var_lens_opacity = tk.DoubleVar(value=float(self._data.get("lens_opacity", 1.0)))
        tk.Scale(
            op_fr,
            variable=self.var_lens_opacity,
            orient=tk.HORIZONTAL,
            from_=0.4,
            to=1.0,
            resolution=0.05,
            length=400,
        ).pack(fill=tk.X, padx=8, pady=8)

        tk.Label(
            tab,
            text=self._lens_wheel_scroll_hint_saved(),
            fg="#666",
            wraplength=520,
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(12, 0))

    def _lens_wheel_scroll_hint_saved(self) -> str:
        labels = {"alt": "Alt", "shift": "Shift", "ctrl": "Ctrl", "win": "Win"}
        w = normalize_lens_wheel_mod(self._data.get("lens_wheel_mod_width", "alt"))
        h = normalize_lens_wheel_mod(self._data.get("lens_wheel_mod_height", "ctrl"))
        if w == h:
            h = next(t for t in ("shift", "alt", "ctrl", "win") if t != w)
        return (
            f"In-app resize (both shapes): {labels[w]}+scroll → width · {labels[h]}+scroll → height · "
            f"{labels[w]}+{labels[h]}+scroll → both sides (100–800 px). "
            "(Adjust wheel modifiers in General → Lens resize.)"
        )

    def _tab_popup(self, nb: ttk.Notebook):
        tab = tk.Frame(nb, padx=12, pady=12)
        nb.add(tab, text="Popup")

        gf = tk.LabelFrame(tab, text="Typography & timing")
        gf.pack(fill=tk.X, pady=(0, 8))

        row = tk.Frame(gf)
        row.pack(fill=tk.X, padx=8, pady=4)
        tk.Label(row, text="Font size:", width=14, anchor="w").pack(side=tk.LEFT, padx=_SETTINGS_ROW_LABEL_GAP)
        self.var_popup_font = tk.IntVar(value=int(self._data.get("popup_font_size", 14)))
        tk.Spinbox(row, from_=8, to=32, textvariable=self.var_popup_font, width=8).pack(side=tk.LEFT)

        row2 = tk.Frame(gf)
        row2.pack(fill=tk.X, padx=8, pady=4)
        tk.Label(row2, text="Auto-close (ms):", width=14, anchor="w").pack(
            side=tk.LEFT,
            padx=_SETTINGS_ROW_LABEL_GAP,
        )
        self.var_popup_close = tk.IntVar(value=int(self._data.get("popup_auto_close_ms", 15000)))
        tk.Spinbox(row2, from_=1000, to=600000, increment=500, textvariable=self.var_popup_close, width=10).pack(
            side=tk.LEFT
        )

        row3 = tk.Frame(gf)
        row3.pack(fill=tk.X, padx=8, pady=8)
        tk.Label(row3, text="Max text width:", width=14, anchor="w").pack(
            side=tk.LEFT,
            padx=_SETTINGS_ROW_LABEL_GAP,
        )
        self.var_popup_maxw = tk.IntVar(value=int(self._data.get("popup_max_width", 680)))
        tk.Spinbox(row3, from_=240, to=900, increment=10, textvariable=self.var_popup_maxw, width=8).pack(
            side=tk.LEFT
        )

        _ox0 = int(self._data.get("popup_mouse_offset_x", 0))
        if "popup_mouse_offset_y" in self._data:
            _oy0 = int(self._data["popup_mouse_offset_y"])
        else:
            _oy0 = int(self._data.get("popup_mouse_gap_px", 20))

        row_ox = tk.Frame(gf)
        row_ox.pack(fill=tk.X, padx=8, pady=(0, 4))
        tk.Label(row_ox, text="Mouse offset X (px):", width=14, anchor="w").pack(
            side=tk.LEFT,
            padx=_SETTINGS_ROW_LABEL_GAP,
        )
        self.var_popup_mouse_offset_x = tk.IntVar(value=_ox0)
        tk.Spinbox(
            row_ox,
            from_=-2000,
            to=2000,
            increment=5,
            textvariable=self.var_popup_mouse_offset_x,
            width=8,
        ).pack(side=tk.LEFT)

        row_oy = tk.Frame(gf)
        row_oy.pack(fill=tk.X, padx=8, pady=(0, 4))
        tk.Label(row_oy, text="Mouse offset Y (px):", width=14, anchor="w").pack(
            side=tk.LEFT,
            padx=_SETTINGS_ROW_LABEL_GAP,
        )
        self.var_popup_mouse_offset_y = tk.IntVar(value=_oy0)
        tk.Spinbox(
            row_oy,
            from_=-2000,
            to=2000,
            increment=5,
            textvariable=self.var_popup_mouse_offset_y,
            width=8,
        ).pack(side=tk.LEFT)
        tk.Label(
            gf,
            text=(
                "Popup is centered on the cursor horizontally, then shifted by X (negative = left). "
                "Top edge is placed at cursor row + Y (negative = up; 0 = tight to cursor row)."
            ),
            fg="#666",
            wraplength=520,
            justify=tk.LEFT,
        ).pack(anchor="w", padx=8, pady=(0, 4))

        qa_fr = tk.LabelFrame(tab, text="Quick OCR replacement from popup")
        qa_fr.pack(fill=tk.X, pady=(8, 0))
        self.var_popup_quick_append = tk.BooleanVar(
            value=bool(self._data.get("popup_quick_append", False)),
        )
        tk.Checkbutton(
            qa_fr,
            variable=self.var_popup_quick_append,
            text=(
                "When on: the + strip on translation popups adds a form to save an OCR replacement rule "
                "(match → replace, whole-word) into the active Reading profile — same rules as Settings → Translation → OCR replacements. "
                "The expanded panel always offers correct-source (OCR) + Re-translate when that makes sense "
                "(even when this box is off)."
            ),
            fg="#444",
            wraplength=500,
            justify=tk.LEFT,
            anchor="w",
        ).pack(anchor="w", padx=8, pady=8)

        lay = tk.LabelFrame(tab, text="Layout & rounding")
        lay.pack(fill=tk.X, pady=(8, 0))

        row_r = tk.Frame(lay)
        row_r.pack(fill=tk.X, padx=8, pady=6)
        tk.Label(row_r, text="Corner radius (px):", width=14, anchor="w").pack(
            side=tk.LEFT,
            padx=_SETTINGS_ROW_LABEL_GAP,
        )
        self.var_popup_border_radius = tk.IntVar(value=int(self._data.get("popup_border_radius", 6)))
        tk.Spinbox(row_r, from_=0, to=48, textvariable=self.var_popup_border_radius, width=8).pack(side=tk.LEFT)

        row_outline = tk.Frame(lay)
        row_outline.pack(fill=tk.X, padx=8, pady=(0, 6))
        tk.Label(row_outline, text="Border line (px):", width=14, anchor="w").pack(
            side=tk.LEFT,
            padx=_SETTINGS_ROW_LABEL_GAP,
        )
        self.var_popup_border_width = tk.IntVar(
            value=int(self._data.get("popup_border_width", 1))
        )
        tk.Spinbox(
            row_outline,
            from_=0,
            to=16,
            textvariable=self.var_popup_border_width,
            width=8,
        ).pack(side=tk.LEFT)
        tk.Label(
            lay,
            text="Accent outline thickness around the popup (0 = no border line). Uses 'Outer border' color.",
            fg="#666",
            wraplength=520,
            justify=tk.LEFT,
        ).pack(anchor="w", padx=8, pady=(0, 6))

        row_wb = tk.Frame(lay)
        row_wb.pack(fill=tk.X, padx=8, pady=(0, 8))
        tk.Label(row_wb, text="Word break:", width=14, anchor="w").pack(
            side=tk.LEFT,
            padx=_SETTINGS_ROW_LABEL_GAP,
        )
        wm = str(self._data.get("popup_wrap_mode", "word")).strip().lower()
        if wm != "char":
            wm = "word"
        self.var_popup_wrap_mode = tk.StringVar(value=wm)
        ttk.Combobox(
            row_wb,
            textvariable=self.var_popup_wrap_mode,
            values=("word", "char"),
            state="readonly",
            width=10,
        ).pack(side=tk.LEFT)

        tk.Label(
            lay,
            text='"word": wrap between words. "char": wrap anywhere (narrow columns, long unbroken Thai).',
            fg="#666",
            wraplength=520,
            justify=tk.LEFT,
        ).pack(anchor="w", padx=8, pady=(0, 6))

        op_fr = tk.LabelFrame(tab, text="Window opacity")
        op_fr.pack(fill=tk.X, pady=(4, 8))
        self.var_popup_opacity = tk.DoubleVar(value=float(self._data.get("popup_opacity", 1.0)))
        tk.Scale(
            op_fr,
            variable=self.var_popup_opacity,
            orient=tk.HORIZONTAL,
            from_=0.4,
            to=1.0,
            resolution=0.05,
            length=400,
        ).pack(fill=tk.X, padx=8, pady=8)

        col_fr = tk.LabelFrame(tab, text="Colors")
        col_fr.pack(fill=tk.X, pady=(0, 8))

        self.var_popup_bg = tk.StringVar(value=str(self._data.get("popup_bg_color", "#1e1e1e")))
        self.var_popup_accent = tk.StringVar(value=str(self._data.get("popup_accent_color", "#00ff88")))
        self.var_popup_trans = tk.StringVar(value=str(self._data.get("popup_translation_fg", "#ffffff")))

        self._color_picker_row(col_fr, "Background:", self.var_popup_bg)
        self._color_picker_row(col_fr, "Outer border:", self.var_popup_accent)
        self._color_picker_row(col_fr, "Text:", self.var_popup_trans)

    def _translate_provider_key_from_ui(self) -> str:
        try:
            i = int(self._cb_translate_provider.current())
        except (tk.TclError, TypeError, ValueError):
            return "docker_local"
        if i < 0 or i >= len(_TRANSLATE_PROVIDER_KEYS):
            return "docker_local"
        return _TRANSLATE_PROVIDER_KEYS[i]

    def _on_translate_provider_changed(self, _evt=None) -> None:
        k = self._translate_provider_key_from_ui()
        self.var_ai_url.set(_TRANSLATE_PROVIDER_DEFAULT_URL.get(k, "http://localhost:12434"))

    def _apply_provider_default_url(self, url_var: tk.StringVar, provider_key: str) -> None:
        """Set base URL to the canonical default for this backend (same idea as Translation tab)."""
        if provider_key == "inherit":
            return
        url_var.set(_TRANSLATE_PROVIDER_DEFAULT_URL.get(provider_key, "http://localhost:12434"))

    def _sync_ai_ocr_url_entry(self) -> None:
        """API base URL row follows Translate when backend is 'Same as translation'."""
        if not getattr(self, "_ent_ai_ocr_url", None):
            return
        k = self._ai_ocr_backend_key_from_ui()
        self._ent_ai_ocr_url.configure(
            textvariable=self.var_ai_url if k == "inherit" else self.var_ai_ocr_base_url,
        )

    def _on_ai_ocr_backend_changed(self, _evt=None) -> None:
        k = self._ai_ocr_backend_key_from_ui()
        self._apply_provider_default_url(self.var_ai_ocr_base_url, k)
        self._sync_ai_ocr_url_entry()

    def _sync_olm_url_entry(self) -> None:
        if not getattr(self, "_ent_olm_url", None):
            return
        k = self._olm_backend_key_from_ui()
        self._ent_olm_url.configure(
            textvariable=self.var_ai_url if k == "inherit" else self.var_olm_url,
        )

    def _on_olm_backend_changed(self, _evt=None) -> None:
        k = self._olm_backend_key_from_ui()
        self._apply_provider_default_url(self.var_olm_url, k)
        self._sync_olm_url_entry()

    def _ai_runtime_config_snapshot(self) -> dict:
        """Partial config for resolve_translate / chat while the settings panel is open."""
        tr = copy.deepcopy(self._data.get("translate") or {})
        integ = {**(tr.get("integration") or {})}
        integ["provider"] = self._translate_provider_key_from_ui()
        new_k = self.var_translate_api_key.get().strip()
        if new_k:
            integ["api_key"] = new_k
        tr["integration"] = integ
        tr["source_lang"] = self.var_source_lang.get().strip() or "English"
        tr["target_lang"] = self.var_target_lang.get().strip() or "Thai"
        return {
            "ai_url": self.var_ai_url.get().strip(),
            "model": self.var_model.get().strip(),
            "translate": tr,
        }

    def _ai_ocr_backend_key_from_ui(self) -> str:
        try:
            i = int(self._cb_ai_ocr_backend.current())
        except (tk.TclError, TypeError, ValueError, AttributeError):
            return "inherit"
        if i < 0 or i >= len(_AI_OCR_BACKEND_KEYS):
            return "inherit"
        return _AI_OCR_BACKEND_KEYS[i]

    def _olm_backend_key_from_ui(self) -> str:
        try:
            i = int(self._cb_olm_backend.current())
        except (tk.TclError, TypeError, ValueError, AttributeError):
            return "openai_compat"
        if i < 0 or i >= len(_OLM_BACKEND_KEYS):
            return "openai_compat"
        return _OLM_BACKEND_KEYS[i]

    def _olm_list_models_url_var(self) -> tk.StringVar:
        k = self._olm_backend_key_from_ui()
        if k == "inherit":
            return self.var_ai_url
        if k == "docker_local":
            return self.var_olm_url
        if k in ("openai", "anthropic"):
            return self.var_ai_url
        if k == "ollama":
            return self.var_olm_url
        return self.var_olm_url

    def _olm_list_models_key_var(self) -> tk.StringVar | None:
        k = self._olm_backend_key_from_ui()
        if k == "inherit":
            return self.var_translate_api_key
        if k in ("openai", "anthropic", "openai_compat", "ollama"):
            return self.var_olm_api_key
        return None

    def _pick_openai_model_ai_ocr(self) -> None:
        k = self._ai_ocr_backend_key_from_ui()
        if k == "inherit":
            self._pick_openai_model(self.var_ai_url, self.var_ai_ocr_model, self.var_translate_api_key)
            return
        if self.var_ai_ocr_base_url.get().strip():
            self._pick_openai_model(
                self.var_ai_ocr_base_url,
                self.var_ai_ocr_model,
                self.var_ai_ocr_api_key,
            )
            return
        self._pick_openai_model(self.var_ai_url, self.var_ai_ocr_model, self.var_ai_ocr_api_key)

    def _tab_ai(self, nb: ttk.Notebook):
        tab = tk.Frame(nb, padx=12, pady=12)
        nb.add(tab, text="AI / Translate")

        td = self._data.get("translate") or {}
        tr_int = td.get("integration") or {}
        prov = _migrate_legacy_ollama_provider_key(str(tr_int.get("provider") or "docker_local"))
        if prov not in _TRANSLATE_PROVIDER_KEYS:
            prov = "docker_local"

        row_prov = tk.Frame(tab)
        row_prov.pack(fill=tk.X, pady=(0, 8))
        tk.Label(row_prov, text="Translation backend:", width=18, anchor="w").pack(
            side=tk.LEFT,
            padx=_SETTINGS_ROW_LABEL_GAP,
        )
        self._cb_translate_provider = ttk.Combobox(
            row_prov,
            values=_TRANSLATE_PROVIDER_LABELS,
            state="readonly",
            width=36,
        )
        self._cb_translate_provider.pack(side=tk.LEFT, fill=tk.X, expand=True)
        try:
            self._cb_translate_provider.current(_TRANSLATE_PROVIDER_KEYS.index(prov))
        except ValueError:
            self._cb_translate_provider.current(0)

        self.var_ai_url = tk.StringVar(value=str(self._data.get("ai_url", "http://localhost:12434")))
        self.var_model = tk.StringVar(value=str(self._data.get("model", "")))
        self.var_translate_api_key = tk.StringVar(value="")

        for label, var in (
            ("API base URL:", self.var_ai_url),
            ("Translation model:", self.var_model),
        ):
            fr = tk.Frame(tab)
            fr.pack(fill=tk.X, pady=(0, 6))
            tk.Label(fr, text=label, width=18, anchor="w").pack(side=tk.LEFT, padx=_SETTINGS_ROW_LABEL_GAP)
            if label.startswith("Translation model"):
                tk.Entry(fr, textvariable=var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
                ttk.Button(
                    fr,
                    text="List models…",
                    command=lambda: self._pick_openai_model(
                        self.var_ai_url,
                        self.var_model,
                        self.var_translate_api_key,
                    ),
                ).pack(side=tk.LEFT)
            else:
                tk.Entry(fr, textvariable=var).pack(side=tk.LEFT, fill=tk.X, expand=True)

        key_hint = (
            "API key for cloud backends only — optional if OPENAI_API_KEY / ANTHROPIC_API_KEY is set. "
            "Leave blank to keep a previously saved key."
        )
        if str(tr_int.get("api_key") or "").strip():
            key_hint += " (A key is already saved — type a new one to replace.)"
        key_fr = tk.Frame(tab)
        key_fr.pack(fill=tk.X, pady=(0, 6))
        tk.Label(key_fr, text="API key (optional):", width=18, anchor="w").pack(
            side=tk.LEFT,
            padx=_SETTINGS_ROW_LABEL_GAP,
        )
        tk.Entry(key_fr, textvariable=self.var_translate_api_key, show="*").pack(
            side=tk.LEFT,
            fill=tk.X,
            expand=True,
        )
        tk.Label(tab, text=key_hint, fg="#666", wraplength=520, justify=tk.LEFT).pack(anchor="w", pady=(0, 4))
        self._cb_translate_provider.bind("<<ComboboxSelected>>", self._on_translate_provider_changed)

        lang_lf = tk.LabelFrame(tab, text="Languages")
        lang_lf.pack(fill=tk.X, pady=(10, 0))
        self.var_source_lang = tk.StringVar(
            value=str(td.get("source_lang") or "English").strip() or "English"
        )
        self.var_target_lang = tk.StringVar(
            value=str(td.get("target_lang") or "Thai").strip() or "Thai"
        )
        lr = tk.Frame(lang_lf)
        lr.pack(fill=tk.X, padx=8, pady=(8, 4))
        tk.Label(lr, text="Source (OCR) language:", width=18, anchor="w").pack(
            side=tk.LEFT, padx=_SETTINGS_ROW_LABEL_GAP
        )
        tk.Entry(lr, textvariable=self.var_source_lang, width=22).pack(side=tk.LEFT, padx=(0, 12))
        tk.Label(lr, text="Target language:", width=14, anchor="w").pack(side=tk.LEFT, padx=(0, 8))
        tk.Entry(lr, textvariable=self.var_target_lang, width=22).pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(
            lang_lf,
            text=(
                "Used in the translation system prompt, popup labels, and optional placeholders in the prompt below: "
                "{source_lang}, {target_lang}, and {text} (required). "
                "For PaddleOCR, set the language code on the OCR tab."
            ),
            fg="#666",
            wraplength=520,
            justify=tk.LEFT,
        ).pack(anchor="w", padx=8, pady=(0, 8))

        self._series_profiles: dict[str, dict] = copy.deepcopy(td.get("series_profiles") or {})
        if not self._series_profiles:
            self._series_profiles = {
                "default": {
                    "label": "Default",
                    "context": "",
                    "series_name": "",
                    "glossary": "",
                    "text_corrections": [],
                },
            }
        raw_act = td.get("active_series")
        if isinstance(raw_act, str) and raw_act.strip() == "":
            self._series_active_key = ""
        else:
            self._series_active_key = str(raw_act or "default").strip() or "default"
            if self._series_active_key not in self._series_profiles:
                self._series_active_key = next(iter(self._series_profiles.keys()))

        ser_fr = tk.LabelFrame(tab, text="Active manga / series  (separate context & translation memory)")
        ser_fr.pack(fill=tk.X, pady=(10, 0))

        sr = tk.Frame(ser_fr)
        sr.pack(fill=tk.X, padx=8, pady=(8, 8))
        tk.Label(sr, text="Reading:", width=14, anchor="w").pack(side=tk.LEFT, padx=_SETTINGS_ROW_LABEL_GAP)
        self.var_series_pick = tk.StringVar()
        self.cmb_series_pick = ttk.Combobox(
            sr,
            textvariable=self.var_series_pick,
            state="readonly",
            width=40,
        )
        self.cmb_series_pick.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        ttk.Button(sr, text="New…", command=self._new_series_profile).pack(side=tk.LEFT)
        self._btn_series_delete = ttk.Button(sr, text="Delete", command=self._delete_series_profile)
        self._btn_series_delete.pack(side=tk.LEFT, padx=(8, 0))
        tk.Label(
            ser_fr,
            text="Choose (none) for generic translation (no saved series context); translation memory uses a separate bucket until you pick a profile. Delete is disabled for (none) and when only one profile remains.",
            fg="#666",
            wraplength=520,
            justify=tk.LEFT,
        ).pack(anchor="w", padx=8, pady=(0, 8))

        # --- Series lookup ---
        lookup_lf = tk.LabelFrame(tab, text="Auto-generate context from series name")
        lookup_lf.pack(fill=tk.X, pady=(10, 0))

        lookup_row = tk.Frame(lookup_lf)
        lookup_row.pack(fill=tk.X, padx=8, pady=(8, 4))
        tk.Label(lookup_row, text="Comic / Series:", width=14, anchor="w").pack(side=tk.LEFT, padx=_SETTINGS_ROW_LABEL_GAP)
        self.var_series_name = tk.StringVar(value=(self._data.get("translate") or {}).get("series_name", ""))
        tk.Entry(lookup_row, textvariable=self.var_series_name).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self._btn_search_ctx = ttk.Button(lookup_row, text="Search & Fill Context", command=self._search_and_fill_context)
        self._btn_search_ctx.pack(side=tk.LEFT)

        tk.Label(
            lookup_lf,
            text='Type a series name (e.g. "Spider-Man", "Naruto", "One Piece"), then click Search. The AI will look it up online and write a translation context for you.',
            fg="#666",
            wraplength=520,
            justify=tk.LEFT,
        ).pack(anchor="w", padx=8, pady=(0, 8))

        # --- Context box ---
        ctx_lf = tk.LabelFrame(tab, text="Series context  (sent to AI as system instructions)")
        ctx_lf.pack(fill=tk.X, pady=(10, 0))
        self.txt_context = ScrolledText(ctx_lf, height=8, wrap=tk.WORD, font=("Consolas", 10))
        self.txt_context.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        tk.Label(
            ctx_lf,
            text='Auto-filled by Search, or edit manually. Leave blank for generic translation.',
            fg="#666",
            wraplength=520,
            justify=tk.LEFT,
        ).pack(anchor="w", padx=8, pady=(0, 6))

        gloss_lf = tk.LabelFrame(
            tab,
            text="Names & glossary  (also sent to AI; use for OCR fixes & character spellings)",
        )
        gloss_lf.pack(fill=tk.X, pady=(10, 0))
        self.txt_glossary = ScrolledText(gloss_lf, height=4, wrap=tk.WORD, font=("Consolas", 10))
        self.txt_glossary.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        tk.Label(
            gloss_lf,
            text=(
                "One line per name or phrase. Example: Kaoru — main character; garbled OCR like "
                '"if ka or u", "Iwonder…" usually means Kaoru. '
                "Search & Fill Context also merges AI-suggested names/terms here (existing lines kept; duplicates skipped)."
            ),
            fg="#666",
            wraplength=520,
            justify=tk.LEFT,
        ).pack(anchor="w", padx=8, pady=(0, 6))

        corr_lf = tk.LabelFrame(
            tab,
            text="OCR replacements  (this series only — run before translation)",
        )
        corr_lf.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        tk.Label(
            corr_lf,
            text=(
                "Replace garbled or Japanese honorific transliterations so the model sees plain English. "
                "For ordinary English names, turn on Match case so Aerial (character) does not change aerial (adjective). "
                'Honorifics / all-caps OCR: leave Match case off. Turn off Whole word only for typos inside longer tokens.'
            ),
            fg="#666",
            wraplength=520,
            justify=tk.LEFT,
        ).pack(anchor="w", padx=8, pady=(8, 4))

        tree_fr = tk.Frame(corr_lf)
        tree_fr.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
        self._corrections_tree = ttk.Treeview(
            tree_fr,
            columns=("match", "replace", "whole", "mcase"),
            show="headings",
            height=5,
            selectmode="browse",
        )
        self._corrections_tree.heading("match", text="Match (OCR)")
        self._corrections_tree.heading("replace", text="Replace with")
        self._corrections_tree.heading("whole", text="Whole word")
        self._corrections_tree.heading("mcase", text="Match case")
        self._corrections_tree.column("match", width=128, stretch=True)
        self._corrections_tree.column("replace", width=168, stretch=True)
        self._corrections_tree.column("whole", width=76, stretch=False, anchor=tk.CENTER)
        self._corrections_tree.column("mcase", width=76, stretch=False, anchor=tk.CENTER)
        vsb = ttk.Scrollbar(tree_fr, orient=tk.VERTICAL, command=self._corrections_tree.yview)
        self._corrections_tree.configure(yscrollcommand=vsb.set)
        self._corrections_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        add_fr = tk.Frame(corr_lf)
        add_fr.pack(fill=tk.X, padx=6, pady=(0, 8))
        tk.Label(add_fr, text="Match:").pack(side=tk.LEFT, padx=(0, 4))
        self._var_corr_match = tk.StringVar()
        tk.Entry(add_fr, textvariable=self._var_corr_match, width=18).pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(add_fr, text="Replace:").pack(side=tk.LEFT, padx=(0, 4))
        self._var_corr_replace = tk.StringVar()
        tk.Entry(add_fr, textvariable=self._var_corr_replace, width=22).pack(side=tk.LEFT, padx=(0, 8))
        self._var_corr_whole = tk.BooleanVar(value=True)
        tk.Checkbutton(add_fr, text="Whole word", variable=self._var_corr_whole).pack(side=tk.LEFT, padx=(0, 8))
        self._var_corr_case = tk.BooleanVar(value=False)
        tk.Checkbutton(add_fr, text="Match case", variable=self._var_corr_case).pack(side=tk.LEFT, padx=(0, 8))

        def _corr_add() -> None:
            if self._series_active_key == "":
                return
            m = self._var_corr_match.get().strip()
            if not m:
                messagebox.showwarning("OCR replacements", "Enter text to match.", parent=self)
                return
            r = self._var_corr_replace.get()
            ww = self._var_corr_whole.get()
            cs = self._var_corr_case.get()
            self._corrections_tree.insert(
                "",
                tk.END,
                values=(m, r, "Yes" if ww else "No", "Yes" if cs else "No"),
            )
            self._var_corr_match.set("")
            self._var_corr_replace.set("")

        def _corr_remove() -> None:
            sel = self._corrections_tree.selection()
            if not sel:
                return
            self._corrections_tree.delete(sel[0])

        ttk.Button(add_fr, text="Add rule", command=_corr_add).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(add_fr, text="Delete selected row", command=_corr_remove).pack(side=tk.LEFT)
        self._corrections_tree.bind("<Delete>", lambda _e: _corr_remove())
        self._corrections_tree.bind("<BackSpace>", lambda _e: _corr_remove())

        tk.Label(
            corr_lf,
            text="Delete: select a row, then “Delete selected row” or press Delete. Click OK / Save in this window to write changes to your config file.",
            fg="#666",
            wraplength=520,
            justify=tk.LEFT,
            anchor="w",
        ).pack(anchor="w", padx=8, pady=(0, 4))

        self._load_profile_to_editor(self._series_active_key)

        lf = tk.LabelFrame(
            tab,
            text="Translation prompt  (must contain {text}; optional {source_lang}, {target_lang})",
        )
        lf.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self.txt_translate = ScrolledText(lf, height=5, wrap=tk.WORD, font=("Consolas", 10))
        self.txt_translate.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        prompt = (self._data.get("translate") or {}).get("prompt", DEFAULT_TRANSLATE_PROMPT)
        self.txt_translate.insert("1.0", prompt)

        self.cmb_series_pick.bind("<<ComboboxSelected>>", self._on_series_pick_changed)
        self._rebuild_series_combo()

    def _sync_series_delete_button(self) -> None:
        cant_delete = (
            self._series_active_key == ""
            or len(self._series_profiles) <= 1
        )
        try:
            self._btn_series_delete.configure(state=("disabled" if cant_delete else "normal"))
        except tk.TclError:
            pass

    def _rebuild_series_combo(self) -> None:
        profiles = self._series_profiles
        keys = sorted(profiles.keys(), key=lambda k: profile_label(profiles, k).lower())
        displays = [READING_COMBO_NONE] + [combo_display_for_key(profiles, k) for k in keys]
        self.cmb_series_pick.configure(values=displays)
        self._series_pick_suppress += 1
        try:
            if self._series_active_key == "":
                self.var_series_pick.set(READING_COMBO_NONE)
            else:
                self.var_series_pick.set(combo_display_for_key(profiles, self._series_active_key))
        finally:
            self._series_pick_suppress -= 1
        self._sync_series_delete_button()

    def _persist_profile_from_editor(self) -> None:
        if self._series_active_key == "":
            return
        ctx = self.txt_context.get("1.0", "end").rstrip("\n")
        gloss = self.txt_glossary.get("1.0", "end").rstrip("\n")
        sn = self.var_series_name.get().strip()
        p = self._series_profiles.get(self._series_active_key)
        if not isinstance(p, dict):
            p = {
                "label": self._series_active_key,
                "context": ctx,
                "series_name": sn,
                "glossary": gloss,
                "text_corrections": self._corrections_list_from_tree(),
            }
            self._series_profiles[self._series_active_key] = p
            return
        p["context"] = ctx
        p["series_name"] = sn
        p["glossary"] = gloss
        p["text_corrections"] = self._corrections_list_from_tree()
        lab = str(p.get("label", "")).strip()
        if not lab:
            p["label"] = sn or self._series_active_key

    def _corrections_list_from_tree(self) -> list[dict]:
        if not hasattr(self, "_corrections_tree"):
            return []
        out: list[dict] = []
        for iid in self._corrections_tree.get_children():
            vals = self._corrections_tree.item(iid, "values")
            if not vals or len(vals) < 3:
                continue
            m = str(vals[0] or "").strip()
            if not m:
                continue
            r = str(vals[1] or "")
            w = str(vals[2] or "").strip().lower()
            ww = w not in ("no", "n", "0", "false")
            mc = ""
            if len(vals) >= 4:
                mc = str(vals[3] or "").strip().lower()
            cs = mc not in ("no", "n", "0", "false", "")
            out.append({"match": m, "replace": r, "whole_word": ww, "case_sensitive": cs})
        return out

    def _load_profile_to_editor(self, key: str) -> None:
        self._series_active_key = key
        prof = self._series_profiles.get(key)
        ctx = ""
        sn = ""
        gloss = ""
        if isinstance(prof, dict):
            ctx = prof.get("context", "") or ""
            sn = str(prof.get("series_name", "") or "").strip()
            gloss = prof.get("glossary", "") or ""
        self.txt_context.delete("1.0", "end")
        self.txt_context.insert("1.0", ctx)
        self.txt_glossary.delete("1.0", "end")
        self.txt_glossary.insert("1.0", gloss)
        self.var_series_name.set(sn)
        if hasattr(self, "_corrections_tree"):
            for ch in self._corrections_tree.get_children():
                self._corrections_tree.delete(ch)
            if key and isinstance(prof, dict):
                raw_c = prof.get("text_corrections")
                if isinstance(raw_c, list):
                    for item in raw_c:
                        if not isinstance(item, dict):
                            continue
                        m = str(item.get("match", "") or "").strip()
                        if not m:
                            continue
                        r = str(item.get("replace", "") or "")
                        ww = bool(item.get("whole_word", True))
                        cs = bool(item.get("case_sensitive", False))
                        self._corrections_tree.insert(
                            "",
                            tk.END,
                            values=(m, r, "Yes" if ww else "No", "Yes" if cs else "No"),
                        )
        self._sync_series_delete_button()

    def _on_series_pick_changed(self, _evt=None) -> None:
        if self._series_pick_suppress:
            return
        self._persist_profile_from_editor()
        parsed = reading_pick_to_series_key(self.var_series_pick.get())
        if parsed is None:
            self._rebuild_series_combo()
            return
        if parsed != "" and parsed not in self._series_profiles:
            self._rebuild_series_combo()
            return
        if parsed == self._series_active_key:
            self._sync_series_delete_button()
            return
        self._load_profile_to_editor(parsed)
        self._rebuild_series_combo()

    def _new_series_profile(self) -> None:
        name = simpledialog.askstring("New series", "Manga / comic name for this profile:", parent=self)
        if not name or not str(name).strip():
            return
        self._persist_profile_from_editor()
        name = str(name).strip()
        slug = slugify_series_key(name, frozenset(self._series_profiles.keys()))
        self._series_profiles[slug] = {
            "label": name,
            "context": "",
            "series_name": name,
            "glossary": "",
            "text_corrections": [],
        }
        self._series_active_key = slug
        self._rebuild_series_combo()
        self._load_profile_to_editor(slug)

    def _delete_series_profile(self) -> None:
        if self._series_active_key == "":
            return
        if len(self._series_profiles) <= 1:
            messagebox.showwarning(
                "Series",
                "You need at least one series profile.",
                parent=self,
            )
            return
        lab = profile_label(self._series_profiles, self._series_active_key)
        if not messagebox.askyesno(
            "Remove series profile",
            f'Remove "{lab}" ({self._series_active_key}) from the list?\n\n'
            "Translation memory rows for this key stay in memory.db.",
            parent=self,
        ):
            return
        self._persist_profile_from_editor()
        del self._series_profiles[self._series_active_key]
        self._series_active_key = sorted(self._series_profiles.keys())[0]
        self._rebuild_series_combo()
        self._load_profile_to_editor(self._series_active_key)

    def _search_and_fill_context(self) -> None:
        import threading

        if self._series_active_key == "":
            messagebox.showwarning(
                "Series name",
                "Select a manga profile first (Reading), or click New…. (none) has no saved context.",
                parent=self,
            )
            return

        name = self.var_series_name.get().strip()
        if not name:
            messagebox.showwarning("Series name", "Enter a comic or manga series name first.", parent=self)
            return
        self._btn_search_ctx.configure(state="disabled", text="Searching…")
        threading.Thread(target=self._do_search_context, args=(name,), daemon=True).start()

    def _do_search_context(self, name: str) -> None:
        import requests as req

        wiki_summary = ""
        try:
            slug = name.replace(" ", "_")
            r = req.get(
                f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}",
                timeout=10,
                headers={"User-Agent": "manga-translator-app/1.0"},
            )
            if r.status_code == 200:
                wiki_summary = r.json().get("extract", "")[:1200]
        except Exception:
            pass

        gloss_footer = (
            "\n\nAfter that, on its own line write exactly:\n---GLOSSARY---\n"
            "Then one canonical English (or Japanese) spelling per line: main character names and "
            "series-specific terms the translator must spell consistently. No bullets or numbering. "
            "If there is nothing to list, write ---GLOSSARY--- with nothing below it."
        )
        if wiki_summary:
            ai_input = (
                f'Series: {name}\n\nBackground (Wikipedia):\n{wiki_summary}\n\n'
                f'Based on this, write a system prompt for an AI translator doing English-to-Thai translations of this series. '
                f'Structure it in this order:\n'
                f'1. A 2-3 sentence synopsis of the story so the translator understands the world and plot.\n'
                f'2. Which character names and special terms to keep in English (or Japanese for manga).\n'
                f'3. The tone and style of the dialogue.\n'
                f'4. Any important catchphrases or terminology to handle carefully.\n'
                f'Keep the system prompt under 250 words.'
                f'{gloss_footer}'
            )
        else:
            ai_input = (
                f'Write a system prompt for an AI translator doing English-to-Thai translations of the "{name}" comic/manga series. '
                f'Structure it in this order:\n'
                f'1. A 2-3 sentence synopsis of the story so the translator understands the world and plot.\n'
                f'2. Which character names and special terms to keep in English (or Japanese for manga).\n'
                f'3. The tone and style of the dialogue.\n'
                f'4. Any important catchphrases or terminology to handle carefully.\n'
                f'Keep the system prompt under 250 words.'
                f'{gloss_footer}'
            )

        try:
            ep = resolve_translate(self._ai_runtime_config_snapshot())
            generated = chat_complete(
                ep,
                [{"role": "user", "content": ai_input}],
                timeout=90,
            )
            if generated.startswith("[Error:"):
                self.after(0, self._search_context_error, generated)
            else:
                self.after(0, self._apply_generated_context, generated)
        except Exception as e:
            self.after(0, self._search_context_error, str(e))

    @staticmethod
    def _split_generated_context_glossary(raw: str) -> tuple[str, str]:
        t = (raw or "").strip()
        if not t:
            return "", ""
        m = re.search(r"^---\s*GLOSSARY\s*---\s*$", t, re.MULTILINE | re.IGNORECASE)
        if not m:
            return t, ""
        ctx = t[: m.start()].strip()
        gloss = t[m.end() :].strip()
        return ctx, gloss

    def _merge_glossary_lines(self, existing: str, addition: str) -> str:
        """Append non-empty lines from addition that are not already present (case-insensitive)."""
        seen = {
            ln.strip().lower()
            for ln in existing.splitlines()
            if ln.strip()
        }
        out_lines = [ln for ln in existing.splitlines()]
        for ln in addition.splitlines():
            s = ln.strip()
            if not s:
                continue
            key = s.lower()
            if key in seen:
                continue
            seen.add(key)
            out_lines.append(s)
        return "\n".join(out_lines).strip("\n")

    def _apply_generated_context(self, text: str) -> None:
        ctx_text, gloss_block = self._split_generated_context_glossary(text)
        self.txt_context.delete("1.0", "end")
        self.txt_context.insert("1.0", ctx_text)

        cur_gloss = self.txt_glossary.get("1.0", "end").rstrip("\n")
        merged = self._merge_glossary_lines(cur_gloss, gloss_block)
        series_line = self.var_series_name.get().strip()
        if series_line:
            merged = self._merge_glossary_lines(merged, series_line)
        self.txt_glossary.delete("1.0", "end")
        self.txt_glossary.insert("1.0", merged)

        self._btn_search_ctx.configure(state="normal", text="Search & Fill Context")

    def _search_context_error(self, msg: str) -> None:
        self._btn_search_ctx.configure(state="normal", text="Search & Fill Context")
        messagebox.showerror("Context search failed", f"Could not generate context:\n{msg}", parent=self)

    def _ocr_swap_panels(self, engine_key: str) -> None:
        for fr in self._ocr_engine_frames:
            fr.pack_forget()
        if engine_key == "paddleocr":
            self._fr_ocr_paddle.pack(fill=tk.BOTH, expand=True)
        elif engine_key == "ai_vision":
            self._fr_ocr_ai.pack(fill=tk.BOTH, expand=True)
        else:
            self._fr_ocr_olm.pack(fill=tk.BOTH, expand=True)

    def _ocr_engine_from_ui(self) -> str:
        i = self._cb_ocr_engine.current()
        if i < 0 or i >= len(_OCR_ENGINE_KEYS):
            return "paddleocr"
        return _OCR_ENGINE_KEYS[i]

    def _pick_openai_model(
        self,
        url_var: tk.StringVar,
        model_var: tk.StringVar,
        api_key_var: tk.StringVar | None = None,
    ) -> None:
        """GET ``/v1/models`` from an OpenAI-compatible server; user picks an ``id`` into ``model_var``."""
        base = _normalize_openai_compatible_base(url_var.get())
        if not base:
            messagebox.showwarning(
                "Models",
                "Enter a server base URL first (e.g. http://127.0.0.1:30024 or your AI base URL).",
                parent=self,
            )
            return

        dlg = tk.Toplevel(self)
        dlg.title("Select model")
        dlg.transient(self)
        dlg.grab_set()
        dlg.minsize(420, 280)

        frm = tk.Frame(dlg, padx=10, pady=8)
        frm.pack(fill=tk.BOTH, expand=True)

        tk.Label(frm, text=f"Models from:\n{base}/v1/models", anchor="w", justify="left").pack(
            fill=tk.X,
            pady=(0, 6),
        )
        status = tk.Label(frm, text="Loading…", anchor="w", fg="#666666")
        status.pack(fill=tk.X)

        lb_fr = tk.Frame(frm)
        lb_fr.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        scrollbar = ttk.Scrollbar(lb_fr, orient="vertical")
        lb = tk.Listbox(lb_fr, height=14, font=("Consolas", 10), yscrollcommand=scrollbar.set)
        scrollbar.config(command=lb.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        def _dlg_alive() -> bool:
            try:
                return bool(dlg.winfo_exists())
            except tk.TclError:
                return False

        def apply_selection():
            sel = lb.curselection()
            if not sel:
                messagebox.showinfo("Models", "Select a model first.", parent=dlg)
                return
            model_var.set(lb.get(sel[0]))
            dlg.destroy()

        def on_double(_evt=None):
            if lb.curselection():
                apply_selection()

        lb.bind("<Double-Button-1>", on_double)

        btn_fr = tk.Frame(frm)
        btn_fr.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btn_fr, text="Cancel", command=dlg.destroy).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(btn_fr, text="Use selected", command=apply_selection).pack(side=tk.RIGHT)

        list_timeout = 25

        def load_task():
            err: str | None = None
            ids: list[str] = []
            try:
                headers: dict[str, str] = {}
                if api_key_var is not None:
                    key = api_key_var.get().strip()
                    if key:
                        headers["Authorization"] = f"Bearer {key}"
                r = requests.get(f"{base}/v1/models", headers=headers or None, timeout=list_timeout)
                if not r.ok:
                    err = f"HTTP {r.status_code}: {r.text.strip()[:400]}"
                else:
                    j = r.json()
                    ids = _parse_models_from_openai_json(j)
                    if not ids:
                        err = "Empty or unrecognized /v1/models response."
            except requests.exceptions.RequestException as e:
                err = str(e)
            except Exception as e:
                err = str(e)

            def finish():
                if not _dlg_alive():
                    return
                if err:
                    status.configure(text=err, fg="#b00020")
                    messagebox.showerror("Models", f"Could not list models:\n{err}", parent=dlg)
                    return
                for mid in ids:
                    lb.insert(tk.END, mid)
                status.configure(text=f"{len(ids)} model(s). Double-click or Use selected.", fg="#666666")

            self.after(0, finish)

        threading.Thread(target=load_task, daemon=True).start()

        self.update_idletasks()
        x = self.winfo_rootx() + 40
        y = self.winfo_rooty() + 80
        dlg.geometry(f"480x360+{x}+{y}")

    def _tab_ocr(self, nb: ttk.Notebook):
        tab = tk.Frame(nb, padx=12, pady=12)
        nb.add(tab, text="OCR")
        o = self._data.get("ocr") or {}
        ai = self._data.get("ai_ocr") or {}
        olm = self._data.get("olm_ocr") or {}

        engine = str(o.get("engine") or "").strip().lower()
        if not engine:
            engine = "ai_vision" if ai.get("enabled") else "paddleocr"
        if engine == "olmocr_local":
            engine = "olm_ocr"
        if engine not in _OCR_ENGINE_KEYS:
            engine = "paddleocr"

        row0 = tk.Frame(tab)
        row0.pack(fill=tk.X, pady=(0, 8))
        tk.Label(row0, text="OCR engine:", width=14, anchor="w").pack(side=tk.LEFT, padx=_SETTINGS_ROW_LABEL_GAP)
        self._cb_ocr_engine = ttk.Combobox(
            row0,
            values=_OCR_ENGINE_LABELS,
            state="readonly",
            width=36,
        )
        self._cb_ocr_engine.pack(side=tk.LEFT, fill=tk.X, expand=True)
        try:
            idx = _OCR_ENGINE_KEYS.index(engine)
        except ValueError:
            idx = 0
        self._cb_ocr_engine.current(idx)

        body = tk.Frame(tab)
        body.pack(fill=tk.BOTH, expand=True)

        self._fr_ocr_paddle = tk.Frame(body)
        self._fr_ocr_ai = tk.Frame(body)
        self._fr_ocr_olm = tk.Frame(body)
        self._ocr_engine_frames = (
            self._fr_ocr_paddle,
            self._fr_ocr_ai,
            self._fr_ocr_olm,
        )

        # --- PaddleOCR (local): preprocessing tunables ---
        self.var_ocr_upscale = tk.IntVar(value=int(o.get("upscale", 2)))
        self.var_ocr_contrast = tk.DoubleVar(value=float(o.get("contrast", 1.0)))
        self.var_ocr_sharp = tk.DoubleVar(value=float(o.get("sharpness", 1.0)))
        self.var_ocr_binarize = tk.BooleanVar(value=bool(o.get("binarize", False)))
        self.var_ocr_fix_case = tk.BooleanVar(value=bool(o.get("fix_case", True)))
        self.var_ocr_debug = tk.BooleanVar(value=bool(o.get("debug", False)))
        self.var_ocr_thr = tk.DoubleVar(value=float(o.get("text_threshold", 0.5)))
        self.var_ocr_low = tk.DoubleVar(value=float(o.get("low_text", 0.3)))
        self.var_ocr_link = tk.DoubleVar(value=float(o.get("link_threshold", 0.3)))
        self.var_ocr_mag = tk.DoubleVar(value=float(o.get("mag_ratio", 2.0)))
        self.var_ocr_min = tk.IntVar(value=int(o.get("min_size", 8)))
        self.var_ocr_paddle_lang = tk.StringVar(
            value=str(o.get("paddle_lang") or "en").strip() or "en"
        )

        pf = self._fr_ocr_paddle
        pf.columnconfigure(0, weight=1)
        row_pl = tk.Frame(pf)
        row_pl.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        tk.Label(row_pl, text="Paddle language:", width=16, anchor="w").pack(
            side=tk.LEFT, padx=_SETTINGS_ROW_LABEL_GAP
        )
        ttk.Combobox(
            row_pl,
            textvariable=self.var_ocr_paddle_lang,
            values=_PADDLE_LANG_CODES,
            width=14,
        ).pack(side=tk.LEFT)
        tk.Label(
            pf,
            text="PaddleOCR recognition model (e.g. en, japan, korean, latin for Latin script). Type a code if yours is not listed.",
            fg="#666",
            wraplength=480,
            justify=tk.LEFT,
        ).grid(row=1, column=0, sticky="w", pady=(0, 8))
        specs = [
            ("Upscale", self.var_ocr_upscale, 1, 4, True, 1),
            ("Contrast", self.var_ocr_contrast, 0.5, 3.0, False, 0.05),
            ("Sharpness", self.var_ocr_sharp, 0.5, 3.0, False, 0.05),
            ("text_threshold", self.var_ocr_thr, 0.0, 1.0, False, 0.05),
            ("low_text", self.var_ocr_low, 0.0, 1.0, False, 0.05),
            ("link_threshold", self.var_ocr_link, 0.0, 1.0, False, 0.05),
            ("mag_ratio", self.var_ocr_mag, 0.5, 4.0, False, 0.05),
            ("min_size", self.var_ocr_min, 1, 64, True, 1),
        ]
        for i, (name, var, lo, hi, is_int, inc) in enumerate(specs):
            fr = tk.Frame(pf)
            fr.grid(row=i + 2, column=0, sticky="ew", pady=2)
            tk.Label(fr, text=name + ":", width=16, anchor="w").pack(side=tk.LEFT, padx=_SETTINGS_ROW_LABEL_GAP)
            if is_int:
                tk.Spinbox(fr, from_=lo, to=hi, textvariable=var, width=12).pack(side=tk.LEFT)
            else:
                tk.Spinbox(fr, from_=lo, to=hi, increment=inc, textvariable=var, width=12).pack(side=tk.LEFT)
        tk.Checkbutton(pf, text="Binarize", variable=self.var_ocr_binarize).grid(
            row=len(specs) + 2, column=0, sticky="w"
        )
        tk.Checkbutton(pf, text="Fix case (manga caps)", variable=self.var_ocr_fix_case).grid(
            row=len(specs) + 3, column=0, sticky="w", pady=(4, 0)
        )
        tk.Checkbutton(pf, text="PaddleOCR preprocess debug dumps", variable=self.var_ocr_debug).grid(
            row=len(specs) + 4, column=0, sticky="w", pady=(4, 0)
        )

        # --- AI Vision OCR (same layout order as AI / Translate: backend → URL → model → key) ---
        af = self._fr_ocr_ai
        ai_int = ai.get("integration") or {}
        ab = _migrate_legacy_ollama_provider_key(str(ai_int.get("provider") or "inherit"))
        if ab not in _AI_OCR_BACKEND_KEYS:
            ab = "inherit"
        self.var_ai_ocr_base_url = tk.StringVar(value=str(ai_int.get("base_url") or "").strip())

        row_ai_be = tk.Frame(af)
        row_ai_be.pack(fill=tk.X, pady=(0, 8))
        tk.Label(row_ai_be, text="Vision OCR backend:", width=18, anchor="w").pack(
            side=tk.LEFT,
            padx=_SETTINGS_ROW_LABEL_GAP,
        )
        self._cb_ai_ocr_backend = ttk.Combobox(
            row_ai_be,
            values=_AI_OCR_BACKEND_LABELS,
            state="readonly",
            width=36,
        )
        self._cb_ai_ocr_backend.pack(side=tk.LEFT, fill=tk.X, expand=True)
        try:
            self._cb_ai_ocr_backend.current(_AI_OCR_BACKEND_KEYS.index(ab))
        except ValueError:
            self._cb_ai_ocr_backend.current(0)

        fr_ai_url = tk.Frame(af)
        fr_ai_url.pack(fill=tk.X, pady=(0, 6))
        tk.Label(fr_ai_url, text="API base URL:", width=18, anchor="w").pack(
            side=tk.LEFT,
            padx=_SETTINGS_ROW_LABEL_GAP,
        )
        self._ent_ai_ocr_url = tk.Entry(fr_ai_url, textvariable=self.var_ai_ocr_base_url)
        self._ent_ai_ocr_url.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(
            af,
            text=(
                "When backend is “Same as translation”, this is the same URL as AI / Translate → API base URL. "
                "Otherwise it is only used for vision OCR."
            ),
            fg="#666",
            wraplength=520,
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(0, 6))

        self.var_ai_ocr_model = tk.StringVar(value=str(ai.get("model", "")))
        fr_ai = tk.Frame(af)
        fr_ai.pack(fill=tk.X, pady=(0, 6))
        tk.Label(fr_ai, text="Vision model:", width=18, anchor="nw").pack(
            side=tk.LEFT, anchor="n", padx=_SETTINGS_ROW_LABEL_GAP
        )
        fr_ai_col = tk.Frame(fr_ai)
        fr_ai_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        fr_ai_entry = tk.Frame(fr_ai_col)
        fr_ai_entry.pack(fill=tk.X)
        tk.Entry(fr_ai_entry, textvariable=self.var_ai_ocr_model).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6)
        )
        ttk.Button(
            fr_ai_entry,
            text="List models…",
            command=self._pick_openai_model_ai_ocr,
        ).pack(side=tk.LEFT)

        ai_key_hint = (
            "API key for cloud backends only — optional if OPENAI_API_KEY / ANTHROPIC_API_KEY is set. "
            "Leave blank to keep a previously saved key."
        )
        if str(ai_int.get("api_key") or "").strip():
            ai_key_hint += " (A key is already saved — type a new one to replace.)"
        self.var_ai_ocr_api_key = tk.StringVar(value="")
        fr_ai_key = tk.Frame(af)
        fr_ai_key.pack(fill=tk.X, pady=(0, 6))
        tk.Label(fr_ai_key, text="API key (optional):", width=18, anchor="w").pack(
            side=tk.LEFT,
            padx=_SETTINGS_ROW_LABEL_GAP,
        )
        tk.Entry(fr_ai_key, textvariable=self.var_ai_ocr_api_key, show="*").pack(
            side=tk.LEFT,
            fill=tk.X,
            expand=True,
        )
        tk.Label(af, text=ai_key_hint, fg="#666", wraplength=520, justify=tk.LEFT).pack(anchor="w", pady=(0, 4))

        self._cb_ai_ocr_backend.bind("<<ComboboxSelected>>", self._on_ai_ocr_backend_changed)
        self._sync_ai_ocr_url_entry()

        lf_ai = tk.LabelFrame(af, text="Vision OCR prompt")
        lf_ai.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.txt_ai_ocr = ScrolledText(lf_ai, height=8, wrap=tk.WORD, font=("Consolas", 10))
        self.txt_ai_ocr.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.txt_ai_ocr.insert("1.0", ai.get("prompt", ""))
        self.var_ai_ocr_debug = tk.BooleanVar(value=bool(ai.get("debug", False)))
        tk.Checkbutton(af, text="AI Vision OCR debug dumps", variable=self.var_ai_ocr_debug).pack(
            anchor="w", pady=(8, 0)
        )

        # --- olmOCR (OpenAI-compatible HTTP) — same block order as AI / Translate ---
        of = self._fr_ocr_olm
        olm_int = olm.get("integration") or {}
        obm = _migrate_legacy_ollama_provider_key(str(olm_int.get("provider") or "openai_compat"))
        if obm not in _OLM_BACKEND_KEYS:
            obm = "openai_compat"
        row_olm_be = tk.Frame(of)
        row_olm_be.pack(fill=tk.X, pady=(0, 8))
        tk.Label(row_olm_be, text="olmOCR backend:", width=18, anchor="w").pack(
            side=tk.LEFT,
            padx=_SETTINGS_ROW_LABEL_GAP,
        )
        self._cb_olm_backend = ttk.Combobox(
            row_olm_be,
            values=_OLM_BACKEND_LABELS,
            state="readonly",
            width=36,
        )
        self._cb_olm_backend.pack(side=tk.LEFT, fill=tk.X, expand=True)
        try:
            self._cb_olm_backend.current(_OLM_BACKEND_KEYS.index(obm))
        except ValueError:
            self._cb_olm_backend.current(_OLM_BACKEND_KEYS.index("openai_compat"))

        self.var_olm_url = tk.StringVar(value=str(olm.get("url", "")))
        fr_u = tk.Frame(of)
        fr_u.pack(fill=tk.X, pady=(0, 6))
        tk.Label(fr_u, text="API base URL:", width=18, anchor="w").pack(side=tk.LEFT, padx=_SETTINGS_ROW_LABEL_GAP)
        self._ent_olm_url = tk.Entry(fr_u, textvariable=self.var_olm_url)
        self._ent_olm_url.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(
            of,
            text=(
                "When backend is “Same as translation”, this field tracks AI / Translate → API base URL. "
                "Use Custom (OpenAI-compatible) for a dedicated vLLM / SGLang port."
            ),
            fg="#666",
            wraplength=520,
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(0, 6))

        self.var_olm_model = tk.StringVar(value=str(olm.get("model", "")))
        fr_m = tk.Frame(of)
        fr_m.pack(fill=tk.X, pady=(0, 6))
        tk.Label(fr_m, text="Model:", width=18, anchor="w").pack(side=tk.LEFT, padx=_SETTINGS_ROW_LABEL_GAP)
        tk.Entry(fr_m, textvariable=self.var_olm_model).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        ttk.Button(
            fr_m,
            text="List models…",
            command=lambda: self._pick_openai_model(
                self._olm_list_models_url_var(),
                self.var_olm_model,
                self._olm_list_models_key_var(),
            ),
        ).pack(side=tk.LEFT)

        olm_key_hint = (
            "API key for cloud backends only — optional if OPENAI_API_KEY / ANTHROPIC_API_KEY is set. "
            "Leave blank to keep a previously saved key."
        )
        if str(olm.get("api_key") or "").strip():
            olm_key_hint += " (A key is already saved — type a new one to replace.)"
        self.var_olm_api_key = tk.StringVar(value="")
        fr_olm_key = tk.Frame(of)
        fr_olm_key.pack(fill=tk.X, pady=(0, 6))
        tk.Label(fr_olm_key, text="API key (optional):", width=18, anchor="w").pack(
            side=tk.LEFT,
            padx=_SETTINGS_ROW_LABEL_GAP,
        )
        tk.Entry(fr_olm_key, textvariable=self.var_olm_api_key, show="*").pack(
            side=tk.LEFT,
            fill=tk.X,
            expand=True,
        )
        tk.Label(of, text=olm_key_hint, fg="#666", wraplength=520, justify=tk.LEFT).pack(anchor="w", pady=(0, 4))

        self._cb_olm_backend.bind("<<ComboboxSelected>>", self._on_olm_backend_changed)
        self._sync_olm_url_entry()
        lf_olm = tk.LabelFrame(of, text="olmOCR prompt")
        lf_olm.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.txt_olm_ocr = ScrolledText(lf_olm, height=8, wrap=tk.WORD, font=("Consolas", 10))
        self.txt_olm_ocr.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.txt_olm_ocr.insert("1.0", olm.get("prompt", ""))
        self.var_olm_debug = tk.BooleanVar(value=bool(olm.get("debug", False)))
        tk.Checkbutton(of, text="olmOCR debug dumps", variable=self.var_olm_debug).pack(anchor="w", pady=(8, 0))

        def _on_engine(_evt=None):
            self._ocr_swap_panels(self._ocr_engine_from_ui())

        self._cb_ocr_engine.bind("<<ComboboxSelected>>", _on_engine)
        self._ocr_swap_panels(engine)

    def _tab_general(self, nb: ttk.Notebook):
        tab = tk.Frame(nb, padx=12, pady=12)
        nb.add(tab, text="General")

        self.var_debug = tk.BooleanVar(value=bool(self._data.get("debug", False)))
        tk.Checkbutton(tab, text='Global debug (also enables OCR debug unless disabled on the OCR tab)', variable=self.var_debug).pack(anchor="w")

        self.var_show_exit = tk.BooleanVar(value=bool(self._data.get("show_exit_button", True)))
        tk.Checkbutton(
            tab,
            text="Show draggable control bar (Exit, Test connection, Settings)",
            variable=self.var_show_exit,
        ).pack(
            anchor="w", pady=(10, 0)
        )

        self.var_exit_hotkey = tk.StringVar(value=str(self._data.get("exit_hotkey", "<ctrl>+<shift>+<alt>+q")))
        self.var_settings_hotkey = tk.StringVar(value=str(self._data.get("settings_hotkey", "f12")))

        self.var_capture_hotkey = tk.StringVar(value=config_capture_trigger_raw(self._data))

        hk_fr = tk.LabelFrame(tab, text="Shortcuts (Listen only)")
        hk_fr.pack(fill=tk.X, pady=(10, 0))
        self._shortcut_listen_row(
            hk_fr,
            "Run capture (OCR + translate):",
            self.var_capture_hotkey,
            self._listen_capture_hotkey,
            display_format=lambda r: _capture_token_to_mouse_label(r.lower())
            or _format_hotkey_plain_display(r),
        )

        cap_mouse_fr = tk.Frame(hk_fr)
        cap_mouse_fr.pack(fill=tk.X, padx=8, pady=(0, 6))
        tk.Label(cap_mouse_fr, text="Capture (mouse menu):", width=22, anchor="w").pack(
            side=tk.LEFT,
            padx=_SETTINGS_ROW_LABEL_GAP,
        )
        self.var_capture_mouse_combo = tk.StringVar()
        self._cb_capture_mouse = ttk.Combobox(
            cap_mouse_fr,
            textvariable=self.var_capture_mouse_combo,
            state="readonly",
            width=42,
        )
        self._cb_capture_mouse.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._cb_capture_mouse.bind("<<ComboboxSelected>>", self._on_capture_mouse_combo_selected)
        self.var_capture_hotkey.trace_add("write", lambda *_: self._sync_capture_mouse_combo_display())
        self._sync_capture_mouse_combo_display()

        tk.Label(
            hk_fr,
            text="When using keys, the menu shows “Keyboard: …” with your chord; pick a mouse line to switch to a click.",
            fg="#555",
            wraplength=520,
            justify=tk.LEFT,
        ).pack(anchor="w", padx=8, pady=(0, 6))

        self._shortcut_listen_row(hk_fr, "Quit translator:", self.var_exit_hotkey, self._listen_exit_hotkey)
        self._shortcut_listen_row(hk_fr, "Open Settings:", self.var_settings_hotkey, self._listen_settings_hotkey)

        self._build_lens_resize_hotkeys_ui(tab)

        tk.Label(
            tab,
            text=(
                "Listen opens a grab window: hold Ctrl/Shift/Alt/Win as needed, then press the final key. "
                "Escape cancels without changing."
            ),
            fg="#555",
            wraplength=520,
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(12, 0))

    def _ensure_lens_wheel_mod_vars(self) -> None:
        if hasattr(self, "var_lens_wheel_mod_width"):
            return
        w = normalize_lens_wheel_mod(self._data.get("lens_wheel_mod_width", "alt"))
        h = normalize_lens_wheel_mod(self._data.get("lens_wheel_mod_height", "ctrl"))
        if w == h:
            h = next(t for t in ("shift", "alt", "ctrl", "win") if t != w)
        self.var_lens_wheel_mod_width = tk.StringVar(value=w)
        self.var_lens_wheel_mod_height = tk.StringVar(value=h)

    def _lens_wheel_mod_row(self, parent: tk.Misc, label: str, token_var: tk.StringVar) -> None:
        labels = ["Alt", "Shift", "Ctrl", "Win"]
        tokens = ["alt", "shift", "ctrl", "win"]
        readable = dict(zip(tokens, labels))
        token_from_label = dict(zip(labels, tokens))

        fr = tk.Frame(parent)
        fr.pack(fill=tk.X, padx=8, pady=6)
        tk.Label(fr, text=label, width=22, anchor="w").pack(side=tk.LEFT, padx=_SETTINGS_ROW_LABEL_GAP)
        cb = ttk.Combobox(fr, values=labels, width=14, state="readonly")
        cb.set(readable[normalize_lens_wheel_mod(token_var.get())])
        cb.pack(side=tk.LEFT)

        def on_sel(_evt=None) -> None:
            lbl = cb.get()
            tok = token_from_label.get(lbl)
            if tok:
                token_var.set(tok)

        cb.bind("<<ComboboxSelected>>", on_sel)

    def _ensure_lens_resize_hotkey_vars(self) -> None:
        if hasattr(self, "var_lens_hk_resize_w"):
            return
        self.var_lens_hk_resize_w = tk.StringVar(
            value=str(self._data.get("lens_hotkey_resize_width", "")),
        )
        self.var_lens_hk_resize_h_up = tk.StringVar(
            value=str(self._data.get("lens_hotkey_resize_height_up", "")),
        )
        self.var_lens_hk_resize_h_dn = tk.StringVar(
            value=str(self._data.get("lens_hotkey_resize_height_down", "")),
        )

    def _build_lens_resize_hotkeys_ui(self, parent: tk.Misc) -> None:
        self._ensure_lens_wheel_mod_vars()
        self._ensure_lens_resize_hotkey_vars()

        wheel_fr = tk.LabelFrame(parent, text="Lens resize (mouse wheel)")
        wheel_fr.pack(fill=tk.X, pady=(10, 0))
        self._lens_wheel_mod_row(wheel_fr, "Hold + scroll → width:", self.var_lens_wheel_mod_width)
        self._lens_wheel_mod_row(wheel_fr, "Hold + scroll → height:", self.var_lens_wheel_mod_height)
        tk.Label(
            wheel_fr,
            text='Pick two different keys. Holding both together + scroll adjusts width and height at once.',
            fg="#666",
            wraplength=520,
            justify=tk.LEFT,
        ).pack(anchor="w", padx=8, pady=(4, 8))

        hk_r = tk.LabelFrame(parent, text="Lens resize (keyboard, optional)")
        hk_r.pack(fill=tk.X, pady=(10, 0))
        self._shortcut_listen_row(
            hk_r,
            "Widen width (+):",
            self.var_lens_hk_resize_w,
            self._listen_lens_hk_resize_w,
            empty_as="(none — disabled)",
        )
        self._shortcut_listen_row(
            hk_r,
            "Height increase (+):",
            self.var_lens_hk_resize_h_up,
            self._listen_lens_hk_resize_h_up,
            empty_as="(none — disabled)",
        )
        self._shortcut_listen_row(
            hk_r,
            "Height decrease (-):",
            self.var_lens_hk_resize_h_dn,
            self._listen_lens_hk_resize_h_dn,
            empty_as="(none — disabled)",
        )
        tk.Label(
            hk_r,
            text=(
                "One shortcut widens width only; two shortcuts resize height ±. "
                "Leave blank to disable. Mouse wheel uses the modifiers chosen above."
            ),
            fg="#666",
            wraplength=520,
            justify=tk.LEFT,
        ).pack(anchor="w", padx=8, pady=(4, 8))

    def _shortcut_listen_row(
        self,
        parent: tk.Misc,
        label: str,
        display_var: tk.StringVar,
        listen_cmd: Callable[[], None],
        *,
        empty_as: str | None = None,
        display_format: Callable[[str], str] | None = None,
    ) -> None:
        fr = tk.Frame(parent)
        fr.pack(fill=tk.X, padx=8, pady=6)
        tk.Label(fr, text=label, width=22, anchor="w").pack(side=tk.LEFT, padx=_SETTINGS_ROW_LABEL_GAP)
        text_lbl = tk.Label(
            fr,
            anchor="w",
            justify="left",
            fg=_SHORTCUT_VALUE_FG,
            wraplength=280,
        )
        text_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        def refresh_var(*_: object) -> None:
            raw = display_var.get().strip()
            if raw:
                shown = display_format(raw) if display_format else raw
                text_lbl.config(text=shown, fg=_SHORTCUT_VALUE_FG)
            elif empty_as is not None:
                text_lbl.config(text=empty_as, fg=_SHORTCUT_MUTED_FG)
            else:
                text_lbl.config(text="", fg=_SHORTCUT_VALUE_FG)

        display_var.trace_add("write", refresh_var)
        refresh_var()

        ttk.Button(fr, text="Listen…", width=12, command=listen_cmd).pack(side=tk.RIGHT)

    @staticmethod
    def _shortcut_listen_hint(saved: str, *, optional_disabled: bool = False) -> str:
        """Human line for Listen dialog ‘current shortcut’ banner."""
        t = saved.strip()
        if t:
            return t
        if optional_disabled:
            return "(none — disabled)"
        return "(not set yet)"

    def _capture_listen_hint(self) -> str:
        cur = self.var_capture_hotkey.get().strip()
        if not cur:
            return "(not set yet)"
        friendly = _capture_token_to_mouse_label(cur.lower())
        return friendly if friendly else _format_hotkey_plain_display(cur)

    def _open_key_listen_dialog(
        self,
        title: str,
        on_capture: _ListenCb,
        *,
        current_display: str,
    ) -> None:
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.resizable(False, False)
        held_modifiers: set[str] = set()

        # Two-value -pady on tk.Label is rejected on some Windows Tk builds; use pack(pady=…) instead.
        tk.Label(dlg, text="Current shortcut", fg="#666").pack(padx=24, pady=(16, 4))
        tk.Label(
            dlg,
            text=current_display,
            justify=tk.CENTER,
            wraplength=400,
        ).pack(padx=24, pady=(0, 14))
        tk.Label(
            dlg,
            text=(
                "Hold Ctrl / Shift / Alt / Win, then press the final key "
                "(same idea as Discord, VS Code, etc.).\nEscape cancels."
            ),
            justify=tk.CENTER,
            wraplength=380,
        ).pack(padx=24, pady=(0, 10))
        tk.Label(dlg, text="Keys are read in this window only.", fg="#777").pack(padx=16, pady=(0, 12))

        def close() -> None:
            try:
                dlg.grab_release()
            except tk.TclError:
                pass
            try:
                dlg.destroy()
            except tk.TclError:
                pass

        def on_key_release(event: tk.Event) -> None:
            n = normalize_modifier_keysym_for_held((event.keysym or "").strip())
            if n:
                held_modifiers.discard(n)

        def on_key_press(event: tk.Event) -> None:
            ks = (event.keysym or "").strip()
            if ks == "Escape":
                close()
                return
            # Track physical modifiers; normalize fixes Windows casings (e.g. control_l).
            mod_id = normalize_modifier_keysym_for_held(ks)
            if mod_id is not None:
                held_modifiers.add(mod_id)
                return
            # Physical set + event.state: Tk often omits Ctrl in held but sets state bits.
            mod_tokens = tk_listen_combine_modifiers(held_modifiers, event)
            hk = tk_key_event_to_hotkey(event, modifier_tokens=mod_tokens)
            if hk:
                on_capture(hk)
                close()

        dlg.bind("<KeyPress>", on_key_press)
        dlg.bind("<KeyRelease>", on_key_release)
        dlg.protocol("WM_DELETE_WINDOW", close)
        dlg.transient(self)
        dlg.after(80, dlg.grab_set)
        dlg.after(120, dlg.focus_force)

    def _sync_capture_mouse_combo_display(self) -> None:
        """Refresh combobox. Must not trigger <<ComboboxSelected>> — that can overwrite
        var_capture_hotkey with a stale mouse pick on Windows when values/set run."""
        if not getattr(self, "_cb_capture_mouse", None):
            return
        cb = self._cb_capture_mouse
        raw_stored = self.var_capture_hotkey.get().strip()
        ml = raw_stored.lower()
        mouse_lbl = _capture_token_to_mouse_label(ml)
        mouse_only = [lbl for lbl, _ in _CAPTURE_MOUSE_CHOICES]

        cb.unbind("<<ComboboxSelected>>")
        try:
            if mouse_lbl:
                cb.configure(values=mouse_only)
                self.var_capture_mouse_combo.set(mouse_lbl)
            else:
                kb_line = (
                    f"Keyboard: {_format_hotkey_plain_display(raw_stored)}"
                    if raw_stored
                    else "Keyboard: (not set — click Listen ↑)"
                )
                cb.configure(values=[kb_line, *mouse_only])
                self.var_capture_mouse_combo.set(kb_line)
        except tk.TclError:
            pass
        finally:
            cb.bind("<<ComboboxSelected>>", self._on_capture_mouse_combo_selected)

    def _on_capture_mouse_combo_selected(self, _evt=None) -> None:
        choice = (self.var_capture_mouse_combo.get() or "").strip()
        if choice.lower().startswith("keyboard"):
            return
        tok = _CAPTURE_LABEL_TO_TOKEN.get(choice)
        if tok:
            self.var_capture_hotkey.set(tok)

    def _listen_capture_hotkey(self) -> None:
        def apply(hk: str) -> None:
            self.var_capture_hotkey.set(hk.strip())

        self._open_key_listen_dialog(
            "Record capture shortcut",
            apply,
            current_display=self._capture_listen_hint(),
        )

    def _listen_exit_hotkey(self) -> None:
        def apply(hk: str) -> None:
            self.var_exit_hotkey.set(hk.strip())

        self._open_key_listen_dialog(
            "Record quit shortcut",
            apply,
            current_display=self._shortcut_listen_hint(self.var_exit_hotkey.get()),
        )

    def _listen_settings_hotkey(self) -> None:
        def apply(hk: str) -> None:
            self.var_settings_hotkey.set(hk.strip())

        self._open_key_listen_dialog(
            "Record Settings shortcut",
            apply,
            current_display=self._shortcut_listen_hint(self.var_settings_hotkey.get()),
        )

    def _listen_lens_hk_resize_w(self) -> None:
        def apply(hk: str) -> None:
            self.var_lens_hk_resize_w.set(hk.strip())

        self._open_key_listen_dialog(
            "Record widen-width shortcut",
            apply,
            current_display=self._shortcut_listen_hint(
                self.var_lens_hk_resize_w.get(),
                optional_disabled=True,
            ),
        )

    def _listen_lens_hk_resize_h_up(self) -> None:
        def apply(hk: str) -> None:
            self.var_lens_hk_resize_h_up.set(hk.strip())

        self._open_key_listen_dialog(
            "Record height-increase shortcut",
            apply,
            current_display=self._shortcut_listen_hint(
                self.var_lens_hk_resize_h_up.get(),
                optional_disabled=True,
            ),
        )

    def _listen_lens_hk_resize_h_dn(self) -> None:
        def apply(hk: str) -> None:
            self.var_lens_hk_resize_h_dn.set(hk.strip())

        self._open_key_listen_dialog(
            "Record height-decrease shortcut",
            apply,
            current_display=self._shortcut_listen_hint(
                self.var_lens_hk_resize_h_dn.get(),
                optional_disabled=True,
            ),
        )

    def _validate(self) -> str | None:
        shape = self.var_lens_shape.get().strip().lower()
        if shape not in ("circle", "square"):
            return 'Lens shape must be "circle" or "square".'
        w = int(self.var_lens_width.get())
        h = int(self.var_lens_height.get())
        if w < 100 or w > 800:
            return "Lens width must be between 100 and 800."
        if h < 100 or h > 800:
            return "Lens height must be between 100 and 800."
        lo = float(self.var_lens_opacity.get())
        if lo < 0.25 or lo > 1.0:
            return "Lens opacity must be between 0.25 and 1.0."
        lbw = int(self.var_lens_border.get())
        if lbw < 1 or lbw > 20:
            return "Lens border line must be between 1 and 20."
        for lbl, getter in (
            ("Lens widen-width shortcut", lambda: self.var_lens_hk_resize_w.get()),
            ("Lens height-increase shortcut", lambda: self.var_lens_hk_resize_h_up.get()),
            ("Lens height-decrease shortcut", lambda: self.var_lens_hk_resize_h_dn.get()),
        ):
            hk_raw = getter().strip()
            if not hk_raw:
                continue
            verr = validate_keyboard_hotkey_string(hk_raw)
            if verr:
                return f"{lbl}: {verr}"

        self._ensure_lens_wheel_mod_vars()
        wwm = normalize_lens_wheel_mod(self.var_lens_wheel_mod_width.get())
        whm = normalize_lens_wheel_mod(self.var_lens_wheel_mod_height.get())
        if wwm == whm:
            return "Lens mouse wheel: choose two different modifiers for width and height (e.g. Alt and Shift)."

        op = float(self.var_popup_opacity.get())
        if op < 0.25 or op > 1.0:
            return "Popup opacity must be between 0.25 and 1.0."
        rb = int(self.var_popup_border_radius.get())
        if rb < 0 or rb > 48:
            return "Popup corner radius must be between 0 and 48."
        pbw = int(self.var_popup_border_width.get())
        if pbw < 0 or pbw > 16:
            return "Popup border line must be between 0 and 16."
        wbm = self.var_popup_wrap_mode.get().strip().lower()
        if wbm not in ("word", "char"):
            return 'Popup word break must be "word" or "char".'
        pox = int(self.var_popup_mouse_offset_x.get())
        poy = int(self.var_popup_mouse_offset_y.get())
        if pox < -2000 or pox > 2000:
            return "Popup mouse offset X must be between -2000 and 2000."
        if poy < -2000 or poy > 2000:
            return "Popup mouse offset Y must be between -2000 and 2000."
        if not self.var_ai_url.get().strip():
            return "API base URL cannot be empty."
        tpl = self.txt_translate.get("1.0", "end")
        if "{text}" not in tpl:
            return 'Translation prompt must include the literal placeholder {text}.'
        if not self.var_source_lang.get().strip():
            return "Source language cannot be empty."
        if not self.var_target_lang.get().strip():
            return "Target language cannot be empty."
        pl = self.var_ocr_paddle_lang.get().strip() or "en"
        if not re.match(r"^[A-Za-z0-9_]+$", pl):
            return "Paddle language code must contain only letters, digits, or underscore."
        qh = validate_keyboard_hotkey_string(self.var_exit_hotkey.get().strip())
        if qh:
            return f"Quit shortcut: {qh}"
        sh_raw = self.var_settings_hotkey.get().strip()
        if not sh_raw:
            return "Settings shortcut missing — use Listen to set it."
        sh = validate_keyboard_hotkey_string(sh_raw)
        if sh:
            return f"Settings shortcut: {sh}"
        cap = self.var_capture_hotkey.get().strip()
        if not cap:
            return "Capture trigger missing — use Listen or pick a mouse button."
        if cap.lower() not in _CAPTURE_MOUSE_TOKEN_SET:
            cap_err = validate_keyboard_hotkey_string(cap)
            if cap_err:
                return f"Capture shortcut: {cap_err}"
        return None

    def _merge_lens_into_config(self, d: dict) -> None:
        ls = self.var_lens_shape.get().strip().lower()
        d["lens_shape"] = ls if ls in ("circle", "square") else "circle"
        lw = int(self.var_lens_width.get())
        lh = int(self.var_lens_height.get())
        d["lens_width"] = lw
        d["lens_height"] = lh
        d["lens_radius"] = max(MIN_RADIUS, min(MAX_RADIUS, max(lw, lh) // 2))
        d["lens_color"] = self.var_lens_color.get().strip()
        d["lens_border_width"] = int(self.var_lens_border.get())
        d["lens_opacity"] = float(self.var_lens_opacity.get())
        d["lens_hotkey_resize_width"] = self.var_lens_hk_resize_w.get().strip()
        d["lens_hotkey_resize_height_up"] = self.var_lens_hk_resize_h_up.get().strip()
        d["lens_hotkey_resize_height_down"] = self.var_lens_hk_resize_h_dn.get().strip()

        self._ensure_lens_wheel_mod_vars()
        wm = normalize_lens_wheel_mod(self.var_lens_wheel_mod_width.get())
        hm = normalize_lens_wheel_mod(self.var_lens_wheel_mod_height.get())
        if wm == hm:
            hm = next(t for t in ("shift", "alt", "ctrl", "win") if t != wm)
        d["lens_wheel_mod_width"] = wm
        d["lens_wheel_mod_height"] = hm

    def _assemble_dict(self) -> dict:
        d = copy.deepcopy(self._data)

        self._merge_lens_into_config(d)

        d["popup_font_size"] = int(self.var_popup_font.get())
        d["popup_auto_close_ms"] = int(self.var_popup_close.get())
        d["popup_opacity"] = float(self.var_popup_opacity.get())
        d["popup_bg_color"] = self.var_popup_bg.get().strip()
        d["popup_accent_color"] = self.var_popup_accent.get().strip()
        d["popup_translation_fg"] = self.var_popup_trans.get().strip()
        d["popup_max_width"] = int(self.var_popup_maxw.get())
        d["popup_border_radius"] = int(self.var_popup_border_radius.get())
        d["popup_border_width"] = int(self.var_popup_border_width.get())
        d["popup_wrap_mode"] = self.var_popup_wrap_mode.get().strip().lower()
        d["popup_mouse_offset_x"] = int(self.var_popup_mouse_offset_x.get())
        d["popup_mouse_offset_y"] = int(self.var_popup_mouse_offset_y.get())
        d["popup_quick_append"] = bool(self.var_popup_quick_append.get())
        d.pop("popup_mouse_gap_px", None)

        d["ai_url"] = self.var_ai_url.get().strip()
        d["model"] = self.var_model.get().strip()

        d.setdefault("translate", {})
        tr_int_new: dict = {"provider": self._translate_provider_key_from_ui()}
        _tk = self.var_translate_api_key.get().strip()
        if _tk:
            tr_int_new["api_key"] = _tk
        else:
            _old_tr = (self._data.get("translate") or {}).get("integration") or {}
            if _old_tr.get("api_key"):
                tr_int_new["api_key"] = _old_tr["api_key"]
        d["translate"]["integration"] = tr_int_new
        self._persist_profile_from_editor()
        d["translate"]["series_profiles"] = copy.deepcopy(self._series_profiles)
        d["translate"]["active_series"] = (
            "" if self._series_active_key == "" else self._series_active_key
        )
        if self._series_active_key == "":
            mirror_ctx = ""
            mirror_sn = ""
        else:
            act = self._series_profiles.get(self._series_active_key)
            mirror_ctx = profile_system_context(act) if isinstance(act, dict) else ""
            mirror_sn = (
                str(act.get("series_name", "")).strip()
                if isinstance(act, dict)
                else ""
            )
        d["translate"]["prompt"] = self.txt_translate.get("1.0", "end").rstrip("\n")
        d["translate"]["source_lang"] = self.var_source_lang.get().strip() or "English"
        d["translate"]["target_lang"] = self.var_target_lang.get().strip() or "Thai"
        d["translate"]["context"] = mirror_ctx or ""
        d["translate"]["series_name"] = mirror_sn
        eff_tr = (_load_effective_config_dict().get("translate") or {})
        if "quick_translate" in eff_tr:
            d["translate"]["quick_translate"] = bool(eff_tr["quick_translate"])

        ocr_engine = self._ocr_engine_from_ui()
        ai_int: dict = {"provider": self._ai_ocr_backend_key_from_ui()}
        if self._ai_ocr_backend_key_from_ui() != "inherit":
            _bu = self.var_ai_ocr_base_url.get().strip()
            if _bu:
                ai_int["base_url"] = _bu
        _ak = self.var_ai_ocr_api_key.get().strip()
        if _ak:
            ai_int["api_key"] = _ak
        else:
            _old_ai = (self._data.get("ai_ocr") or {}).get("integration") or {}
            if _old_ai.get("api_key"):
                ai_int["api_key"] = _old_ai["api_key"]
        d["ai_ocr"] = {
            "enabled": ocr_engine == "ai_vision",
            "model": self.var_ai_ocr_model.get().strip(),
            "prompt": self.txt_ai_ocr.get("1.0", "end").rstrip("\n"),
            "debug": bool(self.var_ai_ocr_debug.get()),
            "integration": ai_int,
        }

        olm_int: dict = {"provider": self._olm_backend_key_from_ui()}
        _old_olm = (self._data.get("olm_ocr") or {})
        _ok = self.var_olm_api_key.get().strip()
        _olm_backend = self._olm_backend_key_from_ui()
        _olm_url_saved = (
            self.var_ai_url.get().strip()
            if _olm_backend == "inherit"
            else self.var_olm_url.get().strip()
        )
        _olm_row = {
            "url": _olm_url_saved,
            "model": self.var_olm_model.get().strip(),
            "prompt": self.txt_olm_ocr.get("1.0", "end").rstrip("\n"),
            "debug": bool(self.var_olm_debug.get()),
            "integration": olm_int,
        }
        if _ok:
            _olm_row["api_key"] = _ok
        elif _old_olm.get("api_key"):
            _olm_row["api_key"] = _old_olm["api_key"]
        d["olm_ocr"] = _olm_row

        d["ocr"] = {
            "engine": ocr_engine,
            "upscale": int(self.var_ocr_upscale.get()),
            "contrast": float(self.var_ocr_contrast.get()),
            "sharpness": float(self.var_ocr_sharp.get()),
            "binarize": bool(self.var_ocr_binarize.get()),
            "text_threshold": float(self.var_ocr_thr.get()),
            "low_text": float(self.var_ocr_low.get()),
            "link_threshold": float(self.var_ocr_link.get()),
            "mag_ratio": float(self.var_ocr_mag.get()),
            "min_size": int(self.var_ocr_min.get()),
            "fix_case": bool(self.var_ocr_fix_case.get()),
            "debug": bool(self.var_ocr_debug.get()),
            "paddle_lang": self.var_ocr_paddle_lang.get().strip() or "en",
        }

        d["debug"] = bool(self.var_debug.get())
        d["show_exit_button"] = bool(self.var_show_exit.get())
        d.pop("block_desktop_clicks", None)
        d.pop("block_desktop_opacity", None)
        d["exit_hotkey"] = self.var_exit_hotkey.get().strip()
        d["settings_hotkey"] = self.var_settings_hotkey.get().strip() or "f12"
        d.pop("lens_settings_hotkey", None)
        d["capture_hotkey"] = self.var_capture_hotkey.get().strip() or "middle_click"
        d.pop("hotkey", None)

        return d

    def _save(self):
        err = self._validate()
        if err:
            messagebox.showerror("Settings", err, parent=self)
            return
        data = self._assemble_dict()
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write("\n")
        except OSError as e:
            messagebox.showerror("Settings", f"Could not save config:\n{e}", parent=self)
            return
        self._on_save(data)
        self.destroy()
