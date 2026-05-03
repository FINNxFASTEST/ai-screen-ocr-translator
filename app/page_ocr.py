"""
OCR with bounding box extraction for the full-page translation overlay.

Extends PaddleOCR to return per-block bounding boxes instead of just joined text.
Nearby lines are grouped into speech bubbles so each bubble is one translation unit.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

from app.ocr_engine import _OCR_DEFAULTS, _extract_lines, _fix_case, _join_lines, get_reader


def _poly_to_bbox(poly: list, upscale: int) -> list[int]:
    """Convert a PaddleOCR polygon (4 points) to [x, y, w, h] in original image coords."""
    pts = np.array(poly, dtype=float) / max(upscale, 1)
    x_min = int(pts[:, 0].min())
    y_min = int(pts[:, 1].min())
    x_max = int(pts[:, 0].max())
    y_max = int(pts[:, 1].max())
    return [x_min, y_min, x_max - x_min, y_max - y_min]


def _group_lines(
    lines: list[tuple],
    upscale: int,
    gap_threshold: int = 18,
) -> list[list[tuple]]:
    """
    Group OCR lines that are vertically close (same speech bubble) together.

    Returns a list of groups, each group is a list of (poly, text, score) tuples.
    gap_threshold is in original-image pixels.
    """
    if not lines:
        return []

    # Sort top-to-bottom using the upscale-adjusted y of the top-left corner
    def _top_y(line):
        poly = line[0]
        pts = np.array(poly, dtype=float) / max(upscale, 1)
        return float(pts[:, 1].min())

    sorted_lines = sorted(lines, key=_top_y)

    groups: list[list[tuple]] = [[sorted_lines[0]]]

    for line in sorted_lines[1:]:
        poly = line[0]
        pts = np.array(poly, dtype=float) / max(upscale, 1)
        line_top = float(pts[:, 1].min())

        # Compare with bottom of the last line in the current group
        last_poly = groups[-1][-1][0]
        last_pts = np.array(last_poly, dtype=float) / max(upscale, 1)
        last_bottom = float(last_pts[:, 1].max())

        if line_top - last_bottom <= gap_threshold:
            groups[-1].append(line)
        else:
            groups.append([line])

    return groups


def _merged_bbox(group: list[tuple], upscale: int) -> list[int]:
    """Return the bounding rect of all polys in a group, in original coords."""
    all_pts: list[np.ndarray] = []
    for poly, _, _ in group:
        pts = np.array(poly, dtype=float) / max(upscale, 1)
        all_pts.append(pts)
    combined = np.vstack(all_pts)
    x_min = int(combined[:, 0].min())
    y_min = int(combined[:, 1].min())
    x_max = int(combined[:, 0].max())
    y_max = int(combined[:, 1].max())
    return [x_min, y_min, x_max - x_min, y_max - y_min]


# OpenCV's remap (used internally by PaddleOCR) silently crashes or raises when
# the image passed to it exceeds SHRT_MAX (32767) pixels in either dimension
# after the upscale step.  We split tall images into overlapping chunks and
# merge the results so callers never hit this limit.
_CHUNK_MAX_PX = 4000   # safe height per chunk in *original* image pixels
_CHUNK_OVERLAP = 100   # overlap between chunks to avoid cutting through text


def _ocr_chunk(
    image: Image.Image,
    cfg: dict,
    reader,
    upscale: int,
    min_score: float,
) -> list[tuple]:
    """Run OCR on a single image chunk, return raw (poly, text, score) tuples."""
    from app.ocr_engine import _preprocess
    processed = _preprocess(image, cfg)
    img_array = np.array(processed)
    result = reader.ocr(img_array)
    return _extract_lines(result, min_score)


def extract_blocks(
    image: Image.Image,
    ocr_config: dict | None = None,
    group_gap_px: int = 18,
) -> list[dict]:
    """
    Run PaddleOCR and return grouped text blocks with bounding boxes.

    Each block:
        {
            "text":  str,           # joined text of the group
            "bbox":  [x, y, w, h],  # bounding rect in original image coords
            "score": float,         # mean confidence score
        }

    Lines within group_gap_px of each other are merged into one block so that
    multi-line speech bubbles translate as a single unit.

    Tall images are automatically split into chunks to stay within OpenCV's
    32767-pixel-per-dimension hard limit.
    """
    cfg = ocr_config or {}

    paddle_lang = str(cfg.get("paddle_lang") or "en").strip() or "en"
    reader = get_reader(paddle_lang)

    upscale = int(cfg.get("upscale", _OCR_DEFAULTS["upscale"]))
    min_score = float(cfg.get("rec_score_threshold", _OCR_DEFAULTS["rec_score_threshold"]))

    orig_w, orig_h = image.size

    # ── Split into chunks if image is too tall ────────────────────────────
    # The limit applies to the *upscaled* image, so divide by upscale.
    safe_chunk_h = min(_CHUNK_MAX_PX, max(200, 32000 // max(upscale, 1)))

    all_lines: list[tuple] = []

    if orig_h <= safe_chunk_h:
        all_lines = _ocr_chunk(image, cfg, reader, upscale, min_score)
    else:
        y = 0
        while y < orig_h:
            chunk_h = min(safe_chunk_h, orig_h - y)
            chunk = image.crop((0, y, orig_w, y + chunk_h))
            chunk_lines = _ocr_chunk(chunk, cfg, reader, upscale, min_score)

            # Shift polygon y-coords by the chunk's offset in the full image
            # (polys are in upscaled space, so offset must be scaled too)
            y_offset_upscaled = y * upscale
            shifted: list[tuple] = []
            for poly, text, score in chunk_lines:
                shifted_poly = [
                    [pt[0], pt[1] + y_offset_upscaled] for pt in poly
                ]
                shifted.append((shifted_poly, text, score))

            # Deduplicate lines that fall in the overlap zone of the previous chunk.
            # A line is a duplicate if its top-y (in original coords) is less than
            # the previous chunk's bottom minus the overlap.
            if y > 0 and shifted:
                overlap_start_orig = y - _CHUNK_OVERLAP
                filtered = []
                for poly, text, score in shifted:
                    pts = np.array(poly, dtype=float) / max(upscale, 1)
                    line_top = float(pts[:, 1].min())
                    if line_top >= overlap_start_orig:
                        filtered.append((poly, text, score))
                shifted = filtered

            all_lines.extend(shifted)

            # Advance by chunk_h minus overlap so we don't miss text at boundaries
            y += chunk_h - _CHUNK_OVERLAP
            if y >= orig_h:
                break

    if not all_lines:
        return []

    groups = _group_lines(all_lines, upscale, gap_threshold=group_gap_px)

    blocks: list[dict] = []
    for group in groups:
        texts = [ln[1] for ln in group]
        text = _join_lines(texts)

        if cfg.get("fix_case", _OCR_DEFAULTS["fix_case"]):
            text = _fix_case(text)

        text = text.strip()
        if not text:
            continue

        bbox = _merged_bbox(group, upscale)
        mean_score = float(np.mean([ln[2] for ln in group]))

        blocks.append({"text": text, "bbox": bbox, "score": mean_score})

    return blocks
