from __future__ import annotations

from PIL import Image, ImageEnhance, ImageFilter


def preprocess(image: Image.Image) -> Image.Image:
    """Prepare a Supernote page image for Tesseract OCR.

    Steps: grayscale → contrast boost → sharpen → binarize at threshold 180.

    Args:
        image: Source PIL image (any mode).
    Returns:
        Processed grayscale PIL image ready for Tesseract.
    """
    gray = image.convert("L")
    enhanced = ImageEnhance.Contrast(gray).enhance(2.0)
    sharpened = enhanced.filter(ImageFilter.SHARPEN)
    binarized = sharpened.point(lambda px: 255 if px >= 180 else 0)
    return binarized
