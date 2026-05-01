import json
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from pynput import keyboard, mouse

from app.ai_ocr import extract_text_ai
from app.capture import capture_region
from app.exit_button import ExitButton
from app.hotkeys import hotkey_readable, parse_hotkey
from app.lens import LensWindow
from app.ocr_engine import extract_text
from app.popup import TranslationPopup
from app.spinner import Spinner
from app.translator import translate

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.json"

_CAPTURE_MOUSE_TOKENS: dict[str, mouse.Button] = {
    "middle_click": mouse.Button.middle,
    "left_click": mouse.Button.left,
    "right_click": mouse.Button.right,
    "mouse_x1": mouse.Button.x1,
    "mouse_x2": mouse.Button.x2,
    "back": mouse.Button.x1,
    "forward": mouse.Button.x2,
    "x1": mouse.Button.x1,
    "x2": mouse.Button.x2,
}

_CAPTURE_MOUSE_READABLE: dict[str, str] = {
    "middle_click": "Middle mouse button",
    "left_click": "Left mouse button",
    "right_click": "Right mouse button",
    "mouse_x1": "Mouse side / back (X1)",
    "mouse_x2": "Mouse side / forward (X2)",
    "x1": "Mouse side / back (X1)",
    "x2": "Mouse side / forward (X2)",
    "back": "Mouse side / back (X1)",
    "forward": "Mouse side / forward (X2)",
}


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


