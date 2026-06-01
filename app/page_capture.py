"""
Full-page scroll capture.

Scrolls the foreground window from top to bottom using Page Down keypresses,
captures screenshots at each step, and stitches them into one tall PIL Image.
"""
from __future__ import annotations

import time
from typing import Callable

import mss
import numpy as np
from PIL import Image


def _press_pagedown() -> None:
    import pyautogui
    pyautogui.press("pagedown")


def _goto_top() -> None:
    import pyautogui
    pyautogui.hotkey("ctrl", "Home")


def _find_cut_point(img_above: Image.Image, img_below: Image.Image, max_search: int = 500) -> int:
    """
    Find how many pixels from the top of img_below to discard (the overlapping region).

    Searches for the last strip of img_above inside the top of img_below.
    Returns the cut index: img_below[cut:] is the new non-overlapping content.
    Returns 0 if no reliable match found (means page didn't scroll).
    """
    h = img_above.height
    w = img_above.width
    strip_h = 40

    # Use a wide center column for robustness
    x1 = max(0, w // 2 - 300)
    x2 = min(w, w // 2 + 300)

    ref = np.array(img_above.crop((x1, h - strip_h, x2, h))).astype(np.float32)

    search_limit = min(max_search, img_below.height - strip_h)
    best_diff = float("inf")
    best_y = -1

    for y in range(0, search_limit, 3):
        candidate = np.array(img_below.crop((x1, y, x2, y + strip_h))).astype(np.float32)
        diff = float(np.abs(ref - candidate).mean())
        if diff < best_diff:
            best_diff = diff
            best_y = y
        if diff < 2.0:
            break

    # If best match is poor the page didn't scroll — signal caller to stop
    if best_diff > 20.0 or best_y < 0:
        return 0

    return best_y + strip_h


def _images_same(a: Image.Image, b: Image.Image, threshold: float = 3.0) -> bool:
    """True when two screenshots are nearly identical (scroll position didn't change)."""
    # Compare the middle half to avoid browser chrome at top/bottom
    mid_y1 = a.height // 4
    mid_y2 = a.height * 3 // 4
    aa = np.array(a.crop((0, mid_y1, a.width, mid_y2))).astype(np.float32)
    bb = np.array(b.crop((0, mid_y1, b.width, mid_y2))).astype(np.float32)
    return float(np.abs(aa - bb).mean()) < threshold


def _stitch(strips: list[Image.Image]) -> Image.Image:
    """Stitch overlapping screenshots into one tall image."""
    if len(strips) == 1:
        return strips[0]

    w = strips[0].width
    segments: list[tuple[Image.Image, int]] = [(strips[0], 0)]

    for i in range(1, len(strips)):
        cut = _find_cut_point(strips[i - 1], strips[i])
        segments.append((strips[i], cut))

    total_h = sum(img.height - cut for img, cut in segments)
    result = Image.new("RGB", (w, total_h))
    y = 0
    for img, cut in segments:
        region = img.crop((0, cut, w, img.height))
        result.paste(region, (0, y))
        y += region.height

    return result


def capture_full_page(
    progress_callback: Callable[[int, str], None] | None = None,
    scroll_pause: float = 0.25,
    max_screenshots: int = 60,
) -> Image.Image:
    """
    Scroll the foreground window from top to bottom and stitch all screenshots.

    Returns a single tall PIL Image of the full page.
    progress_callback(step, message) is called after each screenshot.
    """
    if progress_callback:
        progress_callback(0, "Scrolling to top of page...")

    _goto_top()
    time.sleep(0.5)

    strips: list[Image.Image] = []
    prev_img: Image.Image | None = None

    with mss.mss() as sct:
        monitor = sct.monitors[1]

        for step in range(max_screenshots):
            raw = sct.grab(monitor)
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

            if prev_img is not None and _images_same(prev_img, img):
                # Page didn't scroll — we're at the bottom
                break

            strips.append(img)
            prev_img = img

            if progress_callback:
                progress_callback(step + 1, f"Capturing screenshot {step + 1}...")

            _press_pagedown()
            time.sleep(scroll_pause)

    if not strips:
        # Fallback: single screenshot
        with mss.mss() as sct:
            raw = sct.grab(sct.monitors[1])
            return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

    if progress_callback:
        progress_callback(len(strips), f"Stitching {len(strips)} screenshots...")

    return _stitch(strips)
