import tkinter as tk
import tkinter.font as tkfont

from PIL import Image, ImageDraw, ImageTk

_DEFAULT_BG = "#1e1e1e"
_DEFAULT_THAI = "#ffffff"
_DEFAULT_ACCENT = "#00ff88"
_DEFAULT_RADIUS = 6
_DEFAULT_BORDER_WIDTH = 1
_MAX_BORDER_WIDTH = 16
PADDING = 12


def _rgb_tuple(color: str) -> tuple[int, int, int]:
    c = color.strip().lstrip("#")
    if len(c) == 6 and all(ch in "0123456789abcdefABCDEF" for ch in c):
        return tuple(int(c[i : i + 2], 16) for i in (0, 2, 4))
    return (30, 30, 30)


def _fit_text_columns(text: str, font: tkfont.Font, ch_w: int, max_width_px: int) -> int:
    """Text width in characters: shrink to content when it fits, else cap at max_width_px."""
    cap = max(8, max_width_px // max(1, ch_w))
    if not (text or "").strip():
        return min(cap, 14)
    widest = max(font.measure(line) for line in text.split("\n"))
    slack = 28  # widget padx + rounding vs font.measure
    if widest + slack <= max_width_px:
        target_px = min(max_width_px, widest + slack)
        cols = max(1, (target_px + ch_w - 1) // ch_w)
        return min(cols, cap)
    return cap


class TranslationPopup:
    def __init__(self, root: tk.Tk, original: str, translated: str,
                 cx: int, cy: int, config: dict):
        self.root = root
        self.font_size = int(config.get("popup_font_size", 14))
        self.auto_close_ms = int(config.get("popup_auto_close_ms", 15000))
        ox = int(config.get("popup_mouse_offset_x", 0))
        if "popup_mouse_offset_y" in config:
            oy = int(config["popup_mouse_offset_y"])
        else:
            oy = int(config.get("popup_mouse_gap_px", 20))
        self._mouse_offset_x = max(-2000, min(2000, ox))
        self._mouse_offset_y = max(-2000, min(2000, oy))

        accent = config.get("popup_accent_color", _DEFAULT_ACCENT)
        bg_col = config.get("popup_bg_color", _DEFAULT_BG)
        trans_fg = config.get("popup_translation_fg", _DEFAULT_THAI)
        max_width_px = int(config.get("popup_max_width", 480))
        border_radius = int(config.get("popup_border_radius", _DEFAULT_RADIUS))
        border_radius = max(0, min(48, border_radius))
        border_width = int(config.get("popup_border_width", _DEFAULT_BORDER_WIDTH))
        border_width = max(0, min(_MAX_BORDER_WIDTH, border_width))
        opacity = float(config.get("popup_opacity", 1.0))
        opacity = max(0.25, min(1.0, opacity))

        wrap_mode = str(config.get("popup_wrap_mode", "word")).strip().lower()
        twrap = tk.CHAR if wrap_mode == "char" else tk.WORD

        self._after_id = None
        self._card_photo: ImageTk.PhotoImage | None = None

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        try:
            self.win.attributes("-alpha", opacity)
        except tk.TclError:
            pass

        body = (translated or "").strip()
        display = body or "(no translation)"

        font = tkfont.Font(family="Segoe UI", size=self.font_size)
        ch_w = max(1, font.measure("M"), font.measure("ก"))
        chars_wide = _fit_text_columns(display, font, ch_w, max_width_px)

        txt = tk.Text(
            self.win,
            wrap=twrap,
            width=chars_wide,
            height=3,
            font=font,
            fg=trans_fg,
            bg=bg_col,
            insertbackground=trans_fg,
            bd=0,
            highlightthickness=0,
            padx=2,
            pady=4,
            cursor="arrow",
        )
        txt.insert("1.0", display)
        nl = max(1, int(float(txt.index("end-1c").split(".")[0])))
        txt.configure(height=nl)

        # Text has no -disabledforeground (Label-only). Read-only without DISABLED avoids greyed themes.
        def _block_edit(_evt):
            return "break"

        for _seq in ("<Key>", "<<Paste>>", "<Button-2>"):
            txt.bind(_seq, _block_edit)

        line_h = int(font.metrics("linespace"))
        tw_fallback = max(24, min(max_width_px + 32, chars_wide * ch_w + 24))
        th_fallback = max(line_h + 8, nl * line_h + 16)

        # Map widget off-screen so Tk can compute wrap-aware display lines.
        probe_w = min(max_width_px + 100, max(chars_wide * ch_w + 100, 180))
        self.win.geometry(f"{probe_w}x{max(th_fallback + 120, 200)}+-4000+-4000")
        self.win.update_idletasks()
        txt.pack(padx=PADDING, pady=PADDING)
        self.win.update_idletasks()

        # displaylines counts visual rows including word-wrap — use it to fix height.
        try:
            dl_result = txt.count("1.0", "end", "displaylines")
            dl = dl_result[0] if dl_result else nl
            if dl > nl:
                nl = dl
                txt.configure(height=nl)
                self.win.update_idletasks()
        except tk.TclError:
            pass

        tw_raw = txt.winfo_reqwidth()
        th_raw = txt.winfo_reqheight()
        tw = max(24, min(max_width_px + 32, max(tw_raw, tw_fallback)))
        th = max(th_raw, th_fallback)
        txt.pack_forget()

        card_w = tw + 2 * PADDING
        card_h = th + 2 * PADDING

        r = min(border_radius, card_w // 2, card_h // 2)
        fill = _rgb_tuple(bg_col)
        outline = _rgb_tuple(accent)
        pil = Image.new("RGBA", (max(1, card_w), max(1, card_h)), (0, 0, 0, 0))
        draw = ImageDraw.Draw(pil)
        rect = (0, 0, card_w - 1, card_h - 1)
        if border_width <= 0:
            draw.rounded_rectangle(rect, radius=r, fill=fill + (255,))
        else:
            draw.rounded_rectangle(
                rect,
                radius=r,
                fill=fill + (255,),
                outline=outline + (255,),
                width=border_width,
            )

        # Use a transparent key colour for window corners outside the rounded rect.
        _TRANS_KEY = "#fe01fe"
        pil_rgb = Image.new("RGB", (max(1, card_w), max(1, card_h)), _TRANS_KEY)
        pil_rgb.paste(pil, mask=pil.split()[3])  # alpha-composite onto key colour

        photo = ImageTk.PhotoImage(pil_rgb)
        self._card_photo = photo

        self.win.geometry(f"{card_w}x{card_h}")
        self.win.config(bg=_TRANS_KEY)
        try:
            self.win.attributes("-transparentcolor", _TRANS_KEY)
        except tk.TclError:
            pass

        bg_lbl = tk.Label(
            self.win,
            image=photo,
            borderwidth=0,
            highlightthickness=0,
            bg=_TRANS_KEY,
        )
        bg_lbl.place(x=0, y=0, width=card_w, height=card_h)

        txt.place(x=PADDING, y=PADDING, width=tw, height=th)
        txt.tkraise()

        def _click_close(_):
            self.close()

        self.win.bind("<Escape>", lambda _: self.close())
        for w in (self.win, bg_lbl, txt):
            w.bind("<Button-1>", _click_close)

        self.win.update_idletasks()
        self._position(cx, cy)

        self._after_id = self.root.after(self.auto_close_ms, self.close)

    def _position(self, cx: int, cy: int):
        w = self.win.winfo_width()
        h = self.win.winfo_height()
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()

        x = cx - w // 2 + self._mouse_offset_x
        y = cy + self._mouse_offset_y

        x = max(8, min(x, sw - w - 8))
        y = max(8, min(y, sh - h - 8))

        self.win.geometry(f"+{x}+{y}")
        self.win.focus_force()

    def close(self):
        if self._after_id:
            self.root.after_cancel(self._after_id)
            self._after_id = None
        self._card_photo = None
        try:
            self.win.destroy()
        except tk.TclError:
            pass
