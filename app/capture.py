import mss
import numpy as np
from PIL import Image


def capture_region(spec: dict) -> Image.Image:
    """Capture the lens area; mask outside the shape to white.

    spec keys:
      shape: "ellipse" | "square" | "circle" (circle = legacy radius-only)
      cx, cy: center in screen coordinates
      square / ellipse: width, height (px, full bbox)
      circle (legacy): radius
    """
    shape = str(spec.get("shape", "circle")).lower()
    cx = int(spec["cx"])
    cy = int(spec["cy"])

    if shape == "square":
        return _capture_axis_mask(
            cx, cy, int(spec["width"]), int(spec["height"]), mode="rect"
        )

    if shape in ("ellipse", "circle"):
        if shape == "circle" and spec.get("radius") is not None and "width" not in spec:
            return _capture_circle_radius(cx, cy, int(spec["radius"]))
        w = int(spec["width"])
        h = int(spec["height"])
        return _capture_axis_mask(cx, cy, w, h, mode="ellipse")

    return _capture_circle_radius(cx, cy, int(spec.get("radius", 150)))


def _capture_circle_radius(cx: int, cy: int, radius: int) -> Image.Image:
    left = max(0, cx - radius)
    top = max(0, cy - radius)
    size = radius * 2

    with mss.mss() as sct:
        monitor = {"left": left, "top": top, "width": size, "height": size}
        raw = sct.grab(monitor)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

    arr = np.array(img)
    h, w = arr.shape[:2]
    cy_local, cx_local = h // 2, w // 2
    y_grid, x_grid = np.ogrid[:h, :w]
    outside = (x_grid - cx_local) ** 2 + (y_grid - cy_local) ** 2 > radius**2
    arr[outside] = 255

    return Image.fromarray(arr)


def _capture_axis_mask(
    cx: int, cy: int, width: int, height: int, *, mode: str
) -> Image.Image:
    """Grab screen rect for [cx,cy] ± half sizes; mask rect or ellipse."""
    half_w, half_h = width // 2, height // 2
    ax = max(width / 2.0, 0.5)
    ay = max(height / 2.0, 0.5)

    with mss.mss() as sct:
        mon = sct.monitors[1]
        ml, mt = mon["left"], mon["top"]
        mr, mb = ml + mon["width"], mt + mon["height"]
        left = max(ml, cx - half_w)
        top = max(mt, cy - half_h)
        right = min(mr, cx + half_w)
        bottom = min(mb, cy + half_h)
        rw = max(1, right - left)
        rh = max(1, bottom - top)
        raw = sct.grab({"left": left, "top": top, "width": rw, "height": rh})
    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    arr = np.array(img)
    hh, ww = arr.shape[:2]
    xx = np.arange(ww, dtype=np.float64) + float(left)
    yy = np.arange(hh, dtype=np.float64)[:, None] + float(top)

    if mode == "rect":
        outside = (np.abs(xx - cx) > half_w) | (np.abs(yy - cy) > half_h)
    else:
        dx = (xx - cx) / ax
        dy = (yy - cy) / ay
        outside = dx * dx + dy * dy > 1.0

    arr[outside] = 255
    return Image.fromarray(arr)
