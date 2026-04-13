"""Google Cloud Vision OCR engine implementation."""

from __future__ import annotations

import io
import logging
from statistics import mean

from PIL import Image

from supernote_sync.ingestion.note_parser import NotePage
from supernote_sync.ocr.engine_factory import BaseOcrEngine, OcrResult

logger = logging.getLogger(__name__)


class GoogleVisionEngine(BaseOcrEngine):
    """OCR engine backed by the Google Cloud Vision API.

    Args:
        threshold: Confidence threshold for flagging low-quality results.
        credentials_path: Path to a Google Cloud service-account JSON key
            file.  When empty, application default credentials are used.
    """

    def __init__(self, threshold: float = 0.70, credentials_path: str = "") -> None:
        """Initialise the Google Vision engine."""
        super().__init__(threshold=threshold)
        self.credentials_path = credentials_path
        self._client: object | None = None

    def _get_client(self) -> object:
        """Return a (lazily created) Vision API client.

        Returns:
            A :class:`google.cloud.vision.ImageAnnotatorClient` instance.
        """
        if self._client is None:
            from google.cloud import vision  # type: ignore[import]
            from google.oauth2 import service_account  # type: ignore[import]

            if self.credentials_path:
                creds = service_account.Credentials.from_service_account_file(
                    self.credentials_path
                )
                self._client = vision.ImageAnnotatorClient(credentials=creds)
            else:
                self._client = vision.ImageAnnotatorClient()
        return self._client

    def run(self, page: NotePage) -> OcrResult:
        """Run Google Cloud Vision document text detection on *page*.

        Args:
            page: The note page to process.

        Returns:
            An :class:`~supernote_sync.ocr.engine_factory.OcrResult` with
            extracted text and average confidence.

        Raises:
            RuntimeError: If the Vision API returns an error message.
        """
        from google.cloud import vision  # type: ignore[import]

        logger.debug("Running Google Vision OCR on page %d", page.index)

        # Convert PIL image to PNG bytes
        buf = io.BytesIO()
        img: Image.Image = page.image
        img.save(buf, format="PNG")
        image_bytes = buf.getvalue()

        client = self._get_client()
        vision_image = vision.Image(content=image_bytes)  # type: ignore[attr-defined]
        response = client.document_text_detection(image=vision_image)  # type: ignore[union-attr]

        if response.error.message:
            raise RuntimeError(
                f"Google Vision API error on page {page.index}: {response.error.message}"
            )

        annotation = response.full_text_annotation
        text: str = annotation.text if annotation else ""

        # Collect per-word confidence values
        word_confidences: list[float] = []
        for page_ann in annotation.pages:
            for block in page_ann.blocks:
                for paragraph in block.paragraphs:
                    for word in paragraph.words:
                        conf = word.confidence
                        if conf is not None:
                            word_confidences.append(float(conf))

        avg_confidence = mean(word_confidences) if word_confidences else 0.0

        logger.debug(
            "Page %d: avg confidence=%.2f", page.index, avg_confidence
        )

        result = OcrResult(text=text, confidence=avg_confidence, page_index=page.index)
        return self._flag_low_confidence(result)
