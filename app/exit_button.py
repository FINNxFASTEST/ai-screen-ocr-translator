import threading
import tkinter as tk

import requests

BG = "#1e1e1e"
BTN_COLOR = "#ff4444"
BTN_HOVER = "#ff2222"
TEST_COLOR = "#2d6be4"
TEST_HOVER = "#1a55cc"
TEXT_COLOR = "#ffffff"
STATUS_OK = "#00ff88"
STATUS_ERR = "#ff4444"
STATUS_BUSY = "#888888"


class ExitButton:
    def __init__(self, root: tk.Tk, on_exit, ai_url: str = "http://localhost:12434"):
        self.root = root
        self.on_exit = on_exit
        self.ai_url = ai_url

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.config(bg=BG)
        self.win.geometry("+20+20")

        frame = tk.Frame(self.win, bg=BG, padx=6, pady=6)
        frame.pack()

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

        self.win.bind("<Button-1>", self._drag_start)
        self.win.bind("<B1-Motion>", self._drag_move)
        self._drag_x = 0
        self._drag_y = 0

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

    def _exit(self):
        self.on_exit()
