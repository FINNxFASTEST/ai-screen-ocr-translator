import tkinter as tk

_DEFAULT_BG = "#1e1e1e"
_DEFAULT_ORIGINAL = "#888888"
_DEFAULT_THAI = "#ffffff"
_DEFAULT_ACCENT = "#00ff88"
PADDING = 16


class TranslationPopup:
    def __init__(self, root: tk.Tk, original: str, translated: str,
                 cx: int, cy: int, config: dict):
        self.root = root
        self.font_size = int(config.get("popup_font_size", 14))
        self.auto_close_ms = int(config.get("popup_auto_close_ms", 15000))

        accent = config.get("popup_accent_color", _DEFAULT_ACCENT)
        bg_col = config.get("popup_bg_color", _DEFAULT_BG)
        original_fg = config.get("popup_original_fg", _DEFAULT_ORIGINAL)
        trans_fg = config.get("popup_translation_fg", _DEFAULT_THAI)
        max_width = int(config.get("popup_max_width", 480))
        opacity = float(config.get("popup_opacity", 1.0))
        opacity = max(0.25, min(1.0, opacity))

        self._after_id = None

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        try:
            self.win.attributes("-alpha", opacity)
        except tk.TclError:
            pass
        self.win.config(bg=accent)

        frame = tk.Frame(self.win, bg=bg_col, padx=PADDING, pady=PADDING)
        frame.pack(padx=2, pady=2)

        # Original text label
        orig_label = tk.Label(
            frame,
            text="Original:",
            font=("Segoe UI", self.font_size - 3, "bold"),
            fg=accent,
            bg=bg_col,
            anchor="w",
        )
        orig_label.pack(fill=tk.X)

        orig_text = tk.Label(
            frame,
            text=original or "(no text detected)",
            font=("Segoe UI", self.font_size - 2),
            fg=original_fg,
            bg=bg_col,
            wraplength=max_width,
            justify=tk.LEFT,
            anchor="w",
        )
        orig_text.pack(fill=tk.X, pady=(0, 8))

        # Translation label
        trans_label = tk.Label(
            frame,
            text="Translation:",
            font=("Segoe UI", self.font_size - 3, "bold"),
            fg=accent,
            bg=bg_col,
            anchor="w",
        )
        trans_label.pack(fill=tk.X)

        trans_text = tk.Label(
            frame,
            text=translated or "(no translation)",
            font=("Segoe UI", self.font_size, "bold"),
            fg=trans_fg,
            bg=bg_col,
            wraplength=max_width,
            justify=tk.LEFT,
            anchor="w",
        )
        trans_text.pack(fill=tk.X, pady=(0, 12))

        close_btn = tk.Button(
            frame,
            text="Close  [Esc]",
            font=("Segoe UI", self.font_size - 3),
            fg=bg_col,
            bg=accent,
            activebackground="#00cc66",
            relief=tk.FLAT,
            cursor="hand2",
            command=self.close,
        )
        close_btn.pack(anchor="e")

        self.win.bind("<Escape>", lambda _: self.close())
        self.win.bind("<Button-1>", lambda _: self.close())

        self.win.update_idletasks()
        self._position(cx, cy)

        self._after_id = self.root.after(self.auto_close_ms, self.close)

    def _position(self, cx: int, cy: int):
        w = self.win.winfo_width()
        h = self.win.winfo_height()
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()

        x = cx - w // 2
        y = cy + 20

        x = max(8, min(x, sw - w - 8))
        y = max(8, min(y, sh - h - 8))

        self.win.geometry(f"+{x}+{y}")
        self.win.focus_force()

    def close(self):
        if self._after_id:
            self.root.after_cancel(self._after_id)
            self._after_id = None
        try:
            self.win.destroy()
        except tk.TclError:
            pass
