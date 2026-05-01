import mss
import numpy as np
from PIL import Image


def capture_region(cx: int, cy: int, radius: int) -> Image.Image:
    """Capture the lens circle area with outside pixels masked to white."""
    left = max(0, cx - radius)
    top = max(0, cy - radius)
    size = radius * 2

    with mss.mss() as sct:
        monitor = {"left": left, "top": top, "width": size, "height": size}
        raw = sct.grab(monitor)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

    # Mask pixels outside the circle to white so OCR ignores background
    arr = np.array(img)
    h, w = arr.shape[:2]
    cy_local, cx_local = h // 2, w // 2
    y_grid, x_grid = np.ogrid[:h, :w]
    outside = (x_grid - cx_local) ** 2 + (y_grid - cy_local) ** 2 > radius ** 2
    arr[outside] = 255

    return Image.fromarray(arr)
