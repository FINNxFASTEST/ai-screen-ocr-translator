from collections.abc import Callable

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk

_DEFAULT_BG = "#1e1e1e"
_DEFAULT_THAI = "#ffffff"
_DEFAULT_ACCENT = "#00ff88"
_DEFAULT_RADIUS = 6
_DEFAULT_BORDER_WIDTH = 1
_MAX_BORDER_WIDTH = 16
PADDING = 12
_QUICK_ICON_COLLAPSED = "+"
_QUICK_ICON_EXPANDED = "\u2212"  # minus sign
# Extra card width (right strip for +/− icon) when quick-append is on.
_QUICK_ICON_STRIP_EXTRA = 42


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


_QUICK_ROW_LABELS = ("Names & glossary", "Series context")
_QUICK_FIELD_BY_LABEL = dict(zip(_QUICK_ROW_LABELS, ("glossary", "context")))


class TranslationPopup:
    def __init__(
        self,
        root: tk.Tk,
        original: str,
        translated: str,
        cx: int,
        cy: int,
        config: dict,
        *,
        series_key: str = "",
        on_quick_append: Callable[[str, str], str] | None = None,
        allow_quick_note: bool = True,
    ):
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

        self._accent_hex = config.get("popup_accent_color", _DEFAULT_ACCENT)
        self._border_radius = max(0, min(48, int(config.get("popup_border_radius", _DEFAULT_RADIUS))))
        self._border_width = max(0, min(_MAX_BORDER_WIDTH, int(config.get("popup_border_width", _DEFAULT_BORDER_WIDTH))))
        self._cfg_bg = config.get("popup_bg_color", _DEFAULT_BG)
        self._cfg_fg = config.get("popup_translation_fg", _DEFAULT_THAI)

        max_width_px = int(config.get("popup_max_width", 480))
        opacity = float(config.get("popup_opacity", 1.0))
        opacity = max(0.25, min(1.0, opacity))

        wrap_mode = str(config.get("popup_wrap_mode", "word")).strip().lower()
        twrap = tk.CHAR if wrap_mode == "char" else tk.WORD

        self._after_id = None
        self._card_photo: ImageTk.PhotoImage | None = None
        self._trans_key = "#fe01fe"
        self._anchor_cx = cx
        self._anchor_cy = cy

        self._expanded = False
        self._quick_gap = 4
        self._quick_actual_h = 0
        self._quick_panel: tk.Frame | None = None
        self._ent_for_focus = None
        self._preset_for_focus = ""

        wants_quick_raw = bool(
            allow_quick_note
            and config.get("popup_quick_append", False)
            and callable(on_quick_append)
            and str(series_key or "").strip()
            and str(original or "").strip()
            and not (translated or "").strip().startswith("[Error")
        )
        self._wants_quick = wants_quick_raw
        self._on_quick_append = on_quick_append
        self._series_key = series_key
        self._original_for_quick = original

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

        self._txt_widget = tk.Text(
            self.win,
            wrap=twrap,
            width=chars_wide,
            height=3,
            font=font,
            fg=self._cfg_fg,
            bg=self._cfg_bg,
            insertbackground=self._cfg_fg,
            bd=0,
            highlightthickness=0,
            padx=2,
            pady=3,
            cursor="arrow",
        )
        self._txt_widget.insert("1.0", display)
        nl = max(1, int(float(self._txt_widget.index("end-1c").split(".")[0])))
        self._txt_widget.configure(height=nl)

        def _block_edit(_evt):
            return "break"

        for _seq in ("<Key>", "<<Paste>>", "<Button-2>"):
            self._txt_widget.bind(_seq, _block_edit)

        line_h = int(font.metrics("linespace"))

        probe_w = min(max_width_px + 100, max(chars_wide * ch_w + 100, 180))
        probe_h_hint = max(nl * line_h + line_h + 80, 120)
        self.win.geometry(f"{probe_w}x{probe_h_hint}+-4000+-4000")
        self.win.update_idletasks()
        self._txt_widget.pack(padx=PADDING, pady=PADDING)
        self.win.update_idletasks()

        try:
            dl_result = self._txt_widget.count("1.0", "end", "displaylines")
            dl = dl_result[0] if dl_result else nl
            if dl > nl:
                nl = dl
                self._txt_widget.configure(height=nl)
                self.win.update_idletasks()
        except tk.TclError:
            pass

        tw_raw = self._txt_widget.winfo_reqwidth()
        th_raw = self._txt_widget.winfo_reqheight()
        # Prefer measured Tk sizes (wrap-aware); cap width; avoid extra vertical slack.
        tw = max(24, min(max_width_px + 32, tw_raw))
        th = max(th_raw, nl * line_h + 6)
        self._txt_widget.pack_forget()

        self._tw = tw
        self._th = th

        strip = _QUICK_ICON_STRIP_EXTRA if wants_quick_raw else 0
        card_w = tw + 2 * PADDING + strip
        self._card_w = card_w

        compact_h = PADDING + th + PADDING

        bg_lbl = self._apply_card_surface(
            card_w,
            compact_h,
            accent=self._accent_hex,
            bg_col=self._cfg_bg,
        )

        self._txt_widget.place(x=PADDING, y=PADDING, width=tw, height=th)
        self._txt_widget.tkraise()

        self._quick_icon_btn: tk.Label | None = None
        if wants_quick_raw:
            ifont = tkfont.Font(family="Segoe UI", size=11, weight="bold")
            self._quick_icon_btn = tk.Label(
                self.win,
                text=_QUICK_ICON_COLLAPSED,
                fg=self._accent_hex,
                bg=self._cfg_bg,
                font=ifont,
                padx=4,
                pady=2,
                cursor="hand2",
            )
            self._quick_icon_btn.bind("<Button-1>", self._on_quick_icon_clicked)
            self.win.update_idletasks()
            self._place_quick_icon()
            self._quick_icon_btn.tkraise()

        self._bg_lbl_widget = bg_lbl

        def _click_close(_):
            self.close()

        self.win.bind("<Escape>", lambda _: self.close())
        for w in (bg_lbl, self._txt_widget):
            w.bind("<Button-1>", _click_close)

        self.win.geometry(f"{card_w}x{compact_h}")
        self.win.config(bg=self._trans_key)
        try:
            self.win.attributes("-transparentcolor", self._trans_key)
        except tk.TclError:
            pass

        self.win.update_idletasks()
        self._position(self._anchor_cx, self._anchor_cy)

        self._after_id = self.root.after(self.auto_close_ms, self.close)

    def _make_card_photo(
        self,
        card_w: int,
        card_h: int,
        *,
        accent: str,
        bg_col: str,
    ) -> ImageTk.PhotoImage:
        r = min(self._border_radius, max(1, card_w // 2), max(1, card_h // 2))
        fill = _rgb_tuple(bg_col)
        outline = _rgb_tuple(accent)
        pil = Image.new("RGBA", (max(1, card_w), max(1, card_h)), (0, 0, 0, 0))
        draw = ImageDraw.Draw(pil)
        rect = (0, 0, card_w - 1, card_h - 1)
        bw = self._border_width
        if bw <= 0:
            draw.rounded_rectangle(rect, radius=r, fill=fill + (255,))
        else:
            draw.rounded_rectangle(
                rect,
                radius=r,
                fill=fill + (255,),
                outline=outline + (255,),
                width=bw,
            )
        pil_rgb = Image.new("RGB", (max(1, card_w), max(1, card_h)), self._trans_key)
        pil_rgb.paste(pil, mask=pil.split()[3])
        return ImageTk.PhotoImage(pil_rgb)

    def _apply_card_surface(
        self,
        card_w: int,
        card_h: int,
        *,
        accent: str,
        bg_col: str,
    ) -> tk.Label:
        photo = self._make_card_photo(card_w, card_h, accent=accent, bg_col=bg_col)
        self._card_photo = photo

        bg_lbl = tk.Label(
            self.win,
            image=photo,
            borderwidth=0,
            highlightthickness=0,
            bg=self._trans_key,
        )
        bg_lbl.place(x=0, y=0, width=card_w, height=card_h)
        bg_lbl.lower()
        return bg_lbl

    def _place_quick_icon(self) -> None:
        """Keep + / − right of the translation column (reserved strip); never atop last glyphs."""
        btn = self._quick_icon_btn
        if btn is None:
            return
        self.win.update_idletasks()
        try:
            iw = max(18, btn.winfo_reqwidth())
        except tk.TclError:
            iw = 28
        gutter = PADDING + self._tw + 6
        x = int(gutter)
        right_most = self._card_w - PADDING - iw
        if x > right_most:
            x = max(PADDING + 4, right_most)
        btn.place(x=x, y=PADDING + 2)

    def _ensure_quick_built(self) -> None:
        if self._quick_panel is not None or not self._wants_quick or not callable(self._on_quick_append):
            return
        inner_w = self._card_w - 2 * PADDING

        preset = ((self._original_for_quick or "").strip())[:500]
        self._preset_for_focus = preset
        accent = self._accent_hex
        bg_col = self._cfg_bg
        trans_fg = self._cfg_fg

        small = tkfont.Font(family="Segoe UI", size=max(9, self.font_size - 2))
        fr = tk.Frame(self.win, bg=bg_col, highlightthickness=0)
        hdr = tk.Frame(fr, bg=bg_col)
        hdr.pack(fill=tk.X, pady=(0, 4))
        tk.Label(hdr, text="Add line to:", bg=bg_col, fg=trans_fg, font=small).pack(side=tk.LEFT, padx=(0, 6))

        var_target = tk.StringVar(value=_QUICK_ROW_LABELS[0])
        ttk.Combobox(
            hdr,
            textvariable=var_target,
            values=list(_QUICK_ROW_LABELS),
            state="readonly",
            width=24,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        ent_local = tk.Entry(
            fr,
            fg=trans_fg,
            bg=bg_col,
            insertbackground=trans_fg,
            font=small,
            bd=1,
            relief=tk.GROOVE,
            highlightthickness=1,
            highlightbackground=accent,
            highlightcolor=accent,
        )
        ent_local.pack(fill=tk.X, pady=(0, 6))
        ent_local.insert(0, preset)

        tk.Label(
            fr,
            text=f'Saves to "{self._series_key}" in config. Full editor: Settings → AI.',
            fg="#8a9ba8",
            bg=bg_col,
            font=small,
            anchor="w",
            wraplength=max(220, inner_w - 16),
            justify="left",
        ).pack(fill=tk.X, pady=(0, 6))

        bar = tk.Frame(fr, bg=bg_col)
        bar.pack(fill=tk.X)
        status_lbl = tk.Label(bar, text="", bg=bg_col, fg=trans_fg, font=small, anchor="w")
        status_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

        def _do_append_local():
            if not callable(self._on_quick_append):
                return
            status_lbl.config(text="", fg=trans_fg)
            pick = var_target.get()
            field_key = _QUICK_FIELD_BY_LABEL.get(pick, "glossary")
            err_msg = self._on_quick_append(field_key, ent_local.get())
            if err_msg:
                status_lbl.config(text=err_msg, fg="#ff7777")
            else:
                status_lbl.config(text="Saved.", fg=accent)

        tk.Button(
            bar,
            text="Append & save",
            command=_do_append_local,
            font=small,
            bg="#2d2d2d",
            fg=trans_fg,
            activebackground="#3d3d3d",
            activeforeground=trans_fg,
            relief=tk.FLAT,
            padx=8,
            pady=2,
        ).pack(side=tk.RIGHT)

        fr.place(in_=self.win, x=-8000, y=0, width=inner_w)
        self.win.update_idletasks()
        qh = fr.winfo_reqheight()
        self._quick_actual_h = qh if qh > 0 else 1
        fr.place_forget()

        self._quick_panel = fr
        self._ent_for_focus = ent_local

    def _collapse_quick(self) -> None:
        compact_h = PADDING + self._th + PADDING

        old_bg = getattr(self, "_bg_lbl_widget", None)
        if old_bg is not None:
            try:
                old_bg.destroy()
            except tk.TclError:
                pass

        bg_lbl = self._apply_card_surface(
            self._card_w,
            compact_h,
            accent=self._accent_hex,
            bg_col=self._cfg_bg,
        )

        self._bg_lbl_widget = bg_lbl

        self._expanded = False
        if self._quick_panel is not None:
            self._quick_panel.place_forget()

        self._txt_widget.place(x=PADDING, y=PADDING, width=self._tw, height=self._th)
        self._txt_widget.tkraise()
        if self._quick_icon_btn is not None:
            self._quick_icon_btn.config(text=_QUICK_ICON_COLLAPSED)
            self.win.update_idletasks()
            self._place_quick_icon()
            self._quick_icon_btn.tkraise()

        def _close(_):
            self.close()

        bg_lbl.bind("<Button-1>", _close)
        for w in (bg_lbl, self._txt_widget):
            try:
                w.bind("<Button-1>", _close)
            except tk.TclError:
                pass

        self.win.geometry(f"{self._card_w}x{compact_h}")
        self.win.update_idletasks()
        self._position(self._anchor_cx, self._anchor_cy)

    def _expand_quick(self) -> None:
        self._ensure_quick_built()
        if self._quick_panel is None:
            return

        qg = self._quick_gap
        qp = self._quick_panel
        iw = self._card_w - 2 * PADDING
        qp.place(in_=self.win, x=-8000, y=0, width=iw)
        self.win.update_idletasks()
        qh = qp.winfo_reqheight()
        if qh > 0:
            self._quick_actual_h = qh
        qp.place_forget()

        expanded_h = PADDING + self._th + qg + self._quick_actual_h + PADDING

        old_bg = getattr(self, "_bg_lbl_widget", None)
        if old_bg is not None:
            try:
                old_bg.destroy()
            except tk.TclError:
                pass

        bg_lbl = self._apply_card_surface(
            self._card_w,
            expanded_h,
            accent=self._accent_hex,
            bg_col=self._cfg_bg,
        )

        self._bg_lbl_widget = bg_lbl
        self._expanded = True

        self._txt_widget.place(x=PADDING, y=PADDING, width=self._tw, height=self._th)
        self._txt_widget.tkraise()

        self._quick_panel.place(x=PADDING, y=PADDING + self._th + qg, width=iw)
        self._quick_panel.tkraise()

        if self._quick_icon_btn is not None:
            self._quick_icon_btn.config(text=_QUICK_ICON_EXPANDED)
            self.win.update_idletasks()
            self._place_quick_icon()
            self._quick_icon_btn.tkraise()

        def _close(_):
            self.close()

        bg_lbl.bind("<Button-1>", _close)
        for w in (bg_lbl, self._txt_widget):
            try:
                w.bind("<Button-1>", _close)
            except tk.TclError:
                pass

        self.win.geometry(f"{self._card_w}x{expanded_h}")
        self.win.update_idletasks()
        self._position(self._anchor_cx, self._anchor_cy)

        fn = getattr(self, "_ent_for_focus", None)
        pref = getattr(self, "_preset_for_focus", "") or ""

        def _focus_entry():
            try:
                if fn is not None:
                    fn.focus_set()
                    fn.icursor(len(pref))
            except tk.TclError:
                pass

        self.win.after(60, _focus_entry)

    def _on_quick_icon_clicked(self, _evt=None):
        if self._expanded:
            self._collapse_quick()
        else:
            self._expand_quick()
        return "break"

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
