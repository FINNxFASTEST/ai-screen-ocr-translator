from collections.abc import Callable
from typing import Any

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
    """Text widget width in character columns: use full max width for wrapped prose; stay compact for one short line."""
    cap = max(8, max_width_px // max(1, ch_w))
    if not (text or "").strip():
        return min(cap, 14)
    lines = text.split("\n")
    widest = max((font.measure(line) for line in lines), default=0)
    slack = 28  # widget padx + rounding vs font.measure
    # Hard line breaks or long wrapped lines: use full reading width so we don't force extra wraps.
    if len(lines) > 1 or widest + slack > max_width_px * 0.72:
        return cap
    # Single short line: narrower card
    if widest + slack <= max_width_px:
        target_px = min(max_width_px, widest + slack)
        cols = max(1, (target_px + ch_w - 1) // ch_w)
        return min(cols, cap)
    return cap


class TranslationPopup:
    def __init__(
        self,
        root: tk.Tk,
        original: str,
        translated: str,
        cx: int,
        cy: int,
        config: dict[str, Any],
        *,
        series_key: str = "",
        on_quick_correction: Callable[[str, str, bool, bool], str] | None = None,
        on_retranslate: Callable[[str], None] | None = None,
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

        max_width_px = int(config.get("popup_max_width", 680))
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
        self._ent_for_focus: tk.Entry | None = None
        self._preset_for_focus = ""
        self._source_fix_widget: tk.Text | None = None

        err = (translated or "").strip().startswith("[Error")
        has_orig = bool(str(original or "").strip())
        self._can_quick_correction = bool(
            allow_quick_note
            and config.get("popup_quick_append", False)
            and callable(on_quick_correction)
            and str(series_key or "").strip()
            and has_orig
            and not err
        )
        self._can_fix = bool(
            allow_quick_note and has_orig and not err and callable(on_retranslate)
        )
        self._wants_expand = self._can_quick_correction or self._can_fix
        self._on_quick_correction = on_quick_correction
        self._on_retranslate = on_retranslate
        self._series_key = series_key
        self._original_for_quick = original
        self._translation_y = PADDING
        self._ocr_preview_cap = max(200, int(config.get("popup_ocr_source_max_chars", 1200)))

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
        content_cap_px = max_width_px + 32
        # Prefer measured Tk sizes (wrap-aware); cap width; avoid extra vertical slack.
        tw_compact = max(24, min(content_cap_px, tw_raw))
        th = max(th_raw, nl * line_h + 6)
        self._txt_widget.pack_forget()

        self._tw_compact = tw_compact
        self._cols_compact = chars_wide
        if self._wants_expand:
            self._tw_expanded = max(tw_compact, content_cap_px)
            self._cols_expanded = max(
                chars_wide, max(1, (content_cap_px + ch_w - 1) // ch_w)
            )
        else:
            self._tw_expanded = tw_compact
            self._cols_expanded = chars_wide

        self._tw = tw_compact
        self._th = th

        strip = _QUICK_ICON_STRIP_EXTRA if self._wants_expand else 0
        self._strip_w = strip
        card_w = tw_compact + 2 * PADDING + strip
        self._card_w = card_w

        compact_h = self._translation_y + th + PADDING

        bg_lbl = self._apply_card_surface(
            card_w,
            compact_h,
            accent=self._accent_hex,
            bg_col=self._cfg_bg,
        )

        self._txt_widget.place(
            x=PADDING, y=self._translation_y, width=tw_compact, height=th
        )
        self._txt_widget.tkraise()

        self._quick_icon_btn: tk.Label | None = None
        if self._wants_expand:
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

        self._schedule_auto_close()

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

    def _apply_compact_dimensions(self) -> None:
        """Narrow translation strip (fits short Thai); used when + is collapsed."""
        if not self._wants_expand:
            return
        self._tw = self._tw_compact
        self._card_w = self._tw_compact + 2 * PADDING + self._strip_w
        self._txt_widget.configure(width=self._cols_compact)

    def _apply_expanded_dimensions(self) -> None:
        """Full popup_max_width strip for quick OCR replacements / correct-English underneath +."""
        if not self._wants_expand:
            return
        self._tw = self._tw_expanded
        self._card_w = self._tw_expanded + 2 * PADDING + self._strip_w
        self._txt_widget.configure(width=self._cols_expanded)

    def _ensure_quick_built(self) -> None:
        if self._quick_panel is not None or not self._wants_expand:
            return
        # Match translation column width (exclude + icon strip — was inflating layout incorrectly).
        inner_w = max(280, self._card_w - 2 * PADDING - self._strip_w)

        preset = ((self._original_for_quick or "").strip())[:500]
        self._preset_for_focus = preset
        accent = self._accent_hex
        bg_col = self._cfg_bg
        trans_fg = self._cfg_fg

        small = tkfont.Font(family="Segoe UI", size=max(9, self.font_size - 2))
        fr = tk.Frame(self.win, bg=bg_col, highlightthickness=0)

        oc_raw = str(self._original_for_quick or "").strip()
        muted = "#9aafbf"
        # Read-only OCR line only under + ; skip if editable "Correct English" box is shown.
        if oc_raw and not oc_raw.lower().startswith("(no text") and not self._can_fix:
            n = len(oc_raw)
            cap = self._ocr_preview_cap
            preview = oc_raw if n <= cap else oc_raw[: cap - 1] + "…"
            tk.Label(
                fr,
                text=f"Source (English) — OCR / sent to translator ({n} chars)",
                bg=bg_col,
                fg=trans_fg,
                font=small,
                anchor="w",
            ).pack(fill=tk.X, pady=(0, 2))
            tk.Label(
                fr,
                text=preview,
                bg=bg_col,
                fg=muted,
                font=small,
                anchor="w",
                justify=tk.LEFT,
                wraplength=max(220, inner_w - 16),
            ).pack(fill=tk.X, pady=(0, 8))

        if self._can_quick_correction:
            tk.Label(
                fr,
                text="Add OCR replacement (active Reading profile):",
                bg=bg_col,
                fg=trans_fg,
                font=small,
                anchor="w",
            ).pack(fill=tk.X, pady=(0, 4))

            row_m = tk.Frame(fr, bg=bg_col)
            row_m.pack(fill=tk.X, pady=(0, 4))
            tk.Label(row_m, text="Match:", bg=bg_col, fg=trans_fg, font=small, width=10, anchor="w").pack(
                side=tk.LEFT, padx=(0, 4)
            )
            ent_match = tk.Entry(
                row_m,
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
            ent_match.pack(side=tk.LEFT, fill=tk.X, expand=True)

            row_r = tk.Frame(fr, bg=bg_col)
            row_r.pack(fill=tk.X, pady=(0, 4))
            tk.Label(row_r, text="Replace:", bg=bg_col, fg=trans_fg, font=small, width=10, anchor="w").pack(
                side=tk.LEFT, padx=(0, 4)
            )
            ent_replace = tk.Entry(
                row_r,
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
            ent_replace.pack(side=tk.LEFT, fill=tk.X, expand=True)

            opts_fr = tk.Frame(fr, bg=bg_col)
            opts_fr.pack(fill=tk.X, pady=(2, 2))
            var_whole = tk.BooleanVar(value=True)
            tk.Checkbutton(
                opts_fr,
                text="Whole word",
                variable=var_whole,
                bg=bg_col,
                fg=trans_fg,
                activebackground=bg_col,
                activeforeground=trans_fg,
                selectcolor=bg_col,
                anchor="w",
                font=small,
            ).pack(side=tk.LEFT, padx=(0, 16))
            var_match_case = tk.BooleanVar(value=False)
            tk.Checkbutton(
                opts_fr,
                text="Match case (e.g. name Aerial, not word aerial)",
                variable=var_match_case,
                bg=bg_col,
                fg=trans_fg,
                activebackground=bg_col,
                activeforeground=trans_fg,
                selectcolor=bg_col,
                anchor="w",
                font=small,
            ).pack(side=tk.LEFT)

            tk.Label(
                fr,
                text=(
                    f'Saved into Settings → Translation → OCR replacements for '
                    f'"{self._series_key}". Same match options update the rule.'
                ),
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

            def _save_rule_local():
                if not callable(self._on_quick_correction):
                    return
                status_lbl.config(text="", fg=trans_fg)
                m = ent_match.get().strip()
                r_raw = ent_replace.get()
                err_msg = self._on_quick_correction(
                    m, r_raw, var_whole.get(), var_match_case.get()
                )
                if err_msg:
                    status_lbl.config(text=err_msg, fg="#ff7777")
                else:
                    status_lbl.config(text="Saved.", fg=accent)

            tk.Button(
                bar,
                text="Save rule",
                command=_save_rule_local,
                font=small,
                bg="#2d2d2d",
                fg=trans_fg,
                activebackground="#3d3d3d",
                activeforeground=trans_fg,
                relief=tk.FLAT,
                padx=8,
                pady=2,
            ).pack(side=tk.RIGHT)

            ent_match.insert(0, preset)
            self._ent_for_focus = ent_match

        if self._can_quick_correction and self._can_fix:
            tk.Frame(fr, height=8, bg=bg_col).pack(fill=tk.X)

        if self._can_fix and callable(self._on_retranslate):
            tk.Label(
                fr,
                text="Correct English (OCR), then re-translate:",
                bg=bg_col,
                fg=trans_fg,
                font=small,
                anchor="w",
            ).pack(fill=tk.X, pady=(0, 4))

            src_text = tk.Text(
                fr,
                height=4,
                wrap=tk.WORD,
                font=small,
                fg=trans_fg,
                bg=bg_col,
                insertbackground=trans_fg,
                bd=1,
                relief=tk.GROOVE,
                highlightthickness=1,
                highlightbackground=accent,
                highlightcolor=accent,
                padx=4,
                pady=4,
            )
            src_text.pack(fill=tk.BOTH, expand=True)
            src_text.insert("1.0", (self._original_for_quick or "").strip())

            bar_rt = tk.Frame(fr, bg=bg_col)
            bar_rt.pack(fill=tk.X, pady=(6, 0))
            rt_status = tk.Label(bar_rt, text="", bg=bg_col, fg=trans_fg, font=small, anchor="w")
            rt_status.pack(side=tk.LEFT, fill=tk.X, expand=True)

            def _do_retranslate_local():
                raw = src_text.get("1.0", "end").strip()
                if not raw:
                    rt_status.config(text="Enter English text to translate.", fg="#ff7777")
                    return
                rt_status.config(text="Translating…", fg=accent)
                rt_btn.config(state=tk.DISABLED)
                self._on_retranslate(raw)

            rt_btn = tk.Button(
                bar_rt,
                text="Re-translate",
                command=_do_retranslate_local,
                font=small,
                bg="#2d2d2d",
                fg=trans_fg,
                activebackground="#3d3d3d",
                activeforeground=trans_fg,
                relief=tk.FLAT,
                padx=8,
                pady=2,
            )
            rt_btn.pack(side=tk.RIGHT)
            self._source_fix_widget = src_text

        fr.place(in_=self.win, x=-8000, y=0, width=inner_w)
        self.win.update_idletasks()
        qh = fr.winfo_reqheight()
        self._quick_actual_h = qh if qh > 0 else 1
        fr.place_forget()

        self._quick_panel = fr

    def _collapse_quick(self) -> None:
        self._apply_compact_dimensions()

        compact_h = self._translation_y + self._th + PADDING

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

        self._txt_widget.place(
            x=PADDING, y=self._translation_y, width=self._tw, height=self._th
        )
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
        self._schedule_auto_close()

    def _expand_quick(self) -> None:
        if not self._wants_expand:
            return

        self._pause_auto_close()
        self._apply_expanded_dimensions()
        self._ensure_quick_built()
        if self._quick_panel is None:
            return

        qg = self._quick_gap
        qp = self._quick_panel
        iw = max(280, self._card_w - 2 * PADDING - self._strip_w)
        qp.place(in_=self.win, x=-8000, y=0, width=iw)
        self.win.update_idletasks()
        qh = qp.winfo_reqheight()
        if qh > 0:
            self._quick_actual_h = qh
        qp.place_forget()

        expanded_h = self._translation_y + self._th + qg + self._quick_actual_h + PADDING

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

        self._txt_widget.place(
            x=PADDING, y=self._translation_y, width=self._tw, height=self._th
        )
        self._txt_widget.tkraise()

        self._quick_panel.place(
            x=PADDING, y=self._translation_y + self._th + qg, width=iw
        )
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

        ent = getattr(self, "_ent_for_focus", None)
        pref = getattr(self, "_preset_for_focus", "") or ""
        src_w = getattr(self, "_source_fix_widget", None)

        def _focus_entry():
            try:
                if self._can_quick_correction and ent is not None:
                    ent.focus_set()
                    ent.icursor(len(pref))
                elif self._can_fix and src_w is not None:
                    src_w.focus_set()
                    src_w.mark_set(tk.INSERT, "end")
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

    def _pause_auto_close(self) -> None:
        if self._after_id:
            try:
                self.root.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

    def _schedule_auto_close(self) -> None:
        self._pause_auto_close()
        self._after_id = self.root.after(self.auto_close_ms, self.close)

    def close(self):
        if self._after_id:
            self.root.after_cancel(self._after_id)
            self._after_id = None
        self._card_photo = None
        try:
            self.win.destroy()
        except tk.TclError:
            pass
