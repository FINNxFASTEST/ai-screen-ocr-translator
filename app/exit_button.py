import ctypes
import sys
import threading
import tkinter as tk

import requests


def _floating_panel_xy(root: tk.Tk, win: tk.Toplevel, margin_x: float = 0.20, margin_y: float = 0.20) -> tuple[int, int]:
    """Top-left of floating bar at margin_x / margin_y of primary monitor work area (multi-monitor safe on Windows)."""
    win.update_idletasks()
    ww = max(win.winfo_reqwidth(), 1)
    wh = max(win.winfo_reqheight(), 1)
    if sys.platform == "win32":
        try:

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_long),
                    ("top", ctypes.c_long),
                    ("right", ctypes.c_long),
                    ("bottom", ctypes.c_long),
                ]

            rect = RECT()
            SPI_GETWORKAREA = 0x0030
            if ctypes.windll.user32.SystemParametersInfoW(
                SPI_GETWORKAREA, 0, ctypes.byref(rect), 0
            ):
                aw = rect.right - rect.left
                ah = rect.bottom - rect.top
                x = rect.left + int(aw * margin_x)
                y = rect.top + int(ah * margin_y)
                x = max(rect.left, min(x, rect.right - ww))
                y = max(rect.top, min(y, rect.bottom - wh))
                return x, y
        except Exception:
            pass
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = max(0, min(int(sw * margin_x), sw - ww))
    y = max(0, min(int(sh * margin_y), sh - wh))
    return x, y

BG = "#1e1e1e"
BTN_COLOR = "#ff4444"
BTN_HOVER = "#ff2222"
TEST_COLOR = "#2d6be4"
TEST_HOVER = "#1a55cc"
TEXT_COLOR = "#ffffff"
STATUS_OK = "#00ff88"
STATUS_ERR = "#ff4444"
STATUS_BUSY = "#888888"
COMIC_FG = "#a8c8ff"
PROFILE_TEXT_MAX = 20
ENGINES_TEXT_MAX = 56


def _ellipsize(s: str, max_chars: int = PROFILE_TEXT_MAX) -> str:
    if not s:
        return ""
    if len(s) <= max_chars:
        return s
    return s[:max_chars] + "..."


def _ellipsize_multiline(s: str, line_max: int) -> str:
    if not s:
        return ""
    return "\n".join(_ellipsize(line, line_max) for line in s.split("\n"))


