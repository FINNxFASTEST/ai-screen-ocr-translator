"""Per-series translation context and stable series keys for memory scoping."""

from __future__ import annotations

import re
from typing import Any

DEFAULT_SERIES_KEY = "default"

# Sentinel combobox label for translate.active_series == "" (no profile).
READING_COMBO_NONE = "(none)"


def profile_system_context(profile: dict[str, Any] | None) -> str:
    """Main series context plus optional glossary, sent as one system message block."""
    if not isinstance(profile, dict):
        return ""
    ctx = str(profile.get("context", "") or "").strip()
    gloss = str(profile.get("glossary", "") or "").strip()
    if ctx and gloss:
        return f"{ctx}\n\n{gloss}"
    return ctx or gloss


def slugify_series_key(name: str, existing_keys: frozenset[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "series"
    if base not in existing_keys:
        return base
    n = 2
    while f"{base}_{n}" in existing_keys:
        n += 1
    return f"{base}_{n}"


def migrate_translate_to_profiles(translate: dict[str, Any] | None) -> None:
    """Ensure translate has series_profiles + active_series; migrate legacy flat fields."""
    if not isinstance(translate, dict):
        return
    profiles = translate.get("series_profiles")
    if isinstance(profiles, dict) and profiles:
        if "active_series" not in translate:
            translate["active_series"] = next(iter(profiles.keys()))
            return
        raw = translate.get("active_series")
        if isinstance(raw, str) and raw.strip() == "":
            translate["active_series"] = ""
            return
        active = str(raw).strip()
        if active not in profiles:
            translate["active_series"] = next(iter(profiles.keys()))
        return

    legacy_ctx = translate.get("context", "") or ""
    legacy_name = (translate.get("series_name") or "").strip()
    label = legacy_name or "Default"
    translate["series_profiles"] = {
        DEFAULT_SERIES_KEY: {
            "label": label,
            "context": str(legacy_ctx),
            "series_name": legacy_name,
            "glossary": "",
        }
    }
    translate["active_series"] = DEFAULT_SERIES_KEY


def append_translate_profile_note(
    config: dict[str, Any],
    series_key: str,
    field: str,
    line: str,
) -> tuple[bool, str]:
    """Append one non-empty line to profile glossary or series context (mutates config)."""
    line = line.strip()
    if not line:
        return False, "Nothing to append."
    if field not in ("glossary", "context"):
        return False, "Invalid save target."

    translate = config.setdefault("translate", {})
    migrate_translate_to_profiles(translate)
    profiles = translate.get("series_profiles")

    if not isinstance(profiles, dict) or not profiles:
        return False, "No series profiles in config."
    sk = str(series_key or "").strip()
    if not sk or sk not in profiles:
        return False, 'Choose an active manga profile in Settings (not "(none)") to save notes.'
    prof = profiles[sk]
    if not isinstance(prof, dict):
        return False, "Invalid profile data."
    cur = str(prof.get(field, "") or "").rstrip()
    prof[field] = f"{cur}\n{line}" if cur else line
    return True, ""


def get_active_series_translation(config: dict[str, Any]) -> tuple[str, str]:
    """
    Effective (series_key, context) for OCR→translate pipeline.
    Does not mutate config.
    """
    t = config.get("translate") or {}
    profiles = t.get("series_profiles")

    if isinstance(profiles, dict) and profiles:
        if "active_series" in t:
            raw_act = t.get("active_series")
            if isinstance(raw_act, str) and raw_act.strip() == "":
                return "", ""
            active = str(raw_act).strip() or DEFAULT_SERIES_KEY
        else:
            active = DEFAULT_SERIES_KEY
        if active not in profiles:
            active = next(iter(profiles.keys()))
        prof = profiles.get(active)
        if isinstance(prof, dict):
            return active, profile_system_context(prof)
        return active, ""

    ctx = str(t.get("context", ""))
    return DEFAULT_SERIES_KEY, ctx


def profile_label(profiles: dict[str, Any], key: str) -> str:
    p = profiles.get(key)
    if isinstance(p, dict):
        lab = str(p.get("label", "")).strip()
        return lab if lab else key
    return key


def combo_display_for_key(profiles: dict[str, Any], key: str) -> str:
    """Unique combobox row: readable label plus key in parentheses."""
    return f'{profile_label(profiles, key)}  ({key})'


def parse_key_from_combo(text: str) -> str | None:
    """Extract series key from 'Label  (slug)' combo value."""
    t = str(text).strip()
    if not t:
        return None
    if t.endswith(")") and "(" in t:
        return t[t.rfind("(") + 1 : -1].strip()
    return None


def reading_pick_to_series_key(pick_text: str) -> str | None:
    """
    Reading combobox value → profile slug, "", or None if invalid/cleared.
    None triggers UI restore back to valid selection.
    """
    raw = str(pick_text).strip()
    if not raw:
        return None
    if raw == READING_COMBO_NONE:
        return ""
    return parse_key_from_combo(raw)
