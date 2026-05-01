import io
import re
import sys
import warnings
from datetime import datetime
from pathlib import Path
import numpy as np
import easyocr
from PIL import Image, ImageEnhance, ImageFilter

warnings.filterwarnings("ignore", message=".*pin_memory.*", category=UserWarning)

_reader = None
_DEBUG_DIR = Path(__file__).parent / "debug"

# OCR tuning defaults — can be overridden via config.json "ocr" key
_OCR_DEFAULTS = {
    "upscale": 2,             # multiply image dimensions before OCR (1 = off)
    "contrast": 1.8,          # ImageEnhance.Contrast factor (1.0 = unchanged)
    "sharpness": 2.5,         # ImageEnhance.Sharpness factor (1.0 = unchanged)
    "binarize": True,         # adaptive threshold — cleans manga speech bubbles
    "text_threshold": 0.6,    # EasyOCR: confidence threshold for text detection
    "low_text": 0.4,          # EasyOCR: score for low-confidence text regions
    "link_threshold": 0.4,    # EasyOCR: threshold for linking character boxes
    "mag_ratio": 2.0,         # EasyOCR: internal image magnification
    "min_size": 8,            # EasyOCR: smallest acceptable text height (px)
    "fix_case": True,         # convert ALL-CAPS manga text to sentence case
}


def get_reader() -> easyocr.Reader:
    global _reader
    if _reader is None:
        _sink = io.StringIO()
        sys.stdout, sys.stderr = _sink, _sink
        try:
            _reader = easyocr.Reader(["en"], gpu=False)
        finally:
            sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
    return _reader


def _otsu_threshold(arr: np.ndarray) -> int:
    """Find the optimal binarization threshold using Otsu's method."""
    hist = np.bincount(arr.flatten(), minlength=256).astype(float)
    total = arr.size
    sum_total = float(np.dot(np.arange(256), hist))
    w_b, sum_b, max_var, best = 0.0, 0.0, 0.0, 127
    for t in range(256):
        w_b += hist[t]
        w_f = total - w_b
        if w_b == 0 or w_f == 0:
            continue
        sum_b += t * hist[t]
        mean_b = sum_b / w_b
        mean_f = (sum_total - sum_b) / w_f
        var = w_b * w_f * (mean_b - mean_f) ** 2
        if var > max_var:
            max_var = var
            best = t
    return best


def _preprocess(image: Image.Image, cfg: dict) -> Image.Image:
    upscale = cfg.get("upscale", _OCR_DEFAULTS["upscale"])
    if upscale > 1:
        w, h = image.size
        image = image.resize((w * upscale, h * upscale), Image.LANCZOS)

    image = image.convert("L")  # grayscale — removes colour noise

    # Denoise before thresholding so salt-and-pepper noise doesn't create fake edges
    image = image.filter(ImageFilter.MedianFilter(size=3))

    if cfg.get("binarize", _OCR_DEFAULTS["binarize"]):
        arr = np.array(image)
        threshold = _otsu_threshold(arr)
        binary = (arr > threshold).astype(np.uint8) * 255
        image = Image.fromarray(binary, mode="L")

    contrast = cfg.get("contrast", _OCR_DEFAULTS["contrast"])
    if contrast != 1.0:
        image = ImageEnhance.Contrast(image).enhance(contrast)

    sharpness = cfg.get("sharpness", _OCR_DEFAULTS["sharpness"])
    if sharpness != 1.0:
        image = ImageEnhance.Sharpness(image).enhance(sharpness)

    image = image.filter(ImageFilter.SHARPEN)

    return image.convert("RGB")


def _fix_case(text: str) -> str:
    """Convert ALL-CAPS manga text to sentence case.

    Manga fonts are almost always bold all-caps, so OCR output is correct but
    hard to read and translates poorly. This detects when >80% of letters are
    uppercase and normalises to sentence case while keeping standalone 'I'.
    """
    if not text:
        return text
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return text
    upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
    if upper_ratio < 0.8:
        return text  # already mixed case — leave untouched

    text = text.lower()
    # Capitalise the very first character
    text = re.sub(r'^([a-z])', lambda m: m.group(1).upper(), text)
    # Capitalise first letter after sentence-ending punctuation
    text = re.sub(r'([.!?]\s+)([a-z])', lambda m: m.group(1) + m.group(2).upper(), text)
    # Keep standalone 'i' capitalised
    text = re.sub(r'\bi\b', 'I', text)
    return text


def _save_debug(tag: str, image: Image.Image, label: str) -> None:
    _DEBUG_DIR.mkdir(exist_ok=True)
    path = _DEBUG_DIR / f"{tag}_{label}.png"
    image.save(path)
    print(f"[DEBUG] saved {path}")


def extract_text(image: Image.Image, ocr_config: dict | None = None) -> str:
    cfg = ocr_config or {}
    debug = cfg.get("debug", False)

    reader = get_reader()

    tag = datetime.now().strftime("%H%M%S_%f")[:9]  # e.g. "143052_12"
    if debug:
        _save_debug(tag, image, "1_raw")

    processed = _preprocess(image, cfg)

    if debug:
        _save_debug(tag, processed, "2_preprocessed")

    img_array = np.array(processed)

    results = reader.readtext(
        img_array,
        detail=0,
        paragraph=True,
        text_threshold=cfg.get("text_threshold", _OCR_DEFAULTS["text_threshold"]),
        low_text=cfg.get("low_text", _OCR_DEFAULTS["low_text"]),
        link_threshold=cfg.get("link_threshold", _OCR_DEFAULTS["link_threshold"]),
        mag_ratio=cfg.get("mag_ratio", _OCR_DEFAULTS["mag_ratio"]),
        min_size=cfg.get("min_size", _OCR_DEFAULTS["min_size"]),
    )

    text = " ".join(results).strip()
    if cfg.get("fix_case", _OCR_DEFAULTS["fix_case"]):
        text = _fix_case(text)
    return text
