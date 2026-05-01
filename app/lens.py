import ctypes
import tkinter as tk

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

_SHIFT_KEYS = {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r}
_ALT_KEYS = {keyboard.Key.alt_l, keyboard.Key.alt_r}
if hasattr(keyboard.Key, "alt"):
    _ALT_KEYS.add(keyboard.Key.alt)


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

        self._shift_held = False
        self._alt_held = False
        self._wheel_resize_enabled = True
        self._kb = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._kb.start()

        self._mouse = mouse.Listener(on_scroll=self._on_scroll)
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
        self.root.after(0, self._apply_lens_visuals)

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
        self.canvas.delete("all")
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
        if key in _SHIFT_KEYS:
            self._shift_held = True
        if key in _ALT_KEYS:
            self._alt_held = True

    def _on_key_release(self, key):
        if key in _SHIFT_KEYS:
            self._shift_held = False
        if key in _ALT_KEYS:
            self._alt_held = False

    def _on_scroll(self, x, y, dx, dy):
        if not self._wheel_resize_enabled:
            return
        if dy == 0:
            return
        delta = SCROLL_STEP if dy > 0 else -SCROLL_STEP
        if not self._shift_held and not self._alt_held:
            return
        if self._shift_held and self._alt_held:
            self.lens_width = max(
                MIN_LENS_SIDE, min(MAX_LENS_SIDE, self.lens_width + delta)
            )
            self.lens_height = max(
                MIN_LENS_SIDE, min(MAX_LENS_SIDE, self.lens_height + delta)
            )
        elif self._alt_held:
            self.lens_width = max(
                MIN_LENS_SIDE, min(MAX_LENS_SIDE, self.lens_width + delta)
            )
        elif self._shift_held:
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

    def hide(self):
        self.win.withdraw()

    def show(self):
        self.win.deiconify()

    def set_always_on_top(self, enabled: bool) -> None:
        try:
            self.win.attributes("-topmost", enabled)
        except tk.TclError:
            pass


def _norm_shape(raw) -> str:
    s = str(raw or "circle").strip().lower()
    return "square" if s == "square" else "circle"