class ExitButton:
    def __init__(
        self,
        root: tk.Tk,
        on_exit,
        config: dict | None = None,
        settings_command=None,
        *,
        quick_translate: bool = False,
        on_quick_translate_change=None,
    ):
        self.root = root
        self.on_exit = on_exit
        self._config = config
        self.ai_url = (config or {}).get("ai_url", "http://localhost:12434")
        self._on_quick_translate_change = on_quick_translate_change

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.config(bg=BG)

        frame = tk.Frame(self.win, bg=BG, padx=6, pady=6)
        frame.pack()

        self._profile_line_full = ""
        self._comic_line_full = ""
        self._lang_line_full = ""
        self._engines_line_full = ""
        self._profile_expanded = False

        self.profile_row = tk.Frame(frame, bg=BG)
        self.profile_row.pack(fill=tk.X, pady=(0, 2))

        self.profile_title = tk.Label(
            self.profile_row,
            text="",
            font=("Segoe UI", 8, "bold"),
            fg=TEXT_COLOR,
            bg=BG,
            anchor="w",
        )
        self.profile_title.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.profile_expand_btn = tk.Button(
            self.profile_row,
            text="···",
            font=("Segoe UI", 8, "bold"),
            fg=TEXT_COLOR,
            bg="#2a2a2a",
            activebackground="#3a3a3a",
            activeforeground=TEXT_COLOR,
            relief=tk.FLAT,
            cursor="hand2",
            padx=4,
            pady=0,
            width=3,
            command=self._toggle_profile_expand,
        )

        self.profile_comic = tk.Label(
            frame,
            text="",
            font=("Segoe UI", 8),
            fg=COMIC_FG,
            bg=BG,
            anchor="w",
        )
        self._profile_comic_visible = False

        self.profile_lang = tk.Label(
            frame,
            text="",
            font=("Segoe UI", 8),
            fg="#888888",
            bg=BG,
            anchor="w",
        )
        self._profile_lang_visible = False

        self.profile_engines = tk.Label(
            frame,
            text="",
            font=("Segoe UI", 8),
            fg="#777777",
            bg=BG,
            anchor="w",
            justify=tk.LEFT,
        )
        self._profile_engines_visible = False

        self.quick_row = tk.Frame(frame, bg=BG)
        self.var_quick_translate = tk.BooleanVar(value=bool(quick_translate))
        self.quick_translate_cb = tk.Checkbutton(
            self.quick_row,
            text="Quick translate",
            variable=self.var_quick_translate,
            command=self._on_quick_translate_clicked,
            font=("Segoe UI", 8),
            fg=TEXT_COLOR,
            bg=BG,
            activebackground=BG,
            activeforeground=TEXT_COLOR,
            selectcolor="#2a2a2a",
            highlightthickness=0,
            cursor="hand2",
        )
        self.quick_translate_cb.pack(anchor="w")

        self._first_btn_ref = None

        if settings_command:
            self.settings_btn = tk.Button(
                frame,
                text="Settings",
                font=("Segoe UI", 9, "bold"),
                fg=TEXT_COLOR,
                bg="#3a3a3a",
                activebackground="#4a4a4a",
                activeforeground=TEXT_COLOR,
                relief=tk.FLAT,
                cursor="hand2",
                padx=10,
                pady=5,
                command=settings_command,
            )
            self.quick_row.pack(fill=tk.X, pady=(0, 4))
            self.settings_btn.pack(fill=tk.X, pady=(0, 4))
            self._first_btn_ref = self.settings_btn
        else:
            self.settings_btn = None
            self.quick_row.pack(fill=tk.X, pady=(0, 4))

        self.test_btn = tk.Button(
            frame,
            text="Test Connection",
            font=("Segoe UI", 9, "bold"),
            fg=TEXT_COLOR,
            bg=TEST_COLOR,
            activebackground=TEST_HOVER,
            activeforeground=TEXT_COLOR,
            relief=tk.FLAT,
            cursor="hand2",
            padx=10,
            pady=5,
            command=self._test_connection,
        )
        self.test_btn.pack(fill=tk.X, pady=(0, 4))

        self.status_label = tk.Label(
            frame,
            text="",
            font=("Segoe UI", 8),
            fg=STATUS_BUSY,
            bg=BG,
            anchor="center",
        )
        self.status_label.pack(fill=tk.X, pady=(0, 4))

        self.exit_btn = tk.Button(
            frame,
            text="  Exit  ",
            font=("Segoe UI", 10, "bold"),
            fg=TEXT_COLOR,
            bg=BTN_COLOR,
            activebackground=BTN_HOVER,
            activeforeground=TEXT_COLOR,
            relief=tk.FLAT,
            cursor="hand2",
            padx=10,
            pady=6,
            command=self._exit,
        )
        self.exit_btn.pack(fill=tk.X)

        if self._first_btn_ref is None:
            self._first_btn_ref = self.test_btn

        self._anchor_below_profile = self.quick_row

        self.win.bind("<Button-1>", self._drag_start)
        self.win.bind("<B1-Motion>", self._drag_move)
        self._drag_x = 0
        self._drag_y = 0

        x, y = _floating_panel_xy(root, self.win)
        self.win.geometry(f"+{x}+{y}")

    def _drag_start(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _drag_move(self, event):
        x = self.win.winfo_x() + event.x - self._drag_x
        y = self.win.winfo_y() + event.y - self._drag_y
        self.win.geometry(f"+{x}+{y}")

    def _test_connection(self):
        self.test_btn.config(state=tk.DISABLED)
        self._set_status("Connecting...", STATUS_BUSY)
        threading.Thread(target=self._ping, daemon=True).start()

    def _ping(self):
        try:
            if self._config is not None:
                from app.ai_integration import ping_translate, resolve_translate

                ok, detail = ping_translate(resolve_translate(self._config))
                if ok:
                    self.root.after(0, self._set_status, detail or "OK", STATUS_OK)
                else:
                    self.root.after(0, self._set_status, detail[:160], STATUS_ERR)
            else:
                resp = requests.get(f"{self.ai_url}/v1/models", timeout=5)
                resp.raise_for_status()
                models = [m["id"] for m in resp.json().get("data", [])]
                label = f"OK  ({len(models)} model{'s' if len(models) != 1 else ''})"
                self.root.after(0, self._set_status, label, STATUS_OK)
        except requests.exceptions.ConnectionError:
            self.root.after(0, self._set_status, "Cannot connect", STATUS_ERR)
        except requests.exceptions.Timeout:
            self.root.after(0, self._set_status, "Timed out", STATUS_ERR)
        except Exception as e:
            self.root.after(0, self._set_status, f"Error: {e}", STATUS_ERR)
        finally:
            self.root.after(0, self.test_btn.config, {"state": tk.NORMAL})

    def _set_status(self, text: str, color: str):
        self.status_label.config(text=text, fg=color)

    def set_config(self, cfg: dict) -> None:
        """Refresh resolved endpoint for Test Connection + fallback URL."""
        self._config = cfg
        self.ai_url = str(cfg.get("ai_url") or self.ai_url)

    def set_ai_url(self, url: str):
        self.ai_url = url

    def set_quick_translate(self, enabled: bool) -> None:
        self.var_quick_translate.set(bool(enabled))

    def _on_quick_translate_clicked(self) -> None:
        if self._on_quick_translate_change:
            self._on_quick_translate_change(bool(self.var_quick_translate.get()))

    def set_profile_display(
        self,
        profile_line: str,
        comic_line: str,
        lang_line: str = "",
        engines_line: str = "",
    ) -> None:
        """Profile row, comic name, languages, and OCR / translate backends in use."""
        self._profile_line_full = profile_line or ""
        self._comic_line_full = (comic_line or "").strip()
        self._lang_line_full = (lang_line or "").strip()
        self._engines_line_full = (engines_line or "").strip()
        self._profile_expanded = False
        self._apply_profile_labels()

    def _toggle_profile_expand(self):
        self._profile_expanded = not self._profile_expanded
        self._apply_profile_labels()

    def _needs_expand(self) -> bool:
        pl = self._profile_line_full or ""
        cl = (self._comic_line_full or "").strip()
        ll = (self._lang_line_full or "").strip()
        el = (self._engines_line_full or "").strip()
        eng_expand = any(len(ln) > ENGINES_TEXT_MAX for ln in el.split("\n")) if el else False
        return (
            len(pl) > PROFILE_TEXT_MAX
            or len(cl) > PROFILE_TEXT_MAX
            or len(ll) > PROFILE_TEXT_MAX
            or eng_expand
        )

    def _apply_profile_labels(self):
        pl_full = self._profile_line_full or ""
        cl_full = (self._comic_line_full or "").strip()
        lg_full = (self._lang_line_full or "").strip()
        eng_full = (self._engines_line_full or "").strip()

        if self._profile_expanded:
            pl = pl_full
            ct = cl_full
            lg = lg_full
            eng = eng_full
        else:
            pl = _ellipsize(pl_full)
            ct = _ellipsize(cl_full) if cl_full else ""
            lg = _ellipsize(lg_full) if lg_full else ""
            eng = _ellipsize_multiline(eng_full, ENGINES_TEXT_MAX) if eng_full else ""

        self.profile_title.config(text=pl)

        if self._needs_expand():
            self.profile_expand_btn.pack(side=tk.RIGHT)
            self.profile_expand_btn.config(text="▲" if self._profile_expanded else "···")
        else:
            self.profile_expand_btn.pack_forget()

        if self._profile_comic_visible:
            self.profile_comic.pack_forget()
            self._profile_comic_visible = False
        if self._profile_lang_visible:
            self.profile_lang.pack_forget()
            self._profile_lang_visible = False
        if self._profile_engines_visible:
            self.profile_engines.pack_forget()
            self._profile_engines_visible = False

        if ct:
            self.profile_comic.config(text=ct)
            self.profile_comic.pack(
                fill=tk.X,
                pady=(0, 2 if (lg_full or eng_full) else 4),
                before=self._anchor_below_profile,
            )
            self._profile_comic_visible = True

        if lg:
            self.profile_lang.config(text=lg)
            self.profile_lang.pack(
                fill=tk.X,
                pady=(0, 2 if eng_full else 4),
                before=self._anchor_below_profile,
            )
            self._profile_lang_visible = True

        if eng:
            self.profile_engines.config(text=eng)
            self.profile_engines.pack(
                fill=tk.X,
                pady=(0, 4),
                before=self._anchor_below_profile,
            )
            self._profile_engines_visible = True

    def set_always_on_top(self, enabled: bool) -> None:
        try:
            self.win.attributes("-topmost", enabled)
        except tk.TclError:
            pass

    def _exit(self):
        self.on_exit()
