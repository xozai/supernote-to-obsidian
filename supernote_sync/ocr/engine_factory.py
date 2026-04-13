"""OCR engine abstraction and factory."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from supernote_sync.ingestion.note_parser import NotePage

logger = logging.getLogger(__name__)


@dataclass
class OcrResult:
    """The result of running OCR on a single note page.

    Attributes:
        text: Extracted text content.
        confidence: Average word-level confidence in the range ``[0.0, 1.0]``.
        page_index: Zero-based index of the page within its source note.
        low_confidence: ``True`` when *confidence* is below the configured threshold.
    """

    text: str
    confidence: float
    page_index: int
    low_confidence: bool = False


class BaseOcrEngine(ABC):
    """Abstract base class for OCR engines.

    Subclasses must implement :meth:`run`.

    Args:
        threshold: Confidence threshold below which results are flagged.
    """

    def __init__(self, threshold: float = 0.70) -> None:
        """Initialise with a confidence threshold."""
        self.threshold = threshold

    @abstractmethod
    def run(self, page: NotePage) -> OcrResult:
        """Run OCR on *page* and return an :class:`OcrResult`.

        Args:
            page: The page to process.

        Returns:
            An :class:`OcrResult` with extracted text and confidence score.
        """

    def _flag_low_confidence(self, result: OcrResult) -> OcrResult:
        """Set :attr:`~OcrResult.low_confidence` if below threshold.

        Args:
            result: The result to inspect (modified in place).

        Returns:
            The same *result* with :attr:`~OcrResult.low_confidence` set.
        """
        result.low_confidence = result.confidence < self.threshold
        return result


def build_engine(cfg: dict[str, Any]) -> BaseOcrEngine:
    """Instantiate and return the configured OCR engine.

    Args:
        cfg: Top-level configuration dictionary (expects ``cfg["ocr"]``).

    Returns:
        A ready-to-use :class:`BaseOcrEngine` subclass.

    Raises:
        ValueError: If an unknown engine name is specified.
    """
    ocr_cfg: dict[str, Any] = cfg.get("ocr", {})
    engine_name: str = ocr_cfg.get("engine", "tesseract").lower()
    threshold: float = float(ocr_cfg.get("low_confidence_threshold", 0.70))

    if engine_name == "tesseract":
        from supernote_sync.ocr.tesseract_engine import TesseractEngine  # noqa: PLC0415

        tess_cfg: dict[str, Any] = ocr_cfg.get("tesseract", {})
        binary_path: str = tess_cfg.get("binary_path", "")
        lang: str = tess_cfg.get("lang", "eng")
        logger.info("Using TesseractEngine (lang=%s)", lang)
        return TesseractEngine(threshold=threshold, binary_path=binary_path, lang=lang)

    if engine_name == "google_vision":
        from supernote_sync.ocr.google_vision_engine import (  # noqa: PLC0415
            GoogleVisionEngine,
        )

        gv_cfg: dict[str, Any] = ocr_cfg.get("google_vision", {})
        credentials_path: str = gv_cfg.get("credentials_path", "")
        logger.info("Using GoogleVisionEngine")
        return GoogleVisionEngine(threshold=threshold, credentials_path=credentials_path)

    raise ValueError(
        f"Unknown OCR engine '{engine_name}'. Valid options are 'tesseract' and 'google_vision'."
    )
