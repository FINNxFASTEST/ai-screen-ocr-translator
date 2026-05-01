import tkinter as tk

BG_COLOR = "#1e1e1e"
ORIGINAL_COLOR = "#888888"
THAI_COLOR = "#ffffff"
BORDER_COLOR = "#00ff88"
PADDING = 16
MAX_WIDTH = 480


class TranslationPopup:
    def __init__(self, root: tk.Tk, original: str, translated: str,
                 cx: int, cy: int, config: dict):
        self.root = root
        self.font_size = config.get("popup_font_size", 14)
        self.auto_close_ms = config.get("popup_auto_close_ms", 15000)
        self._after_id = None

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.config(bg=BORDER_COLOR)

        frame = tk.Frame(self.win, bg=BG_COLOR, padx=PADDING, pady=PADDING)
        frame.pack(padx=2, pady=2)

        # Original text label
        orig_label = tk.Label(
            frame,
            text="Original:",
            font=("Segoe UI", self.font_size - 3, "bold"),
            fg=BORDER_COLOR,
            bg=BG_COLOR,
            anchor="w",
        )
        orig_label.pack(fill=tk.X)

        orig_text = tk.Label(
            frame,
            text=original or "(no text detected)",
            font=("Segoe UI", self.font_size - 2),
            fg=ORIGINAL_COLOR,
            bg=BG_COLOR,
            wraplength=MAX_WIDTH,
            justify=tk.LEFT,
            anchor="w",
        )
        orig_text.pack(fill=tk.X, pady=(0, 8))

        # Translation label
        trans_label = tk.Label(
            frame,
            text="Translation:",
            font=("Segoe UI", self.font_size - 3, "bold"),
            fg=BORDER_COLOR,
            bg=BG_COLOR,
            anchor="w",
        )
        trans_label.pack(fill=tk.X)

        trans_text = tk.Label(
            frame,
            text=translated or "(no translation)",
            font=("Segoe UI", self.font_size, "bold"),
            fg=THAI_COLOR,
            bg=BG_COLOR,
            wraplength=MAX_WIDTH,
            justify=tk.LEFT,
            anchor="w",
        )
        trans_text.pack(fill=tk.X, pady=(0, 12))

        close_btn = tk.Button(
            frame,
            text="Close  [Esc]",
            font=("Segoe UI", self.font_size - 3),
            fg=BG_COLOR,
            bg=BORDER_COLOR,
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
