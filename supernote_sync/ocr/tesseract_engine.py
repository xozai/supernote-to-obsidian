"""Tesseract OCR engine implementation."""

from __future__ import annotations

import logging
from statistics import mean

import pytesseract
from pytesseract import Output

from supernote_sync.ingestion.note_parser import NotePage
from supernote_sync.ocr.engine_factory import BaseOcrEngine, OcrResult
from supernote_sync.ocr.preprocessor import preprocess

logger = logging.getLogger(__name__)


class TesseractEngine(BaseOcrEngine):
    """OCR engine backed by Tesseract via :mod:`pytesseract`.

    Args:
        threshold: Confidence threshold for flagging low-quality results.
        binary_path: Path to the ``tesseract`` binary.  If empty the
            system ``PATH`` is searched.
        lang: Tesseract language string (e.g. ``"eng"`` or ``"eng+fra"``).
    """

    def __init__(
        self,
        threshold: float = 0.70,
        binary_path: str = "",
        lang: str = "eng",
    ) -> None:
        """Initialise the Tesseract engine."""
        super().__init__(threshold=threshold)
        if binary_path:
            pytesseract.pytesseract.tesseract_cmd = binary_path
        self.lang = lang

    def run(self, page: NotePage) -> OcrResult:
        """Run Tesseract OCR on *page*.

        Uses :func:`pytesseract.image_to_data` to obtain per-word confidence
        scores, then computes an average confidence across all recognised words.

        Args:
            page: The note page to process.

        Returns:
            An :class:`~supernote_sync.ocr.engine_factory.OcrResult` with
            extracted text and average confidence.
        """
        logger.debug("Running Tesseract OCR on page %d", page.index)
        processed = preprocess(page.image)  # local var, do NOT mutate page.image
        data: dict[str, list[str | int]] = pytesseract.image_to_data(
            processed,
            lang=self.lang,
            output_type=Output.DICT,
        )

        words: list[str] = []
        confidences: list[float] = []

        for word, conf in zip(data["text"], data["conf"]):  # type: ignore[arg-type]
            conf_int = int(conf)  # type: ignore[arg-type]
            if conf_int >= 0 and str(word).strip():
                words.append(str(word))
                confidences.append(conf_int / 100.0)

        text = " ".join(words)
        avg_confidence = mean(confidences) if confidences else 0.0

        logger.debug(
            "Page %d: %d word(s), avg confidence=%.2f", page.index, len(words), avg_confidence
        )

        result = OcrResult(text=text, confidence=avg_confidence, page_index=page.index)
        return self._flag_low_confidence(result)
