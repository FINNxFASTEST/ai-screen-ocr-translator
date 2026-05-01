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

from app.hotkeys import tk_key_event_to_hotkey, validate_keyboard_hotkey_string

_ListenCb = Callable[[str], None]

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.json"

_CAPTURE_CUSTOM_LABEL = "Custom keyboard shortcut…"

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


def _all_mouse_aliases() -> dict[str, str]:
    """Map lowercase config token → UI label."""
    aliases: dict[str, str] = {}
    for label, token in _CAPTURE_MOUSE_CHOICES:
        aliases[token.lower()] = label
    aliases["x1"] = "Mouse side / back (X1)"
    aliases["x2"] = "Mouse side / forward (X2)"
    aliases["back"] = "Mouse side / back (X1)"
    aliases["forward"] = "Mouse side / forward (X2)"
    return aliases


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
    def __init__(self, root: tk.Tk, initial: dict, on_save: Callable[[dict], None]):
        super().__init__(root)
        self._on_save = on_save
        self._data = copy.deepcopy(initial)
        self.title("Manga Translator — Settings")
        self.resizable(True, True)
        self.minsize(520, 480)

        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 4))

        self._tab_lens(nb)
        self._tab_popup(nb)
        self._tab_ai(nb)
        self._tab_ai_ocr(nb)
        self._tab_easyocr(nb)
        self._tab_general(nb)

        btn_fr = tk.Frame(self)
        btn_fr.pack(fill=tk.X, padx=8, pady=8)

        ttk.Button(btn_fr, text="Save", command=self._save).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(btn_fr, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)

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

        fr = tk.LabelFrame(tab, text="Lens radius (px) — default / startup size")
        fr.pack(fill=tk.X, pady=(0, 8))
        self.var_lens_radius = tk.IntVar(value=int(self._data.get("lens_radius", 150)))
        tk.Scale(
            fr,
            variable=self.var_lens_radius,
            orient=tk.HORIZONTAL,
            from_=50,
            to=400,
            resolution=10,
            length=400,
        ).pack(fill=tk.X, padx=8, pady=8)

        self.var_lens_color = tk.StringVar(value=str(self._data.get("lens_color", "#00ff88")))
        self._color_picker_row(tab, "Ring color:", self.var_lens_color)

        bw_fr = tk.LabelFrame(tab, text="Ring width (px)")
        bw_fr.pack(fill=tk.X, pady=(8, 0))
        self.var_lens_border = tk.IntVar(value=int(self._data.get("lens_border_width", 3)))
        tk.Spinbox(bw_fr, from_=1, to=12, textvariable=self.var_lens_border, width=10).pack(
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
            text="In-app: hold Shift and scroll wheel to resize lens (50–400 px). Save applies startup default.",
            fg="#666",
            wraplength=520,
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(12, 0))

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
        tk.Checkbutton(tab, text="Show draggable control bar (Exit, Test connection, Settings)", variable=self.var_show_exit).pack(
            anchor="w", pady=(10, 0)
        )

        cap_fr = tk.LabelFrame(tab, text="Capture trigger (run OCR + translate)")
        cap_fr.pack(fill=tk.X, pady=(10, 0))

        presets = [lbl for lbl, _ in _CAPTURE_MOUSE_CHOICES] + [_CAPTURE_CUSTOM_LABEL]
        self.var_capture_preset = tk.StringVar()
        combo = ttk.Combobox(
            cap_fr,
            values=presets,
            textvariable=self.var_capture_preset,
            state="readonly",
            width=44,
        )
        combo.pack(anchor="w", padx=8, pady=(8, 4))
        combo.bind("<<ComboboxSelected>>", self._on_capture_preset_changed)

        row_cap = tk.Frame(cap_fr)
        row_cap.pack(fill=tk.X, padx=8, pady=(0, 8))
        self.var_capture_display = tk.StringVar()
        tk.Label(row_cap, textvariable=self.var_capture_display, anchor="w", justify="left").pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8)
        )
        ttk.Button(row_cap, text="Listen…", width=12, command=self._listen_capture_hotkey).pack(side=tk.LEFT)

        hk0 = str(self._data.get("hotkey", "middle_click")).strip()
        aliases = _all_mouse_aliases()
        preset_label = aliases.get(hk0.lower(), _CAPTURE_CUSTOM_LABEL)
        self.var_capture_preset.set(preset_label)
        self._capture_keyboard_value = hk0.strip() if preset_label == _CAPTURE_CUSTOM_LABEL else ""
        self._refresh_capture_bind_display()

        tk.Label(
            cap_fr,
            text="Mouse = one global click; keyboard = chords while the translator runs. Use Listen—no typing shortcuts here.",
            fg="#555",
            wraplength=520,
            justify=tk.LEFT,
        ).pack(anchor="w", padx=8, pady=(0, 8))

        self.var_exit_hotkey = tk.StringVar(value=str(self._data.get("exit_hotkey", "<ctrl>+<shift>+<alt>+q")))
        self.var_settings_hotkey = tk.StringVar(value=str(self._data.get("settings_hotkey", "f12")))

        hk_fr = tk.LabelFrame(tab, text="Shortcuts (Listen only)")
        hk_fr.pack(fill=tk.X, pady=(10, 0))
        self._shortcut_listen_row(hk_fr, "Quit translator:", self.var_exit_hotkey, self._listen_exit_hotkey)
        self._shortcut_listen_row(hk_fr, "Open Settings:", self.var_settings_hotkey, self._listen_settings_hotkey)

        tk.Label(
            tab,
            text="Listen opens a grab window: press your shortcut (modifiers + key). Escape cancels.",
            fg="#555",
            wraplength=520,
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(12, 0))

    def _shortcut_listen_row(
        self,
        parent: tk.Misc,
        label: str,
        display_var: tk.StringVar,
        listen_cmd: Callable[[], None],
    ) -> None:
        fr = tk.Frame(parent)
        fr.pack(fill=tk.X, padx=8, pady=6)
        tk.Label(fr, text=label, width=22, anchor="w").pack(side=tk.LEFT)
        tk.Label(fr, textvariable=display_var, anchor="w", justify="left").pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8)
        )
        ttk.Button(fr, text="Listen…", width=12, command=listen_cmd).pack(side=tk.RIGHT)

    def _open_key_listen_dialog(self, title: str, on_capture: _ListenCb) -> None:
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.resizable(False, False)
        # Two-value -pady on tk.Label is rejected on some Windows Tk builds; use pack(pady=…) instead.
        tk.Label(
            dlg,
            text="Press the shortcut you want.\nEscape cancels.",
            justify=tk.CENTER,
            wraplength=360,
        ).pack(padx=24, pady=(16, 10))
        tk.Label(dlg, text="Keys are captured in this window.", fg="#777").pack(padx=16, pady=(0, 12))

        def close() -> None:
            try:
                dlg.grab_release()
            except tk.TclError:
                pass
            try:
                dlg.destroy()
            except tk.TclError:
                pass

        def on_key(event: tk.Event) -> None:
            if event.keysym == "Escape":
                close()
                return
            hk = tk_key_event_to_hotkey(event)
            if hk:
                on_capture(hk)
                close()

        dlg.bind("<KeyPress>", on_key)
        dlg.protocol("WM_DELETE_WINDOW", close)
        dlg.transient(self)
        dlg.after(80, dlg.grab_set)
        dlg.after(120, dlg.focus_force)

    def _listen_capture_hotkey(self) -> None:
        def apply(hk: str) -> None:
            self._capture_keyboard_value = hk.strip()
            self.var_capture_preset.set(_CAPTURE_CUSTOM_LABEL)
            self._refresh_capture_bind_display()

        self._open_key_listen_dialog("Record capture shortcut", apply)

    def _listen_exit_hotkey(self) -> None:
        def apply(hk: str) -> None:
            self.var_exit_hotkey.set(hk.strip())

        self._open_key_listen_dialog("Record quit shortcut", apply)

    def _listen_settings_hotkey(self) -> None:
        def apply(hk: str) -> None:
            self.var_settings_hotkey.set(hk.strip())

        self._open_key_listen_dialog("Record Settings shortcut", apply)

    def _refresh_capture_bind_display(self) -> None:
        if self.var_capture_preset.get() == _CAPTURE_CUSTOM_LABEL:
            inner = self._capture_keyboard_value.strip()
            shown = inner if inner else "(Press Listen…)"
        else:
            shown = "(keyboard not used — mouse preset)"
        self.var_capture_display.set(shown)

    def _on_capture_preset_changed(self, _evt=None) -> None:
        self._refresh_capture_bind_display()

    def _capture_hotkey_raw(self) -> str:
        label = self.var_capture_preset.get()
        if label == _CAPTURE_CUSTOM_LABEL:
            return self._capture_keyboard_value.strip()
        return _CAPTURE_LABEL_TO_TOKEN.get(label, "middle_click")

    def _validate(self) -> str | None:
        r = int(self.var_lens_radius.get())
        if r < 50 or r > 400:
            return "Lens radius must be between 50 and 400."
        lo = float(self.var_lens_opacity.get())
        if lo < 0.25 or lo > 1.0:
            return "Lens opacity must be between 0.25 and 1.0."
        op = float(self.var_popup_opacity.get())
        if op < 0.25 or op > 1.0:
            return "Popup opacity must be between 0.25 and 1.0."
        rb = int(self.var_popup_border_radius.get())
        if rb < 0 or rb > 48:
            return "Popup corner radius must be between 0 and 48."
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
        cap = self._capture_hotkey_raw()
        if cap.lower() not in _CAPTURE_MOUSE_TOKEN_SET:
            cap_err = validate_keyboard_hotkey_string(cap)
            if cap_err:
                return f"Capture trigger: {cap_err}"
        return None

    def _assemble_dict(self) -> dict:
        d = copy.deepcopy(self._data)

        d["lens_radius"] = int(self.var_lens_radius.get())
        d["lens_color"] = self.var_lens_color.get().strip()
        d["lens_border_width"] = int(self.var_lens_border.get())
        d["lens_opacity"] = float(self.var_lens_opacity.get())

        d["popup_font_size"] = int(self.var_popup_font.get())
        d["popup_auto_close_ms"] = int(self.var_popup_close.get())
        d["popup_opacity"] = float(self.var_popup_opacity.get())
        d["popup_bg_color"] = self.var_popup_bg.get().strip()
        d["popup_accent_color"] = self.var_popup_accent.get().strip()
        d["popup_translation_fg"] = self.var_popup_trans.get().strip()
        d["popup_max_width"] = int(self.var_popup_maxw.get())
        d["popup_border_radius"] = int(self.var_popup_border_radius.get())
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
        d["exit_hotkey"] = self.var_exit_hotkey.get().strip()
        d["settings_hotkey"] = self.var_settings_hotkey.get().strip() or "f12"
        d["hotkey"] = self._capture_hotkey_raw()

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
