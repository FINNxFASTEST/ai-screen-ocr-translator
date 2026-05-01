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
    "win": tuple(
        k
        for k in (
            getattr(keyboard.Key, n, None)
            for n in ("cmd", "cmd_l", "cmd_r", "win", "win_l", "win_r")
        )
        if k is not None
    ),
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


TK_MODIFIER_KEYSYMS: frozenset[str] = frozenset(
    {
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
        "Super_L",
        "Super_R",
    }
)


def normalize_modifier_keysym_for_held(raw: str) -> str | None:
    """Return a lowercase stable id for Tk modifier tracking, or None.

    Windows Tk sometimes uses different casings (`control_l`), names (`ISO_Left_Control`),
    or synonyms (`Ctrl_L`). Excluded keys must not collide with real keysyms.
    """

    kl = (raw or "").strip().lower()
    if not kl:
        return None

    alias_map: dict[str, str] = {
        "ctrl_l": "control_l",
        "ctrl_r": "control_r",
        "iso_left_control": "control_l",
        "iso_right_control": "control_r",
        "apple_l": "meta_l",
        "apple_r": "meta_r",
    }
    kl = alias_map.get(kl, kl)

    if kl.startswith(("control_", "shift_", "alt_", "win_", "meta_", "super_")):
        return kl
    if kl in (
        "shift_l",
        "shift_r",
        "control_l",
        "control_r",
        "alt_l",
        "alt_r",
        "win_l",
        "win_r",
        "meta_l",
        "meta_r",
        "super_l",
        "super_r",
    ):
        return kl
    if kl.startswith("iso_") and "control" in kl:
        return "control_l"
    return None


def tk_held_keysyms_to_modifier_tokens(held: set[str]) -> list[str]:
    """Map raw Tk modifier keysyms (still held) to ordered <ctrl>/<shift>/<alt>/<win> tokens."""
    canon: list[str] = []
    for k in held:
        n = normalize_modifier_keysym_for_held(k)
        if n:
            canon.append(n)
    has_ctrl = any(c.startswith("control_") for c in canon)
    has_shift = any(c.startswith("shift_") for c in canon)
    has_alt = any(c.startswith("alt_") for c in canon)
    has_win = any(
        c in ("win_l", "win_r", "meta_l", "meta_r", "super_l", "super_r")
        or c.startswith("win_")
        or c.startswith("meta_")
        or c.startswith("super_")
        for c in canon
    )
    out: list[str] = []
    if has_ctrl:
        out.append("<ctrl>")
    if has_shift:
        out.append("<shift>")
    if has_alt:
        out.append("<alt>")
    if has_win:
        out.append("<win>")
    return out


def tk_event_state_to_modifier_tokens(event: TkEvent) -> list[str]:
    """Modifier bits from Tk KeyPress state (covers Ctrl when physical KeyPress was not delivered)."""
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
    return mods


_MODIFIER_ORDER = ("<ctrl>", "<shift>", "<alt>", "<win>")


def tk_merge_modifier_token_lists(*lists: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for token in _MODIFIER_ORDER:
        if any(token in lst for lst in lists if lst) and token not in seen:
            out.append(token)
            seen.add(token)
    for lst in lists:
        for t in lst:
            if t not in seen:
                out.append(t)
                seen.add(t)
    return out


def tk_listen_combine_modifiers(held_keysyms: set[str], event: TkEvent) -> list[str]:
    """Physical modifier keys + event.state (Windows Tk needs both for reliable Ctrl)."""
    return tk_merge_modifier_token_lists(
        tk_held_keysyms_to_modifier_tokens(held_keysyms),
        tk_event_state_to_modifier_tokens(event),
    )


def tk_key_event_to_hotkey(
    event: TkEvent,
    *,
    modifier_tokens: list[str] | None = None,
    use_event_modifiers: bool = True,
) -> str | None:
    """Build storage string from a Tk KeyPress; None until a non-modifier key is pressed.

    Prefer passing modifier_tokens from KeyPress/KeyRelease tracking (Settings “Listen”).
    That matches other apps’ recorders and avoids bogus modifier bits from event.state on
    Windows Tk. If modifier_tokens is None and use_event_modifiers is False, only the main
    key is stored (legacy). If modifier_tokens is None and use_event_modifiers is True,
    modifiers are inferred from event.state.
    """

    keysym = (event.keysym or "").strip()
    ks_num = getattr(event, "keysym_num", None)
    char = event.char or ""

    if normalize_modifier_keysym_for_held(keysym) is not None:
        return None
    if keysym == "Escape":
        return None

    mods: list[str] = []
    if modifier_tokens is not None:
        mods.extend(modifier_tokens)
    elif use_event_modifiers:
        try:
            state = int(event.state or 0)
        except (TypeError, ValueError):
            state = 0

        SHIFT = 0x0001
        CONTROL = 0x0004
        ALT_WIN = 0x20000
        CONTROL_EXT = 0x40000

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

    # Ctrl/Alt combos: char is often a control byte (\x01–\x1f); keysym still names the key.
    if len(keysym) == 1 and keysym.isalnum():
        return finish(keysym.lower()) if keysym.isalpha() else finish(keysym)

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
            '"<ctrl>+<shift>+<alt>+q", "<win>+e".'
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
