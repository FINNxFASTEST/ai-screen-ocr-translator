import tkinter as tk
import ctypes

from pynput import keyboard, mouse

# Win32 constants for transparent click-through window
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
GWL_EXSTYLE = -20

TRANSPARENT_COLOR = "#010101"
MIN_RADIUS = 50
MAX_RADIUS = 400
SCROLL_STEP = 20
POLL_MS = 30

_SHIFT_KEYS = {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r}


class LensWindow:
    def __init__(self, root: tk.Tk, config: dict):
        self.root = root
        self.radius = config.get("lens_radius", 150)
        self.color = config.get("lens_color", "#00ff88")
        self.border_width = config.get("lens_border_width", 3)

        size = self.radius * 2 + 20

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-transparentcolor", TRANSPARENT_COLOR)
        self.win.config(bg=TRANSPARENT_COLOR)
        self.win.geometry(f"{size}x{size}+0+0")

        self.canvas = tk.Canvas(
            self.win,
            bg=TRANSPARENT_COLOR,
            highlightthickness=0,
            cursor="crosshair",
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self._make_click_through()

        # Track shift state via pynput keyboard listener
        self._shift_held = False
        self._kb = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._kb.start()

        # Track scroll via pynput mouse listener (tkinter can't receive it through click-through window)
        self._mouse = mouse.Listener(on_scroll=self._on_scroll)
        self._mouse.start()

        self._draw_circle()
        self._poll_mouse()

    def _make_click_through(self):
        hwnd = ctypes.windll.user32.GetParent(self.win.winfo_id())
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongW(
            hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT
        )

    def _draw_circle(self):
        self.canvas.delete("all")
        size = self.radius * 2 + 20
        self.win.geometry(f"{size}x{size}")
        pad = 10
        self.canvas.create_oval(
            pad,
            pad,
            size - pad,
            size - pad,
            outline=self.color,
            width=self.border_width,
            fill=TRANSPARENT_COLOR,
        )

    def _poll_mouse(self):
        try:
            x = self.win.winfo_pointerx()
            y = self.win.winfo_pointery()
            size = self.radius * 2 + 20
            self.win.geometry(f"+{x - size // 2}+{y - size // 2}")
        except Exception:
            pass
        self.root.after(POLL_MS, self._poll_mouse)

    def _on_key_press(self, key):
        if key in _SHIFT_KEYS:
            self._shift_held = True

    def _on_key_release(self, key):
        if key in _SHIFT_KEYS:
            self._shift_held = False

    def _on_scroll(self, x, y, dx, dy):
        if not self._shift_held:
            return
        if dy > 0:
            self.radius = min(self.radius + SCROLL_STEP, MAX_RADIUS)
        else:
            self.radius = max(self.radius - SCROLL_STEP, MIN_RADIUS)
        self.root.after(0, self._draw_circle)

    def get_center_and_radius(self) -> tuple[int, int, int]:
        x = self.win.winfo_pointerx()
        y = self.win.winfo_pointery()
        return x, y, self.radius

    def hide(self):
        self.win.withdraw()

    def show(self):
        self.win.deiconify()
