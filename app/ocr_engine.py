import contextlib
import io
import logging
import os
import re
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter


warnings.filterwarnings("ignore")

# Silence PaddleOCR / ppocr / paddle loggers at import time so they never
# inherit the root logger's level and start chattering on first use.
for _noisy in ("ppocr", "paddleocr", "paddle", "paddle.fluid"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

_reader = None
_reader_lang: str | None = None
_reader_use_gpu: bool | None = None
_DEBUG_DIR = Path(__file__).resolve().parents[1] / "debug"

# OCR tuning defaults — can be overridden via config.json "ocr" key
_OCR_DEFAULTS = {
    "upscale": 2,               # multiply image dimensions before OCR (1 = off)
    "contrast": 1.8,            # ImageEnhance.Contrast factor (1.0 = unchanged)
    "sharpness": 2.5,           # ImageEnhance.Sharpness factor (1.0 = unchanged)
    "binarize": True,           # Otsu threshold — cleans manga speech bubbles
    "text_threshold": 0.3,      # PaddleOCR det_db_thresh: lower = more detections
    "rec_score_threshold": 0.5, # minimum recognition confidence to keep a line
    "use_angle_cls": True,      # enable angle classifier for tilted/rotated text
    "fix_case": True,           # convert ALL-CAPS manga text to sentence case
    "word_segment": True,       # split merged words like "whywe" → "why we"
}


def get_reader(lang: str = "en", use_gpu: bool = False):
    """Return a PaddleOCR reader for the given language code (e.g. en, japan, korean).

    use_gpu=True requires paddlepaddle-gpu to be installed:
        pip uninstall paddlepaddle
        pip install paddlepaddle-gpu
    """
    global _reader, _reader_lang, _reader_use_gpu
    code = (lang or "en").strip() or "en"
    # Recreate reader if lang or gpu setting changed
    if _reader is not None and (_reader_lang != code or _reader_use_gpu != use_gpu):
        _reader = None
        _reader_lang = None
        _reader_use_gpu = None
    if _reader is None:
        import paddle
        try:
            paddle.set_flags({"FLAGS_use_mkldnn": False, "FLAGS_enable_pir_api": False})
        except Exception:
            pass
        from paddleocr import PaddleOCR
        # Redirect stderr during construction — PaddleOCR writes model-download
        # and framework messages directly to sys.stderr bypassing logging.
        with contextlib.redirect_stderr(io.StringIO()):
            _reader = PaddleOCR(
                use_angle_cls=True,
                lang=code,
                show_log=False,
                use_gpu=use_gpu,
            )
        _reader_lang = code
        _reader_use_gpu = use_gpu
        if use_gpu:
            print("  OCR     : PaddleOCR GPU enabled")
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


def _segment_words(text: str) -> str:
    """Re-insert spaces into merged words produced by OCR (e.g. 'whywe' → 'why we').

    Only tokens that look like merged words are touched: pure-alpha, all-lowercase,
    longer than 5 chars, and not a known single English word.  Punctuation-bearing
    tokens (contractions, hyphenated words) are left alone so "that's" stays intact.
    """
    try:
        import wordninja
    except ImportError:
        return text

    try:
        import enchant
        _dict = enchant.Dict("en_US")
        def _is_word(w: str) -> bool:
            return _dict.check(w)
    except Exception:
        # Fallback: treat any token wordninja splits into ≥2 parts as merged
        _is_word = None

    tokens = text.split(" ")
    out = []
    for tok in tokens:
        # Only attempt segmentation on plain lowercase alpha tokens long enough
        # to plausibly contain two words (5+ chars), skipping contractions etc.
        if len(tok) >= 5 and tok.isalpha() and tok == tok.lower():
            if _is_word is not None and _is_word(tok):
                out.append(tok)  # already a valid single word
            else:
                parts = wordninja.split(tok)
                out.append(" ".join(parts) if len(parts) > 1 else tok)
        else:
            out.append(tok)
    return " ".join(out)


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
    text = re.sub(r'^([a-z])', lambda m: m.group(1).upper(), text)
    text = re.sub(r'([.!?]\s+)([a-z])', lambda m: m.group(1) + m.group(2).upper(), text)
    text = re.sub(r'\bi\b', 'I', text)
    return text


def _save_debug(tag: str, image: Image.Image, label: str) -> None:
    _DEBUG_DIR.mkdir(exist_ok=True)
    path = _DEBUG_DIR / f"{tag}_{label}.png"
    image.save(path)
    print(f"[DEBUG] saved {path}")


def _extract_lines(result, min_score: float) -> list[tuple]:
    """Normalise PaddleOCR result to [(bbox, text, score)] for both 2.x and 3.x APIs."""
    if not result:
        return []

    first = result[0]

    # 3.x: list of dicts with rec_texts / rec_scores / rec_polys
    if isinstance(first, dict):
        texts  = first.get("rec_texts")  or first.get("rec_text")   or []
        scores = first.get("rec_scores") or first.get("rec_score")  or []
        polys  = first.get("rec_polys")  or first.get("dt_polys")   or []
        return [
            (bbox, text, score)
            for bbox, text, score in zip(polys, texts, scores)
            if score >= min_score
        ]

    # 2.x: list of [bbox, (text, score)] or None per page
    if first is None:
        return []
    return [
        (line[0], line[1][0], line[1][1])
        for line in first
        if line[1][1] >= min_score
    ]


def _join_lines(lines: list[str]) -> str:
    result = ""
    for i, line in enumerate(lines):
        if i == 0:
            result = line
        elif result.endswith("-"):
            result = result[:-1] + line
        else:
            result = result + " " + line
    return result.strip()


def extract_text(image: Image.Image, ocr_config: dict | None = None) -> str:
    cfg = ocr_config or {}
    debug = cfg.get("debug", False)

    paddle_lang = str(cfg.get("paddle_lang") or "en").strip() or "en"
    if paddle_lang.lower() == "spanish":
        paddle_lang = "latin"
    reader = get_reader(paddle_lang)

    tag = datetime.now().strftime("%H%M%S_%f")[:9]
    if debug:
        _save_debug(tag, image, "1_raw")

    processed = _preprocess(image, cfg)

    if debug:
        _save_debug(tag, processed, "2_preprocessed")

    img_array = np.array(processed)

    # Call without version-specific kwargs — both 2.x and 3.x accept bare img
    result = reader.ocr(img_array)

    min_score = cfg.get("rec_score_threshold", _OCR_DEFAULTS["rec_score_threshold"])
    lines = _extract_lines(result, min_score)

    # Sort top-to-bottom so text reads in natural order across speech bubbles
    lines.sort(key=lambda ln: min(pt[1] for pt in ln[0]))

    texts = [ln[1] for ln in lines]
    text = _join_lines(texts)
    if cfg.get("fix_case", _OCR_DEFAULTS["fix_case"]):
        text = _fix_case(text)
    if cfg.get("word_segment", _OCR_DEFAULTS["word_segment"]):
        text = _segment_words(text)
    return text
