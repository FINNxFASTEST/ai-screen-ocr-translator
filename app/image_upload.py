"""
Manual image upload helper for the page translation pipeline.

Opens a file-picker dialog and returns the selected file as a PIL Image
(RGB), ready to be passed directly into run_page_pipeline().
"""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox

from PIL import Image

_SUPPORTED = (
    ("Image files", "*.png *.jpg *.jpeg *.webp *.bmp *.tiff *.tif *.gif"),
    ("PNG", "*.png"),
    ("JPEG", "*.jpg *.jpeg"),
    ("All files", "*.*"),
)


def pick_image(root: tk.Tk) -> Image.Image | None:
    """
    Open a file dialog and return the selected image as a PIL RGB Image.

    Returns None if the user cancels or the file cannot be opened.
    """
    path = filedialog.askopenfilename(
        parent=root,
        title="Select manga page image to translate",
        filetypes=_SUPPORTED,
    )
    if not path:
        return None

    try:
        img = Image.open(path).convert("RGB")
        return img
    except Exception as e:
        messagebox.showerror(
            "Image Upload",
            f"Could not open image:\n{e}",
            parent=root,
        )
        return None
