"""Modal configuration editor for config.json."""

from __future__ import annotations

import copy
import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Callable

from app.hotkeys import (
    config_capture_trigger_raw,
    normalize_lens_wheel_mod,
    normalize_modifier_keysym_for_held,
    tk_key_event_to_hotkey,
    tk_listen_combine_modifiers,
    validate_keyboard_hotkey_string,
)

_ListenCb = Callable[[str], None]

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.json"

# tk.Label default fg is often "" before map; config(fg="") can hide text on Windows.
_SHORTCUT_VALUE_FG = "#1a1a1a"
_SHORTCUT_MUTED_FG = "#666666"

_CAPTURE_MOUSE_CHOICES: list[tuple[str, str]] = [
    ("Middle mouse button", "middle_click"),
    ("Left mouse button", "left_click"),
    ("Right mouse button", "right_click"),
    ("Mouse side / back (X1)", "mouse_x1"),
    ("Mouse side / forward (X2)", "mouse_x2"),
]

_CAPTURE_LABEL_TO_TOKEN = {label: token for label, token in _CAPTURE_MOUSE_CHOICES}
_CAPTURE_MOUSE_TOKEN_SET = {token.lower() for _, token in _CAPTURE_MOUSE_CHOICES}.union(
    {"x1", "x2", "back", "forward"}
)


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
        *,
        panel_mode: str = "full",
    ):
        super().__init__(root)
        self._on_save = on_save
        self._data = copy.deepcopy(initial)
        self._lens_only = panel_mode == "lens_only"

        self.resizable(True, True)

        btn_fr = tk.Frame(self)
        btn_fr.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=8)
        ttk.Button(btn_fr, text="Save", command=self._save).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(btn_fr, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)

        viewport = tk.Frame(self)
        viewport.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=0, pady=(8, 0))

        if self._lens_only:
            self.title("Manga Translator — Lens")
            self.minsize(480, 440)
            inner, _canvas = self._scroll_viewport(viewport)
            padded = tk.Frame(inner, padx=12, pady=(4, 12))
            padded.pack(fill=tk.BOTH, expand=True)
            self._populate_lens_form(padded)
        else:
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

            self._tab_lens(nb)
            self._tab_popup(nb)
            self._tab_ai(nb)
            self._tab_ai_ocr(nb)
            self._tab_easyocr(nb)
            self._tab_general(nb)

            nb.bind("<<NotebookTabChanged>>", _notebook_scroll_sync)
            self.after(150, _notebook_scroll_sync)

        # Do NOT transient() to withdrawn root Tk() — prevents mapping on some Windows setups.
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        if self._lens_only:
            w = min(580, sw - 48)
            h = min(620, sh - 80)
        else:
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
        tk.Label(fr, text=label, width=18, anchor="w").pack(side=tk.LEFT)
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
        tk.Label(shape_row, text="Lens shape:", width=18, anchor="w").pack(side=tk.LEFT)
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
            from_=100,
            to=800,
            resolution=10,
            length=400,
        ).pack(fill=tk.X, padx=8, pady=4)
        tk.Label(self._lens_wh_fr, text="Height:", anchor="w").pack(fill=tk.X, padx=10, pady=(4, 0))
        tk.Scale(
            self._lens_wh_fr,
            variable=self.var_lens_height,
            orient=tk.HORIZONTAL,
            from_=100,
            to=800,
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

        if self._lens_only:
            self._build_lens_resize_hotkeys_ui(tab)

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
        tk.Label(row, text="Font size:", width=14, anchor="w").pack(side=tk.LEFT)
        self.var_popup_font = tk.IntVar(value=int(self._data.get("popup_font_size", 14)))
        tk.Spinbox(row, from_=8, to=32, textvariable=self.var_popup_font, width=8).pack(side=tk.LEFT)

        row2 = tk.Frame(gf)
        row2.pack(fill=tk.X, padx=8, pady=4)
        tk.Label(row2, text="Auto-close (ms):", width=14, anchor="w").pack(side=tk.LEFT)
        self.var_popup_close = tk.IntVar(value=int(self._data.get("popup_auto_close_ms", 15000)))
        tk.Spinbox(row2, from_=1000, to=600000, increment=500, textvariable=self.var_popup_close, width=10).pack(
            side=tk.LEFT
        )

        row3 = tk.Frame(gf)
        row3.pack(fill=tk.X, padx=8, pady=8)
        tk.Label(row3, text="Max text width:", width=14, anchor="w").pack(side=tk.LEFT)
        self.var_popup_maxw = tk.IntVar(value=int(self._data.get("popup_max_width", 480)))
        tk.Spinbox(row3, from_=240, to=900, increment=10, textvariable=self.var_popup_maxw, width=8).pack(
            side=tk.LEFT
        )

        lay = tk.LabelFrame(tab, text="Layout & rounding")
        lay.pack(fill=tk.X, pady=(8, 0))

        row_r = tk.Frame(lay)
        row_r.pack(fill=tk.X, padx=8, pady=6)
        tk.Label(row_r, text="Corner radius (px):", width=14, anchor="w").pack(side=tk.LEFT)
        self.var_popup_border_radius = tk.IntVar(value=int(self._data.get("popup_border_radius", 6)))
        tk.Spinbox(row_r, from_=0, to=48, textvariable=self.var_popup_border_radius, width=8).pack(side=tk.LEFT)

        row_outline = tk.Frame(lay)
        row_outline.pack(fill=tk.X, padx=8, pady=(0, 6))
        tk.Label(row_outline, text="Border line (px):", width=14, anchor="w").pack(side=tk.LEFT)
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
        tk.Label(row_wb, text="Word break:", width=14, anchor="w").pack(side=tk.LEFT)
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

    def _tab_ai(self, nb: ttk.Notebook):
        tab = tk.Frame(nb, padx=12, pady=12)
        nb.add(tab, text="AI / Translate")

        self.var_ai_url = tk.StringVar(value=str(self._data.get("ai_url", "http://localhost:12434")))
        self.var_model = tk.StringVar(value=str(self._data.get("model", "")))

        for label, var in (
            ("AI base URL:", self.var_ai_url),
            ("Translation model:", self.var_model),
        ):
            fr = tk.Frame(tab)
            fr.pack(fill=tk.X, pady=(0, 6))
            tk.Label(fr, text=label, width=18, anchor="w").pack(side=tk.LEFT)
            tk.Entry(fr, textvariable=var).pack(side=tk.LEFT, fill=tk.X, expand=True)

        lf = tk.LabelFrame(tab, text='Translation prompt  (must contain {text})')
        lf.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self.txt_translate = ScrolledText(lf, height=11, wrap=tk.WORD, font=("Consolas", 10))
        self.txt_translate.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        prompt = (self._data.get("translate") or {}).get(
            "prompt",
            "Translate the following English text to Thai. Reply with only the Thai translation, nothing else.\n\n{text}",
        )
        self.txt_translate.insert("1.0", prompt)

    def _tab_ai_ocr(self, nb: ttk.Notebook):
        tab = tk.Frame(nb, padx=12, pady=12)
        nb.add(tab, text="AI OCR")
        ai = self._data.get("ai_ocr") or {}

        self.var_ai_ocr_en = tk.BooleanVar(value=bool(ai.get("enabled", False)))
        tk.Checkbutton(tab, text="Use vision model for OCR instead of EasyOCR", variable=self.var_ai_ocr_en).pack(
            anchor="w", pady=(0, 8)
        )

        self.var_ai_ocr_model = tk.StringVar(value=str(ai.get("model", "")))
        fr = tk.Frame(tab)
        fr.pack(fill=tk.X, pady=(0, 6))
        tk.Label(fr, text="Vision model:", width=18, anchor="w").pack(side=tk.LEFT)
        tk.Entry(fr, textvariable=self.var_ai_ocr_model).pack(side=tk.LEFT, fill=tk.X, expand=True)

        lf = tk.LabelFrame(tab, text="Vision OCR prompt")
        lf.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.txt_ai_ocr = ScrolledText(lf, height=8, wrap=tk.WORD, font=("Consolas", 10))
        self.txt_ai_ocr.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.txt_ai_ocr.insert("1.0", ai.get("prompt", ""))

        self.var_ai_ocr_debug = tk.BooleanVar(value=bool(ai.get("debug", False)))
        tk.Checkbutton(tab, text="AI OCR debug dumps", variable=self.var_ai_ocr_debug).pack(anchor="w", pady=(8, 0))

    def _tab_easyocr(self, nb: ttk.Notebook):
        tab = tk.Frame(nb, padx=12, pady=12)
        nb.add(tab, text="EasyOCR")
        o = self._data.get("ocr") or {}

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
            fr = tk.Frame(tab)
            fr.grid(row=i, column=0, sticky="ew", pady=2)
            tk.Label(fr, text=name + ":", width=16, anchor="w").pack(side=tk.LEFT)
            if is_int:
                tk.Spinbox(fr, from_=lo, to=hi, textvariable=var, width=12).pack(side=tk.LEFT)
            else:
                tk.Spinbox(fr, from_=lo, to=hi, increment=inc, textvariable=var, width=12).pack(side=tk.LEFT)

        tk.Checkbutton(tab, text="Binarize", variable=self.var_ocr_binarize).grid(row=len(specs), column=0, sticky="w")
        tk.Checkbutton(tab, text="Fix case (manga caps)", variable=self.var_ocr_fix_case).grid(
            row=len(specs) + 1, column=0, sticky="w", pady=(4, 0)
        )
        tk.Checkbutton(tab, text="EasyOCR debug dumps", variable=self.var_ocr_debug).grid(
            row=len(specs) + 2, column=0, sticky="w", pady=(4, 0)
        )

    def _tab_general(self, nb: ttk.Notebook):
        tab = tk.Frame(nb, padx=12, pady=12)
        nb.add(tab, text="General")

        self.var_debug = tk.BooleanVar(value=bool(self._data.get("debug", False)))
        tk.Checkbutton(tab, text='Global debug (also enables OCR debug unless disabled in OCR tabs)', variable=self.var_debug).pack(anchor="w")

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
        self.var_lens_settings_hotkey = tk.StringVar(
            value=str(self._data.get("lens_settings_hotkey", "f11")),
        )

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
        tk.Label(cap_mouse_fr, text="Capture (mouse menu):", width=22, anchor="w").pack(side=tk.LEFT)
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
        self._shortcut_listen_row(hk_fr, "Quick Lens settings:", self.var_lens_settings_hotkey, self._listen_lens_settings_hotkey)
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
        tk.Label(fr, text=label, width=22, anchor="w").pack(side=tk.LEFT)
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
        tk.Label(fr, text=label, width=22, anchor="w").pack(side=tk.LEFT)
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

    def _listen_lens_settings_hotkey(self) -> None:
        def apply(hk: str) -> None:
            self.var_lens_settings_hotkey.set(hk.strip())

        self._open_key_listen_dialog(
            "Record quick Lens-settings shortcut",
            apply,
            current_display=self._shortcut_listen_hint(self.var_lens_settings_hotkey.get()),
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

        if self._lens_only:
            return None

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
        if not self.var_ai_url.get().strip():
            return "AI base URL cannot be empty."
        tpl = self.txt_translate.get("1.0", "end")
        if "{text}" not in tpl:
            return 'Translation prompt must include the literal placeholder {text}.'
        qh = validate_keyboard_hotkey_string(self.var_exit_hotkey.get().strip())
        if qh:
            return f"Quit shortcut: {qh}"
        sh_raw = self.var_settings_hotkey.get().strip()
        if not sh_raw:
            return "Settings shortcut missing — use Listen to set it."
        sh = validate_keyboard_hotkey_string(sh_raw)
        if sh:
            return f"Settings shortcut: {sh}"
        lsh_raw = self.var_lens_settings_hotkey.get().strip()
        if not lsh_raw:
            return "Quick Lens-settings shortcut missing — use Listen to set it."
        lsh = validate_keyboard_hotkey_string(lsh_raw)
        if lsh:
            return f"Lens settings shortcut: {lsh}"
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
        d["lens_radius"] = max(50, min(400, max(lw, lh) // 2))
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
        if self._lens_only:
            if str(d.get("capture_hotkey") or "").strip():
                d.pop("hotkey", None)
            return d

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

        d["ai_url"] = self.var_ai_url.get().strip()
        d["model"] = self.var_model.get().strip()

        d.setdefault("translate", {})
        d["translate"]["prompt"] = self.txt_translate.get("1.0", "end").rstrip("\n")

        d["ai_ocr"] = {
            "enabled": bool(self.var_ai_ocr_en.get()),
            "model": self.var_ai_ocr_model.get().strip(),
            "prompt": self.txt_ai_ocr.get("1.0", "end").rstrip("\n"),
            "debug": bool(self.var_ai_ocr_debug.get()),
        }

        d["ocr"] = {
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
        }

        d["debug"] = bool(self.var_debug.get())
        d["show_exit_button"] = bool(self.var_show_exit.get())
        d.pop("block_desktop_clicks", None)
        d.pop("block_desktop_opacity", None)
        d["exit_hotkey"] = self.var_exit_hotkey.get().strip()
        d["settings_hotkey"] = self.var_settings_hotkey.get().strip() or "f12"
        d["lens_settings_hotkey"] = self.var_lens_settings_hotkey.get().strip() or "f11"
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
