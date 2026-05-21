"""Tests for NoteParser."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from supernote_sync.ingestion.note_parser import NotePage, NoteParser


@pytest.fixture()
def parser() -> NoteParser:
    """Return a NoteParser with default DPI."""
    return NoteParser(dpi=200)


@pytest.fixture()
def fake_note(tmp_path: Path) -> Path:
    """Create a dummy .note file."""
    p = tmp_path / "test_note.note"
    p.write_bytes(b"\x00" * 16)
    return p


class TestStubExtract:
    """Tests for the fallback stub extraction."""

    def test_stub_extract_returns_one_page(self, parser: NoteParser, fake_note: Path) -> None:
        """_stub_extract returns exactly one NotePage."""
        pages = parser._stub_extract(fake_note)
        assert len(pages) == 1

    def test_stub_extract_returns_note_page(self, parser: NoteParser, fake_note: Path) -> None:
        """_stub_extract returns a NotePage instance."""
        pages = parser._stub_extract(fake_note)
        assert isinstance(pages[0], NotePage)

    def test_stub_extract_contains_pil_image(self, parser: NoteParser, fake_note: Path) -> None:
        """_stub_extract page contains a PIL Image."""
        pages = parser._stub_extract(fake_note)
        assert isinstance(pages[0].image, Image.Image)

    def test_stub_extract_image_is_white(self, parser: NoteParser, fake_note: Path) -> None:
        """Stub image is white (all pixels are 255)."""
        pages = parser._stub_extract(fake_note)
        img = pages[0].image
        pixel = img.getpixel((0, 0))
        assert pixel == (255, 255, 255)


class TestExtractPages:
    """Tests for extract_pages behaviour."""

    def test_fallback_when_supernotelib_missing(
        self, parser: NoteParser, fake_note: Path
    ) -> None:
        """extract_pages falls back to stub when supernotelib is not importable."""
        with patch.dict(sys.modules, {"supernotelib": None, "supernotelib.converter": None}):
            pages = parser.extract_pages(fake_note)
        assert len(pages) == 1
        assert isinstance(pages[0], NotePage)
        assert isinstance(pages[0].image, Image.Image)

    def test_extract_pages_uses_supernotelib_when_available(
        self, parser: NoteParser, fake_note: Path
    ) -> None:
        """extract_pages uses supernotelib when present."""
        mock_img = Image.new("RGB", (100, 100), color=(200, 200, 200))

        mock_converter = MagicMock()
        mock_converter.convert.return_value = mock_img

        mock_notebook = MagicMock()
        mock_notebook.get_total_pages.return_value = 1

        mock_supernotelib = MagicMock()
        mock_supernotelib.load_notebook.return_value = mock_notebook
        # `import supernotelib.converter as snconverter` resolves via attribute access on the
        # supernotelib mock, so configure ImageConverter on that attribute.
        mock_supernotelib.converter.ImageConverter.return_value = mock_converter

        with patch.dict(
            sys.modules,
            {
                "supernotelib": mock_supernotelib,
                "supernotelib.converter": mock_supernotelib.converter,
            },
        ):
            pages = parser.extract_pages(fake_note)

        assert len(pages) == 1
        assert pages[0].image is mock_img
        mock_converter.convert.assert_called_once_with(0)