class App:
    def __init__(self):
        self.config = load_config()
        self.root = tk.Tk()
        self.root.withdraw()

        self.lens = LensWindow(self.root, self.config)
        self._busy = False
        self._current_popup: TranslationPopup | None = None
        self._settings_panel = None

        self._exit_btn = None
        self._sync_exit_button()

        # Mouse listener for translate trigger
        self._mouse_listener = mouse.Listener(on_click=self._on_click)
        self._mouse_listener.start()

        # Keyboard listener for exit + settings hotkeys
        self._pressed_keys: set = set()
        self._exit_groups: list[set] = []
        self._settings_groups: list[set] = []
        self._capture_mode = "mouse"
        self._capture_button: mouse.Button = mouse.Button.middle
        self._capture_groups: list[set] = []
        self._reload_hotkeys()
        self._kb_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._kb_listener.start()

        exit_hotkey = self.config.get("exit_hotkey", "<ctrl>+q")
        show_btn = self.config.get("show_exit_button", True)
        settings_hotkey = self.config.get("settings_hotkey", "f12")
        print("OCR Translator running.")
        trig = hotkey_readable(
            str(self.config.get("hotkey", "middle_click")),
            _CAPTURE_MOUSE_READABLE,
        )
        print(f"  Capture : {trig}")
        print(f"  Exit    : {exit_hotkey}" + (" / red Exit button" if show_btn else ""))
        print(
            "  Settings: "
            + settings_hotkey
            + (" / Settings button" if show_btn else " (hide control bar)")
        )
        print(f"  Model   : {self.config.get('model')} @ {self.config.get('ai_url')}")
        print("  Resize  : Left Shift + Scroll wheel\n")

        self.root.mainloop()

    def _reload_hotkeys(self) -> None:
        q = self.config.get("exit_hotkey", "<ctrl>+<shift>+<alt>+q")
        parsed = parse_hotkey(q)
        self._exit_groups = parsed if parsed else parse_hotkey("<ctrl>+<shift>+<alt>+q")
        sq = self.config.get("settings_hotkey", "f12")
        sparsed = parse_hotkey(sq)
        self._settings_groups = sparsed if sparsed else parse_hotkey("f12")
        self._reload_capture_trigger()

    def _reload_capture_trigger(self) -> None:
        raw = str(self.config.get("hotkey", "middle_click")).strip()
        raw_lc = raw.lower()
        btn = _CAPTURE_MOUSE_TOKENS.get(raw_lc)
        if btn is not None:
            self._capture_mode = "mouse"
            self._capture_button = btn
            self._capture_groups = []
            return
        groups = parse_hotkey(raw)
        if groups:
            self._capture_mode = "keyboard"
            self._capture_button = mouse.Button.middle
            self._capture_groups = groups
            return
        self._capture_mode = "mouse"
        self._capture_button = mouse.Button.middle
        self._capture_groups = []

    def _sync_exit_button(self) -> None:
        want = self.config.get("show_exit_button", True)
        if want:
            if self._exit_btn is None:
                self._exit_btn = ExitButton(
                    self.root,
                    self._quit,
                    ai_url=self.config.get("ai_url", "http://localhost:12434"),
                    settings_command=lambda: self.root.after(0, self._open_settings),
                )
        else:
            if self._exit_btn is not None:
                try:
                    self._exit_btn.win.destroy()
                except tk.TclError:
                    pass
                self._exit_btn = None

    def _open_settings(self) -> None:
        try:
            from app.config_panel import ConfigPanel, _bring_settings_to_foreground
        except Exception as e:
            print(f"[Settings] Import failed: {e}")
            try:
                messagebox.showerror("Settings", f"Could not load settings panel:\n{e}")
            except Exception:
                pass
            return

        try:
            snapshot = load_config()
        except Exception as e:
            print(f"[Settings] Config load failed: {e}")
            try:
                messagebox.showerror("Settings", f"Could not read config.json:\n{e}")
            except Exception:
                pass
            return

        self.lens.hide()
        if self._exit_btn is not None:
            self._exit_btn.set_always_on_top(False)

        if self._settings_panel is not None:
            try:
                if self._settings_panel.winfo_exists():
                    _bring_settings_to_foreground(self._settings_panel)
                    return
            except tk.TclError:
                pass
            self._settings_panel = None

        def on_saved(new_cfg: dict) -> None:
            self.config = new_cfg
            self.lens.apply_config(new_cfg)
            self._reload_hotkeys()
            self._sync_exit_button()
            if self._exit_btn is not None:
                self._exit_btn.set_ai_url(new_cfg.get("ai_url", "http://localhost:12434"))

        panel_holder: list = []

        def _restore_lens_controls() -> None:
            self.lens.show()
            self.lens.set_always_on_top(True)
            if self._exit_btn is not None:
                self._exit_btn.set_always_on_top(True)

        def _on_panel_destroy(ev=None) -> None:
            root_panel = panel_holder[0] if panel_holder else None
            if ev is not None and getattr(ev, "widget", None) is not root_panel:
                return
            panel_holder.clear()
            self._settings_panel = None
            _restore_lens_controls()

        try:
            panel = ConfigPanel(self.root, snapshot, on_saved)
            panel_holder.append(panel)
            self._settings_panel = panel
            panel.bind("<Destroy>", _on_panel_destroy)
            self.root.after(120, lambda: _bring_settings_to_foreground(panel))
        except Exception as e:
            self._settings_panel = None
            _restore_lens_controls()
            print(f"[Settings] Open failed: {e}")
            try:
                messagebox.showerror("Settings", f"Could not open settings panel:\n{e}")
            except Exception:
                pass

    # --- Mouse ---

    def _on_click(self, x, y, button, pressed):
        if not pressed or self._capture_mode != "mouse":
            return
        if button == self._capture_button:
            self.root.after(0, self._trigger)

    # --- Keyboard (exit hotkey) ---

    def _on_key_press(self, key):
        self._pressed_keys.add(key)
        if self._capture_mode == "keyboard" and self._capture_groups:
            if all(group & self._pressed_keys for group in self._capture_groups):
                self.root.after(0, self._trigger)
                return
        if self._settings_groups and all(
            group & self._pressed_keys for group in self._settings_groups
        ):
            self.root.after(0, self._open_settings)
            return
        if self._exit_groups and all(
            group & self._pressed_keys for group in self._exit_groups
        ):
            self.root.after(0, self._quit)

    def _on_key_release(self, key):
        self._pressed_keys.discard(key)

    # --- Pipeline ---

    def _trigger(self):
        if self._busy:
            return
        self._busy = True

        if self._current_popup:
            self._current_popup.close()
            self._current_popup = None

        cx, cy, radius = self.lens.get_center_and_radius()
        threading.Thread(
            target=self._run_pipeline,
            args=(cx, cy, radius),
            daemon=True,
        ).start()

    def _run_pipeline(self, cx: int, cy: int, radius: int):
        spinner = Spinner()
        try:
            spinner.start("Capturing image ...")
            image = capture_region(cx, cy, radius)

            ai_ocr_cfg = self.config.get("ai_ocr", {})
            ai_url = self.config.get("ai_url", "http://localhost:12434")
            model = self.config.get("model", "docker.io/ai/gemma3:4B-F16")

            if ai_ocr_cfg.get("enabled", False):
                ai_model = ai_ocr_cfg.get("model", "docker.io/ai/gemma3n:2B-F16")
                spinner.update(f"Reading text  ->  {ai_model} ...")
                original = extract_text_ai(
                    image,
                    ai_ocr_cfg,
                    self.config.get("ocr"),
                    ai_url,
                )
            else:
                spinner.update("Reading text  ->  EasyOCR ...")
                ocr_cfg = dict(self.config.get("ocr") or {})
                if not self.config.get("debug", False):
                    ocr_cfg["debug"] = False
                original = extract_text(image, ocr_cfg)

            if not original or original.startswith("[Error"):
                spinner.stop("  x  No text detected")
                self.root.after(0, self._show_empty, cx, cy)
                return

            spinner.update(f"Translating  ->  {model} ...")
            prompt_template = self.config.get("translate", {}).get("prompt", "Translate the following English text to Thai. Reply with only the Thai translation, nothing else.\n\n{text}")
            translated = translate(original, ai_url, model, prompt_template)

            preview = original[:48] + ("..." if len(original) > 48 else "")
            spinner.stop(f"  ok  {preview}")

            self.root.after(0, self._show_popup, original, translated, cx, cy)
        except Exception as e:
            spinner.stop(f"  x  Pipeline error: {e}")
            self.root.after(0, self._show_popup, "", f"[Pipeline error: {e}]", cx, cy)
        finally:
            self._busy = False

    def _show_popup(self, original: str, translated: str, cx: int, cy: int):
        self._current_popup = TranslationPopup(
            self.root, original, translated, cx, cy, self.config
        )
        self.root.after(30, self._raise_current_popup)

    def _show_empty(self, cx: int, cy: int):
        self._current_popup = TranslationPopup(
            self.root,
            "(no text detected)",
            "(point the lens at English text and try again)",
            cx, cy,
            self.config,
        )
        self.root.after(30, self._raise_current_popup)
        self._busy = False

    def _raise_current_popup(self) -> None:
        p = self._current_popup
        if p is None:
            return
        try:
            if self._exit_btn is not None:
                p.win.lift(self._exit_btn.win)
            else:
                p.win.lift(self.lens.win)
        except tk.TclError:
            pass
        try:
            p.win.lift()
        except tk.TclError:
            pass

    def _quit(self):
        self._mouse_listener.stop()
        self._kb_listener.stop()
        self.root.quit()


def run() -> None:
    App()
