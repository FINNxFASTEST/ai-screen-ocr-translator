"""Shared hotkey parsing (pynput) and Tk keybinding recorder formatting."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pynput import keyboard

if TYPE_CHECKING:
    from tkinter import Event as TkEvent
else:
    TkEvent = object


_SPECIAL_KEYS = {
    "ctrl": (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r),
    "shift": (keyboard.Key.shift_l, keyboard.Key.shift_r, keyboard.Key.shift),
    "alt": (keyboard.Key.alt_l, keyboard.Key.alt_r),
    "scroll_lock": (keyboard.Key.scroll_lock,),
    "pause": (keyboard.Key.pause,),
    "caps_lock": (keyboard.Key.caps_lock,),
    "space": (keyboard.Key.space,),
    "enter": (keyboard.Key.enter,),
    "tab": (keyboard.Key.tab,),
    "escape": (keyboard.Key.esc,),
    "prior": (keyboard.Key.page_up,),
    "next": (keyboard.Key.page_down,),
    "page_up": (keyboard.Key.page_up,),
    "page_down": (keyboard.Key.page_down,),
    "home": (keyboard.Key.home,),
    "end": (keyboard.Key.end,),
    "insert": (keyboard.Key.insert,),
    "delete": (keyboard.Key.delete,),
    "left": (keyboard.Key.left,),
    "right": (keyboard.Key.right,),
    "up": (keyboard.Key.up,),
    "down": (keyboard.Key.down,),
    **{f"f{n}": (getattr(keyboard.Key, f"f{n}"),) for n in range(1, 21)},
}

_KEYS_BY_NAME = {
    "comma": keyboard.KeyCode.from_char(","),
    "period": keyboard.KeyCode.from_char("."),
    "slash": keyboard.KeyCode.from_char("/"),
    "semicolon": keyboard.KeyCode.from_char(";"),
    "quote": keyboard.KeyCode.from_char("'"),
    "grave": keyboard.KeyCode.from_char("`"),
    "minus": keyboard.KeyCode.from_char("-"),
    "equals": keyboard.KeyCode.from_char("="),
    "plus": keyboard.KeyCode.from_char("+"),
    "bracketleft": keyboard.KeyCode.from_char("["),
    "bracketright": keyboard.KeyCode.from_char("]"),
    "backslash": keyboard.KeyCode.from_char("\\"),
}


def parse_hotkey(hotkey_str: str) -> list[set]:
    """Parse '<ctrl>+q' style strings into groups of acceptable pynput keys."""
    raw = hotkey_str.replace("<", "").replace(">", "").split("+")
    parts = [p.strip().lower() for p in raw if p.strip()]
    groups: list[set] = []
    for part in parts:
        if part in _SPECIAL_KEYS:
            groups.append(set(_SPECIAL_KEYS[part]))
        elif part in _KEYS_BY_NAME:
            groups.append({_KEYS_BY_NAME[part]})
        elif len(part) == 1:
            ch = part
            groups.append(
                {
                    keyboard.KeyCode.from_char(ch.lower()),
                    keyboard.KeyCode.from_char(ch.upper()),
                    keyboard.KeyCode(vk=ord(ch.upper())),
                }
            )
    return groups


def hotkey_readable(hotkey_str: str, mouse_labels: dict[str, str]) -> str:
    s = hotkey_str.strip().lower()
    if s in mouse_labels:
        return mouse_labels[s]
    return hotkey_str.strip() or "(not set)"


def _compose_mods_and_main(mod_bits: list[str], main: str) -> str:
    return "+".join(mod_bits + [main])


def tk_key_event_to_hotkey(event: TkEvent) -> str | None:
    """Build storage string from a Tk KeyPress; None until a non-modifier key is pressed."""

    keysym = (event.keysym or "").strip()
    ks_num = getattr(event, "keysym_num", None)
    char = event.char or ""

    modifier_only = {
        "Shift_L",
        "Shift_R",
        "Control_L",
        "Control_R",
        "Alt_L",
        "Alt_R",
        "Win_L",
        "Win_R",
        "Meta_L",
        "Meta_R",
    }
    if keysym in modifier_only:
        return None
    if keysym == "Escape":
        return None

    try:
        state = int(event.state or 0)
    except (TypeError, ValueError):
        state = 0

    SHIFT = 0x0001
    CONTROL = 0x0004
    ALT_WIN = 0x20000
    CONTROL_EXT = 0x40000

    mods: list[str] = []
    if bool(state & CONTROL) or bool(state & CONTROL_EXT):
        mods.append("<ctrl>")
    if bool(state & SHIFT):
        mods.append("<shift>")
    if bool(state & ALT_WIN):
        mods.append("<alt>")

    def finish(main_segment: str) -> str | None:
        if not main_segment:
            return None
        return _compose_mods_and_main(mods, main_segment)

    if len(keysym) >= 2 and keysym.startswith("F") and keysym[1:].isdigit():
        return finish(keysym.lower()) or keysym.lower()

    lone = keysym.lower()
    keysym_terminal = {
        "return": "<enter>",
        "kp_enter": "<enter>",
        "tab": "<tab>",
        "space": "<space>",
        "prior": "<prior>",
        "next": "<next>",
        "home": "<home>",
        "end": "<end>",
        "insert": "<insert>",
        "delete": "<delete>",
        "left": "<left>",
        "right": "<right>",
        "up": "<up>",
        "down": "<down>",
    }
    if lone in keysym_terminal:
        got = finish(keysym_terminal[lone])
        return got if got else None

    if ks_num == 65307 and not char:
        got = finish("<escape>")
        return got if got else None

    if lone.startswith("kp_"):
        sub = lone.replace("kp_", "")
        if sub.isdigit():
            return finish(sub)
        if sub in ("add",):
            return finish("+")
        if sub in ("subtract",):
            return finish("-")
        if sub in ("multiply",):
            return finish("*")
        if sub in ("divide",):
            return finish("/")
        if sub in ("decimal",):
            return finish(".")
        if sub == "enter":
            return finish("<enter>")

    if len(char) == 1:
        oc = ord(char)
        if oc >= 32 and oc != 127:
            return finish(char.lower()) if char.isalpha() else finish(char)

    keysym_aliases: dict[str, str] = {
        "comma": ",",
        "period": ".",
        "slash": "/",
        "semicolon": ";",
        "apostrophe": "'",
        "quotedbl": '"',
        "grave": "`",
        "minus": "-",
        "equal": "=",
        "plus": "+",
        "bracketleft": "[",
        "bracketright": "]",
        "backslash": "\\",
        "colon": ":",
        "underscore": "_",
        "greater": ">",
        "less": "<",
    }
    if lone in keysym_aliases:
        return finish(keysym_aliases[lone])

    return None


def validate_keyboard_hotkey_string(s: str) -> str | None:
    """Return error message if invalid keyboard shortcut string, else None."""
    t = (s or "").strip()
    if not t:
        return "Shortcut cannot be empty."
    g = parse_hotkey(t)
    if not g:
        return (
            'Invalid shortcut. Examples: "f12", "<ctrl>+space", '
            '"<shift>+<f10>".'
        )
    return None


def config_capture_trigger_raw(cfg: dict) -> str:
    """Prefer capture_hotkey; fall back to legacy hotkey key."""
    return str(cfg.get("capture_hotkey") or cfg.get("hotkey", "middle_click")).strip()


def normalize_lens_wheel_mod(raw: object) -> str:
    """Config token for which modifier combines with mouse wheel for lens resize (Windows)."""
    t = str(raw or "alt").strip().lower()
    if t in ("control",):
        t = "ctrl"
    if t in ("windows", "meta"):
        t = "win"
    if t not in ("alt", "shift", "ctrl", "win"):
        return "alt"
    return t


def lens_scroll_modifier_key_set(name: str) -> frozenset:
    """Pynput keys counted as held for one lens wheel-modifier axis (width or height)."""
    n = normalize_lens_wheel_mod(name)
    keys: set = set()
    if n == "alt":
        keys.update(_SPECIAL_KEYS["alt"])
        if hasattr(keyboard.Key, "alt"):
            keys.add(keyboard.Key.alt)
    elif n == "shift":
        keys.update(_SPECIAL_KEYS["shift"])
    elif n == "ctrl":
        keys.update(_SPECIAL_KEYS["ctrl"])
        if hasattr(keyboard.Key, "ctrl"):
            keys.add(keyboard.Key.ctrl)
    elif n == "win":
        for attr in ("cmd", "cmd_l", "cmd_r"):
            if hasattr(keyboard.Key, attr):
                keys.add(getattr(keyboard.Key, attr))
    return frozenset(keys)
