from __future__ import annotations
import pytest
from PIL import Image
from supernote_sync.ocr.preprocessor import preprocess


def make_white_image(w: int = 100, h: int = 100) -> Image.Image:
    return Image.new("RGB", (w, h), color=(255, 255, 255))


def make_black_image(w: int = 100, h: int = 100) -> Image.Image:
    return Image.new("RGB", (w, h), color=(0, 0, 0))


def test_preprocess_returns_grayscale_mode():
    result = preprocess(make_white_image())
    assert result.mode in ("L", "1")


def test_preprocess_preserves_dimensions():
    img = make_white_image(200, 300)
    result = preprocess(img)
    assert result.size == (200, 300)


def test_preprocess_white_input_stays_white():
    result = preprocess(make_white_image())
    pixels = list(result.getdata())
    assert all(p == 255 for p in pixels)


def test_preprocess_black_input_stays_black():
    result = preprocess(make_black_image())
    pixels = list(result.getdata())
    assert all(p == 0 for p in pixels)
