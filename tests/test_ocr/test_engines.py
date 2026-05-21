"""Tests for OCR engine factory and engines."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from supernote_sync.ingestion.note_parser import NotePage
from supernote_sync.ocr.engine_factory import OcrResult, build_engine
from supernote_sync.ocr.tesseract_engine import TesseractEngine


@pytest.fixture()
def blank_page() -> NotePage:
    """Return a blank white NotePage."""
    img = Image.new("RGB", (100, 100), color=(255, 255, 255))
    return NotePage(index=0, image=img, source_file=Path("test.note"))


@pytest.fixture()
def tess_cfg() -> dict:
    """Return minimal config selecting tesseract."""
    return {"ocr": {"engine": "tesseract", "low_confidence_threshold": 0.70}}


@pytest.fixture()
def gv_cfg() -> dict:
    """Return minimal config selecting google_vision."""
    return {"ocr": {"engine": "google_vision", "low_confidence_threshold": 0.70}}


class TestBuildEngine:
    """Tests for the engine factory."""

    def test_build_returns_tesseract_engine(self, tess_cfg: dict) -> None:
        """build_engine returns TesseractEngine for engine='tesseract'."""
        engine = build_engine(tess_cfg)
        assert isinstance(engine, TesseractEngine)

    def test_build_raises_for_unknown_engine(self) -> None:
        """build_engine raises ValueError for an unknown engine name."""
        cfg = {"ocr": {"engine": "magic_ocr"}}
        with pytest.raises(ValueError, match="magic_ocr"):
            build_engine(cfg)


class TestTesseractEngine:
    """Tests for TesseractEngine."""

    def _make_tess_data(
        self, words: list[str], confs: list[int]
    ) -> dict:
        """Build a fake pytesseract.image_to_data output dict."""
        return {"text": words, "conf": confs}

    def test_run_returns_ocr_result(self, blank_page: NotePage) -> None:
        """TesseractEngine.run returns an OcrResult."""
        engine = TesseractEngine(threshold=0.70)
        fake_data = self._make_tess_data(["Hello", "world"], [85, 90])
        tess_patch = "supernote_sync.ocr.tesseract_engine.pytesseract.image_to_data"
        with patch(tess_patch, return_value=fake_data):
            result = engine.run(blank_page)
        assert isinstance(result, OcrResult)

    def test_run_extracts_correct_text(self, blank_page: NotePage) -> None:
        """TesseractEngine joins words into text."""
        engine = TesseractEngine(threshold=0.70)
        fake_data = self._make_tess_data(["Hello", "world"], [85, 90])
        tess_patch = "supernote_sync.ocr.tesseract_engine.pytesseract.image_to_data"
        with patch(tess_patch, return_value=fake_data):
            result = engine.run(blank_page)
        assert "Hello" in result.text
        assert "world" in result.text

    def test_run_computes_correct_confidence(self, blank_page: NotePage) -> None:
        """TesseractEngine computes average confidence correctly."""
        engine = TesseractEngine(threshold=0.70)
        fake_data = self._make_tess_data(["Hello", "world"], [80, 100])
        tess_patch = "supernote_sync.ocr.tesseract_engine.pytesseract.image_to_data"
        with patch(tess_patch, return_value=fake_data):
            result = engine.run(blank_page)
        assert abs(result.confidence - 0.90) < 0.01

    def test_run_sets_low_confidence_true_when_conf_is_low(self, blank_page: NotePage) -> None:
        """TesseractEngine flags low_confidence=True when confidence < threshold."""
        engine = TesseractEngine(threshold=0.70)
        fake_data = self._make_tess_data(["bad"], [30])
        tess_patch = "supernote_sync.ocr.tesseract_engine.pytesseract.image_to_data"
        with patch(tess_patch, return_value=fake_data):
            result = engine.run(blank_page)
        assert result.low_confidence is True

    def test_run_returns_zero_confidence_for_no_words(self, blank_page: NotePage) -> None:
        """TesseractEngine returns confidence=0.0 when there are no recognised words."""
        engine = TesseractEngine(threshold=0.70)
        fake_data = self._make_tess_data(["", " "], [-1, -1])
        tess_patch = "supernote_sync.ocr.tesseract_engine.pytesseract.image_to_data"
        with patch(tess_patch, return_value=fake_data):
            result = engine.run(blank_page)
        assert result.confidence == 0.0
        assert result.low_confidence is True


class TestGoogleVisionEngine:
    """Tests for GoogleVisionEngine."""

    def test_run_raises_on_api_error(self, blank_page: NotePage) -> None:
        """GoogleVisionEngine.run raises RuntimeError when API returns an error message."""
        from supernote_sync.ocr.google_vision_engine import GoogleVisionEngine

        engine = GoogleVisionEngine(threshold=0.70)

        # Mock the google.cloud.vision module
        mock_response = MagicMock()
        mock_response.error.message = "API quota exceeded"

        mock_client = MagicMock()
        mock_client.document_text_detection.return_value = mock_response
        engine._client = mock_client

        mock_vision = MagicMock()
        mock_vision.Image = MagicMock(return_value=MagicMock())

        with patch.dict("sys.modules", {"google.cloud.vision": mock_vision}):
            with pytest.raises(RuntimeError, match="API quota exceeded"):
                engine.run(blank_page)

    def test_get_client_raises_for_missing_credentials_file(self) -> None:
        from supernote_sync.ocr.google_vision_engine import GoogleVisionEngine
        engine = GoogleVisionEngine(credentials_path="/nonexistent/creds.json")
        with pytest.raises(ValueError) as exc_info:
            engine._get_client()
        assert "credentials file not found" in str(exc_info.value).lower()

    def test_get_client_does_not_raise_when_credentials_path_is_empty(self) -> None:
        """Empty path uses Application Default Credentials — skip the file check."""
        import sys
        from unittest.mock import MagicMock, patch

        from supernote_sync.ocr.google_vision_engine import GoogleVisionEngine
        engine = GoogleVisionEngine(credentials_path="")
        mock_vision = MagicMock()
        mocks = {
            "google": MagicMock(), "google.cloud": MagicMock(),
            "google.cloud.vision": mock_vision,
            "google.oauth2": MagicMock(), "google.oauth2.service_account": MagicMock(),
        }
        with patch.dict(sys.modules, mocks):
            try:
                engine._get_client()
            except ValueError as e:
                pytest.fail(f"Unexpected ValueError: {e}")
            except Exception:
                pass  # mock-induced errors are acceptable
