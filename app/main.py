import json
import threading
import tkinter as tk
from pathlib import Path

from pynput import keyboard, mouse

from app.ai_ocr import extract_text_ai
from app.capture import capture_region
from app.exit_button import ExitButton
from app.lens import LensWindow
from app.ocr_engine import extract_text
from app.popup import TranslationPopup
from app.spinner import Spinner
from app.translator import translate

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.json"


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


_SPECIAL_KEYS = {
    "ctrl":        (keyboard.Key.ctrl_l,  keyboard.Key.ctrl_r),
    "shift":       (keyboard.Key.shift_l, keyboard.Key.shift_r, keyboard.Key.shift),
    "alt":         (keyboard.Key.alt_l,   keyboard.Key.alt_r),
    "scroll_lock": (keyboard.Key.scroll_lock,),
    "pause":       (keyboard.Key.pause,),
    "caps_lock":   (keyboard.Key.caps_lock,),
    **{f"f{n}": (getattr(keyboard.Key, f"f{n}"),) for n in range(1, 21)},
}


def parse_exit_hotkey(hotkey_str: str) -> list[set]:
    """Parse hotkey string into a list of key groups.

    Each group is a set of acceptable pynput keys for that slot
    (e.g. ctrl -> {ctrl_l, ctrl_r}). ALL groups must have at least
    one key pressed for the hotkey to fire.

    Examples: '<ctrl>+<shift>+<alt>+q', '<scroll_lock>', 'f13'
    """
    parts = hotkey_str.replace("<", "").replace(">", "").split("+")
    groups = []
    for part in parts:
        part = part.strip().lower()
        if part in _SPECIAL_KEYS:
            groups.append(set(_SPECIAL_KEYS[part]))
        elif len(part) == 1:
            # Match both char-based and vk-based KeyCode (Windows reports vk when modifiers held)
            groups.append({
                keyboard.KeyCode.from_char(part),
                keyboard.KeyCode(vk=ord(part.upper())),
            })
    return groups


class App:
    def __init__(self):
        self.config = load_config()
        self.root = tk.Tk()
        self.root.withdraw()

        self.lens = LensWindow(self.root, self.config)
        self._busy = False
        self._current_popup: TranslationPopup | None = None

        # Exit button (optional)
        self._exit_btn = None
        if self.config.get("show_exit_button", True):
            self._exit_btn = ExitButton(
                self.root,
                self._quit,
                ai_url=self.config.get("ai_url", "http://localhost:12434"),
            )

        # Mouse listener for translate trigger
        self._mouse_listener = mouse.Listener(on_click=self._on_click)
        self._mouse_listener.start()

        # Keyboard listener for exit hotkey
        self._pressed_keys: set = set()
        self._exit_groups: list[set] = parse_exit_hotkey(
            self.config.get("exit_hotkey", "<ctrl>+<shift>+<alt>+q")
        )
        self._kb_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._kb_listener.start()

        exit_hotkey = self.config.get("exit_hotkey", "<ctrl>+q")
        show_btn = self.config.get("show_exit_button", True)
        print("OCR Translator running.")
        print("  Trigger : Middle mouse click")
        print(f"  Exit    : {exit_hotkey}" + (" / red Exit button" if show_btn else ""))
        print(f"  Model   : {self.config.get('model')} @ {self.config.get('ai_url')}")
        print("  Resize  : Left Shift + Scroll wheel\n")

        self.root.mainloop()

    # --- Mouse ---

    def _on_click(self, x, y, button, pressed):
        if button == mouse.Button.middle and pressed:
            self.root.after(0, self._trigger)

    # --- Keyboard (exit hotkey) ---

    def _on_key_press(self, key):
        self._pressed_keys.add(key)
        # Fire only when every group has at least one key currently held
        if all(group & self._pressed_keys for group in self._exit_groups):
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

    def _show_empty(self, cx: int, cy: int):
        self._current_popup = TranslationPopup(
            self.root,
            "(no text detected)",
            "(point the lens at English text and try again)",
            cx, cy,
            self.config,
        )
        self._busy = False

    def _quit(self):
        self._mouse_listener.stop()
        self._kb_listener.stop()
        self.root.quit()


def run() -> None:
    App()
