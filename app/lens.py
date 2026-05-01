import ctypes
import tkinter as tk

from app.hotkeys import lens_scroll_modifier_key_set, normalize_lens_wheel_mod
from pynput import keyboard, mouse

# Win32 constants for transparent click-through window
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
GWL_EXSTYLE = -20

TRANSPARENT_COLOR = "#010101"
MIN_RADIUS = 50
MAX_RADIUS = 400
MIN_LENS_SIDE = MIN_RADIUS * 2
MAX_LENS_SIDE = MAX_RADIUS * 2
SCROLL_STEP = 20
POLL_MS = 30
MIN_OPACITY = 0.25
MAX_OPACITY = 1.0

class LensWindow:
    def __init__(self, root: tk.Tk, config: dict):
        self.root = root
        self.shape = _norm_shape(config.get("lens_shape", "circle"))

        r = int(config.get("lens_radius", 150))
        r = max(MIN_RADIUS, min(MAX_RADIUS, r))
        r2 = r * 2
        self.lens_width = int(config.get("lens_width", r2))
        self.lens_height = int(config.get("lens_height", r2))
        self.lens_width = max(MIN_LENS_SIDE, min(MAX_LENS_SIDE, self.lens_width))
        self.lens_height = max(MIN_LENS_SIDE, min(MAX_LENS_SIDE, self.lens_height))
        self.radius = max(
            MIN_RADIUS, min(MAX_RADIUS, max(self.lens_width, self.lens_height) // 2)
        )

        self.color = config.get("lens_color", "#ABD7FF")
        self.border_width = config.get("lens_border_width", 3)
        self.opacity = self._clamp_opacity(config.get("lens_opacity", 1.0))

        ow, oh = self._outer_size()
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-transparentcolor", TRANSPARENT_COLOR)
        self.win.config(bg=TRANSPARENT_COLOR)
        self.win.geometry(f"{ow}x{oh}+0+0")

        self.canvas = tk.Canvas(
            self.win,
            bg=TRANSPARENT_COLOR,
            highlightthickness=0,
            cursor="crosshair",
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self._make_click_through()
        self._apply_window_opacity()

        self._dots = _LoadingDots(root)

        self._width_mod_held = False
        self._height_mod_held = False
        self._wheel_resize_enabled = True
        self._wheel_suppress_os_scroll = bool(
            config.get("lens_wheel_suppress_os_scroll", True)
        )
        self._reload_wheel_modifiers(config)
        self._kb = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._kb.start()

        def hooked_scroll(x, y, dx, dy, injected=False):
            # Injected events must pass through (e.g. synthetic scroll).
            if injected:
                return
            self._on_scroll(x, y, dx, dy)
            if self._lens_wheel_blocks_os_delivery(dx, dy):
                m_listener.suppress_event()

        m_listener = mouse.Listener(on_scroll=hooked_scroll)
        self._mouse = m_listener
        self._mouse.start()

        self._draw_lens()
        self._poll_mouse()

    def _outer_size(self) -> tuple[int, int]:
        pad = 20
        return self.lens_width + pad, self.lens_height + pad

    def _sync_radius_alias(self) -> None:
        """Keep lens_radius field meaningful for config (max half-axis)."""
        self.radius = max(
            MIN_RADIUS, min(MAX_RADIUS, max(self.lens_width, self.lens_height) // 2)
        )

    def apply_config(self, config: dict) -> None:
        """Resize / restyle lens from saved config (live apply)."""
        self.shape = _norm_shape(config.get("lens_shape", self.shape))

        r_cfg = int(config.get("lens_radius", self.radius))
        r_cfg = max(MIN_RADIUS, min(MAX_RADIUS, r_cfg))
        fallback = r_cfg * 2

        self.lens_width = max(
            MIN_LENS_SIDE,
            min(
                MAX_LENS_SIDE,
                int(config.get("lens_width", self.lens_width or fallback)),
            ),
        )
        self.lens_height = max(
            MIN_LENS_SIDE,
            min(
                MAX_LENS_SIDE,
                int(config.get("lens_height", self.lens_height or fallback)),
            ),
        )
        self._sync_radius_alias()

        self.color = config.get("lens_color", self.color)
        bw = int(config.get("lens_border_width", self.border_width))
        self.border_width = max(1, min(20, bw))
        self.opacity = self._clamp_opacity(config.get("lens_opacity", self.opacity))
        self._wheel_suppress_os_scroll = bool(
            config.get("lens_wheel_suppress_os_scroll", True)
        )
        self._reload_wheel_modifiers(config)
        self.root.after(0, self._apply_lens_visuals)

    def _reload_wheel_modifiers(self, config: dict) -> None:
        w = normalize_lens_wheel_mod(config.get("lens_wheel_mod_width", "alt"))
        h = normalize_lens_wheel_mod(config.get("lens_wheel_mod_height", "ctrl"))
        if w == h:
            h = next(t for t in ("shift", "alt", "ctrl", "win") if t != w)
        self._width_mod_keys = lens_scroll_modifier_key_set(w)
        self._height_mod_keys = lens_scroll_modifier_key_set(h)

    @staticmethod
    def _clamp_opacity(value) -> float:
        try:
            x = float(value)
        except (TypeError, ValueError):
            x = 1.0
        return max(MIN_OPACITY, min(MAX_OPACITY, x))

    def _apply_window_opacity(self) -> None:
        try:
            self.win.attributes("-alpha", self.opacity)
        except tk.TclError:
            pass

    def _apply_lens_visuals(self) -> None:
        self._apply_window_opacity()
        self._draw_lens()

    def _make_click_through(self):
        hwnd = ctypes.windll.user32.GetParent(self.win.winfo_id())
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongW(
            hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT
        )

    def _draw_lens(self):
        self.canvas.delete("lens")
        ow, oh = self._outer_size()
        self.win.geometry(f"{ow}x{oh}")
        pad = 10
        if self.shape == "square":
            self.canvas.create_rectangle(
                pad,
                pad,
                ow - pad,
                oh - pad,
                outline=self.color,
                width=self.border_width,
                fill=TRANSPARENT_COLOR,
                tags="lens",
            )
        else:
            self.canvas.create_oval(
                pad,
                pad,
                ow - pad,
                oh - pad,
                outline=self.color,
                width=self.border_width,
                fill=TRANSPARENT_COLOR,
                tags="lens",
            )

    def _poll_mouse(self):
        try:
            x = self.win.winfo_pointerx()
            y = self.win.winfo_pointery()
            ow, oh = self._outer_size()
            self.win.geometry(f"+{x - ow // 2}+{y - oh // 2}")
        except Exception:
            pass
        self.root.after(POLL_MS, self._poll_mouse)

    def _on_key_press(self, key):
        if key in self._width_mod_keys:
            self._width_mod_held = True
        if key in self._height_mod_keys:
            self._height_mod_held = True

    def _on_key_release(self, key):
        if key in self._width_mod_keys:
            self._width_mod_held = False
        if key in self._height_mod_keys:
            self._height_mod_held = False

    def _lens_wheel_blocks_os_delivery(self, dx: int, dy: int) -> bool:
        """True when wheel should not reach other apps (Windows low-level hook)."""
        if not self._wheel_suppress_os_scroll or not self._wheel_resize_enabled:
            return False
        if not self._width_mod_held and not self._height_mod_held:
            return False
        return dx != 0 or dy != 0

    def _on_scroll(self, x, y, dx, dy):
        if not self._wheel_resize_enabled:
            return
        if dy == 0:
            return
        delta = SCROLL_STEP if dy > 0 else -SCROLL_STEP
        if not self._width_mod_held and not self._height_mod_held:
            return
        if self._width_mod_held and self._height_mod_held:
            self.lens_width = max(
                MIN_LENS_SIDE, min(MAX_LENS_SIDE, self.lens_width + delta)
            )
            self.lens_height = max(
                MIN_LENS_SIDE, min(MAX_LENS_SIDE, self.lens_height + delta)
            )
        elif self._width_mod_held:
            self.lens_width = max(
                MIN_LENS_SIDE, min(MAX_LENS_SIDE, self.lens_width + delta)
            )
        elif self._height_mod_held:
            self.lens_height = max(
                MIN_LENS_SIDE, min(MAX_LENS_SIDE, self.lens_height + delta)
            )
        self._sync_radius_alias()
        self.root.after(0, self._draw_lens)

    def resize_width_delta(self, delta: int) -> None:
        self.lens_width = max(
            MIN_LENS_SIDE, min(MAX_LENS_SIDE, self.lens_width + int(delta))
        )
        self._sync_radius_alias()
        self.root.after(0, self._draw_lens)

    def resize_height_delta(self, delta: int) -> None:
        self.lens_height = max(
            MIN_LENS_SIDE, min(MAX_LENS_SIDE, self.lens_height + int(delta))
        )
        self._sync_radius_alias()
        self.root.after(0, self._draw_lens)

    def set_wheel_resize_enabled(self, enabled: bool) -> None:
        """Off while Settings are open so wheel + modifiers don't steal scrollbar / sliders."""
        self._wheel_resize_enabled = bool(enabled)

    def get_capture_params(self) -> dict:
        cx = self.win.winfo_pointerx()
        cy = self.win.winfo_pointery()
        if self.shape == "square":
            return {
                "shape": "square",
                "cx": cx,
                "cy": cy,
                "width": self.lens_width,
                "height": self.lens_height,
            }
        return {
            "shape": "ellipse",
            "cx": cx,
            "cy": cy,
            "width": self.lens_width,
            "height": self.lens_height,
        }

    def set_loading(self, enabled: bool) -> None:
        if enabled:
            self._dots.show()
        else:
            self._dots.hide()

    def hide(self):
        self.win.withdraw()

    def show(self):
        self.win.deiconify()

    def set_always_on_top(self, enabled: bool) -> None:
        try:
            self.win.attributes("-topmost", enabled)
        except tk.TclError:
            pass


class _LoadingDots:
    _W, _H = 52, 20
    _BG = "#1C1C1C"
    _DOT_ON = "#FFFFFF"
    _DOT_OFF = "#3A3A3A"
    _INTERVAL = 280

    def __init__(self, root: tk.Tk):
        self.root = root
        self._step = 0
        self._running = False

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-transparentcolor", TRANSPARENT_COLOR)
        self.win.config(bg=TRANSPARENT_COLOR)
        self.win.geometry(f"{self._W}x{self._H}+0+0")
        self.win.withdraw()

        hwnd = ctypes.windll.user32.GetParent(self.win.winfo_id())
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongW(
            hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT
        )

        self.canvas = tk.Canvas(
            self.win, bg=TRANSPARENT_COLOR,
            highlightthickness=0,
            width=self._W, height=self._H,
        )
        self.canvas.pack()
        self._draw_bg()

    def _draw_bg(self):
        r, x1, y1, x2, y2 = 7, 0, 0, self._W, self._H
        pts = [
            x1+r, y1, x2-r, y1, x2, y1, x2, y1+r,
            x2, y2-r, x2, y2, x2-r, y2, x1+r, y2,
            x1, y2, x1, y2-r, x1, y1+r, x1, y1,
        ]
        self.canvas.create_polygon(pts, smooth=True, fill=self._BG, outline="")

    def show(self):
        self._running = True
        self._step = 0
        self.win.deiconify()
        self._poll()
        self._animate()

    def hide(self):
        self._running = False
        self.win.withdraw()

    def _poll(self):
        if not self._running:
            return
        try:
            x = self.win.winfo_pointerx()
            y = self.win.winfo_pointery()
            self.win.geometry(f"+{x + 20}+{y + 20}")
        except Exception:
            pass
        self.root.after(30, self._poll)

    def _animate(self):
        if not self._running:
            return
        self.canvas.delete("dot")
        cy = self._H // 2
        for i in range(3):
            active = (i == self._step % 3)
            color = self._DOT_ON if active else self._DOT_OFF
            r = 4 if active else 3
            cx = 13 + i * 13
            self.canvas.create_oval(
                cx - r, cy - r, cx + r, cy + r,
                fill=color, outline="", tags="dot",
            )
        self._step += 1
        self.root.after(self._INTERVAL, self._animate)


def _norm_shape(raw) -> str:
    s = str(raw or "circle").strip().lower()
    return "square" if s == "square" else "circle"
