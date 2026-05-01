import json
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from pynput import keyboard, mouse

from app.ai_ocr import extract_text_ai
from app.capture import capture_region
from app.exit_button import ExitButton
from app.hotkeys import (
    config_capture_trigger_raw,
    hotkey_friendly,
    hotkey_readable,
    normalize_lens_wheel_mod,
    parse_hotkey,
)
from app.lens import SCROLL_STEP, LensWindow
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


def _parse_hotkey_or_empty(raw) -> list[set]:
    s = str(raw or "").strip()
    if not s:
        return []
    groups = parse_hotkey(s)
    return groups if groups else []


class App:
    def __init__(self):
        self.config = load_config()
        self.root = tk.Tk()
        self.root.withdraw()

        self.lens = LensWindow(self.root, self.config)
        self._busy = False
        self._current_popup: TranslationPopup | None = None
        self._settings_panel = None
        self._skip_next_panel_restore = False

        self._exit_btn = None
        self._sync_exit_button()

        # Mouse listener for translate trigger
        self._mouse_listener = mouse.Listener(on_click=self._on_click)
        self._mouse_listener.start()

        # Keyboard listener for exit + settings hotkeys
        self._pressed_keys: set = set()
        self._exit_groups: list[set] = []
        self._settings_groups: list[set] = []
        self._lens_settings_groups: list[set] = []
        self._lens_resize_width_groups: list[set] = []
        self._lens_resize_height_up_groups: list[set] = []
        self._lens_resize_height_down_groups: list[set] = []
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
        lens_hotkey = self.config.get("lens_settings_hotkey", "f11")
        print("OCR Translator running.")
        trig = hotkey_readable(
            config_capture_trigger_raw(self.config),
            _CAPTURE_MOUSE_READABLE,
        )
        print(f"  Capture : {trig}")
        print(f"  Exit    : {hotkey_friendly(exit_hotkey)}" + (" / red Exit button" if show_btn else ""))
        print(f"  Lens settings : {hotkey_friendly(lens_hotkey)}")
        print()

        self.root.mainloop()

    def _reload_hotkeys(self) -> None:
        q = self.config.get("exit_hotkey", "<ctrl>+<shift>+<alt>+q")
        parsed = parse_hotkey(q)
        self._exit_groups = parsed if parsed else parse_hotkey("<ctrl>+<shift>+<alt>+q")
        sq = self.config.get("settings_hotkey", "f12")
        sparsed = parse_hotkey(sq)
        self._settings_groups = sparsed if sparsed else parse_hotkey("f12")
        lsq = self.config.get("lens_settings_hotkey", "f11")
        lparsed = parse_hotkey(str(lsq).strip())
        self._lens_settings_groups = lparsed if lparsed else parse_hotkey("f11")
        self._lens_resize_width_groups = _parse_hotkey_or_empty(
            self.config.get("lens_hotkey_resize_width"),
        )
        self._lens_resize_height_up_groups = _parse_hotkey_or_empty(
            self.config.get("lens_hotkey_resize_height_up"),
        )
        self._lens_resize_height_down_groups = _parse_hotkey_or_empty(
            self.config.get("lens_hotkey_resize_height_down"),
        )
        self._reload_capture_trigger()

    def _reload_capture_trigger(self) -> None:
        raw = config_capture_trigger_raw(self.config)
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
        self.lens.set_wheel_resize_enabled(False)
        if self._exit_btn is not None:
            self._exit_btn.set_always_on_top(False)

        if self._settings_panel is not None:
            try:
                if self._settings_panel.winfo_exists():
                    if getattr(self._settings_panel, "_lens_only", False):
                        self._skip_next_panel_restore = True
                        self._settings_panel.destroy()
                        self._settings_panel = None
                    else:
                        self.lens.set_wheel_resize_enabled(False)
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
            self.lens.set_wheel_resize_enabled(True)
            self.lens.set_always_on_top(True)
            if self._exit_btn is not None:
                self._exit_btn.set_always_on_top(True)

        def _on_panel_destroy(ev=None) -> None:
            root_panel = panel_holder[0] if panel_holder else None
            if ev is not None and getattr(ev, "widget", None) is not root_panel:
                return
            panel_holder.clear()
            self._settings_panel = None
            if getattr(self, "_skip_next_panel_restore", False):
                self._skip_next_panel_restore = False
                return
            _restore_lens_controls()

        try:
            panel = ConfigPanel(self.root, snapshot, on_saved)
            panel_holder.append(panel)
            self._settings_panel = panel
            panel.bind("<Destroy>", _on_panel_destroy)
            self.root.after(120, lambda: _bring_settings_to_foreground(panel))
        except Exception as e:
            self._settings_panel = None
            self.lens.set_wheel_resize_enabled(True)
            _restore_lens_controls()
            print(f"[Settings] Open failed: {e}")
            try:
                messagebox.showerror("Settings", f"Could not open settings panel:\n{e}")
            except Exception:
                pass

    def _open_lens_settings(self) -> None:
        try:
            from app.config_panel import ConfigPanel, _bring_settings_to_foreground
        except Exception as e:
            print(f"[Lens settings] Import failed: {e}")
            try:
                messagebox.showerror("Lens settings", f"Could not load settings panel:\n{e}")
            except Exception:
                pass
            return

        try:
            snapshot = load_config()
        except Exception as e:
            print(f"[Lens settings] Config load failed: {e}")
            try:
                messagebox.showerror("Lens settings", f"Could not read config.json:\n{e}")
            except Exception:
                pass
            return

        self.lens.hide()
        self.lens.set_wheel_resize_enabled(False)
        if self._exit_btn is not None:
            self._exit_btn.set_always_on_top(False)

        if self._settings_panel is not None:
            try:
                if self._settings_panel.winfo_exists():
                    if getattr(self._settings_panel, "_lens_only", False):
                        self.lens.set_wheel_resize_enabled(False)
                        _bring_settings_to_foreground(self._settings_panel)
                        return
                    self._skip_next_panel_restore = True
                    self._settings_panel.destroy()
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
            self.lens.set_wheel_resize_enabled(True)
            self.lens.set_always_on_top(True)
            if self._exit_btn is not None:
                self._exit_btn.set_always_on_top(True)

        def _on_panel_destroy(ev=None) -> None:
            root_panel = panel_holder[0] if panel_holder else None
            if ev is not None and getattr(ev, "widget", None) is not root_panel:
                return
            panel_holder.clear()
            self._settings_panel = None
            if getattr(self, "_skip_next_panel_restore", False):
                self._skip_next_panel_restore = False
                return
            _restore_lens_controls()

        try:
            panel = ConfigPanel(self.root, snapshot, on_saved, panel_mode="lens_only")
            panel_holder.append(panel)
            self._settings_panel = panel
            panel.bind("<Destroy>", _on_panel_destroy)
            self.root.after(120, lambda: _bring_settings_to_foreground(panel))
        except Exception as e:
            self._settings_panel = None
            self.lens.set_wheel_resize_enabled(True)
            _restore_lens_controls()
            print(f"[Lens settings] Open failed: {e}")
            try:
                messagebox.showerror("Lens settings", f"Could not open lens panel:\n{e}")
            except Exception:
                pass

    # --- Mouse ---

    def _on_click(self, x, y, button, pressed, injected=False):
        # Synthetic events must pass through (e.g. other apps / automation).
        if injected:
            return
        if self._capture_mode != "mouse":
            return
        if button != self._capture_button:
            return
        if pressed:
            self.root.after(0, self._trigger)
        # Swallow press+release so apps (e.g. Chrome middle-click → new tab) never see them.
        # suppress_event() raises internally; trigger must already be queued above.
        if bool(self.config.get("capture_suppress_os_click", True)):
            self._mouse_listener.suppress_event()

    # --- Keyboard (exit hotkey) ---

    def _on_key_press(self, key):
        self._pressed_keys.add(key)
        if self._capture_mode == "keyboard" and self._capture_groups:
            if all(group & self._pressed_keys for group in self._capture_groups):
                self.root.after(0, self._trigger)
                return
        if self._lens_resize_width_groups and all(
            group & self._pressed_keys for group in self._lens_resize_width_groups
        ):
            self.root.after(0, lambda: self.lens.resize_width_delta(SCROLL_STEP))
            return
        if self._lens_resize_height_up_groups and all(
            group & self._pressed_keys for group in self._lens_resize_height_up_groups
        ):
            self.root.after(0, lambda: self.lens.resize_height_delta(SCROLL_STEP))
            return
        if self._lens_resize_height_down_groups and all(
            group & self._pressed_keys for group in self._lens_resize_height_down_groups
        ):
            self.root.after(0, lambda: self.lens.resize_height_delta(-SCROLL_STEP))
            return
        if self._lens_settings_groups and all(
            group & self._pressed_keys for group in self._lens_settings_groups
        ):
            self.root.after(0, self._open_lens_settings)
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
        self.lens.hide()
        self.lens.set_loading(True)

        if self._current_popup:
            self._current_popup.close()
            self._current_popup = None

        spec = self.lens.get_capture_params()
        threading.Thread(
            target=self._run_pipeline,
            args=(spec,),
            daemon=True,
        ).start()

    def _run_pipeline(self, spec: dict):
        cx = int(spec["cx"])
        cy = int(spec["cy"])
        debug = bool(self.config.get("debug", False))
        spinner = Spinner()
        try:
            spinner.start("Capturing ...")
            image = capture_region(spec)

            ai_ocr_cfg = self.config.get("ai_ocr", {})
            ai_url = self.config.get("ai_url", "http://localhost:12434")
            model = self.config.get("model", "docker.io/ai/gemma3:4B-F16")

            if ai_ocr_cfg.get("enabled", False):
                ai_model = ai_ocr_cfg.get("model", "docker.io/ai/gemma3n:2B-F16")
                spinner.update(f"Reading text ... [{ai_model}]" if debug else "Reading text ...")
                original = extract_text_ai(
                    image,
                    ai_ocr_cfg,
                    self.config.get("ocr"),
                    ai_url,
                )
            else:
                spinner.update("Reading text ... [EasyOCR]" if debug else "Reading text ...")
                ocr_cfg = dict(self.config.get("ocr") or {})
                if not debug:
                    ocr_cfg["debug"] = False
                original = extract_text(image, ocr_cfg)

            if not original or original.startswith("[Error"):
                spinner.stop("  No text found.")
                self.root.after(0, self._show_empty, cx, cy)
                return

            spinner.update(f"Translating ... [{model}]" if debug else "Translating ...")
            prompt_template = self.config.get("translate", {}).get("prompt", "Translate the following English text to Thai. Reply with only the Thai translation, nothing else.\n\n{text}")
            translated = translate(original, ai_url, model, prompt_template)

            preview = original[:48] + ("..." if len(original) > 48 else "")
            spinner.stop(f"  Done  \"{preview}\"")

            self.root.after(0, self._show_popup, original, translated, cx, cy)
        except Exception as e:
            spinner.stop(f"  Error: {e}" if debug else "  Something went wrong.")
            self.root.after(0, self._show_popup, "", f"[Error: {e}]", cx, cy)
        finally:
            self._busy = False
            self.root.after(0, lambda: self.lens.set_loading(False))
            self.root.after(0, self.lens.show)

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
