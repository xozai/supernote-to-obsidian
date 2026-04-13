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

    def test_fallback_when_supernote_tool_missing(
        self, parser: NoteParser, fake_note: Path
    ) -> None:
        """extract_pages falls back to stub when supernote_tool is not importable."""
        with patch.dict(sys.modules, {"supernote_tool": None}):
            pages = parser.extract_pages(fake_note)
        assert len(pages) == 1
        assert isinstance(pages[0], NotePage)
        assert isinstance(pages[0].image, Image.Image)

    def test_extract_pages_uses_supernote_tool_when_available(
        self, parser: NoteParser, fake_note: Path
    ) -> None:
        """extract_pages uses supernote_tool when present."""
        mock_img = Image.new("RGB", (100, 100), color=(200, 200, 200))
        mock_page = MagicMock()
        mock_page.to_image.return_value = mock_img

        mock_notebook = MagicMock()
        mock_notebook.pages = [mock_page]

        mock_supernote_tool = MagicMock()
        mock_supernote_tool.load_notebook.return_value = mock_notebook

        with patch.dict(sys.modules, {"supernote_tool": mock_supernote_tool}):
            pages = parser.extract_pages(fake_note)

        assert len(pages) == 1
        assert pages[0].image is mock_img
        mock_page.to_image.assert_called_once_with(dpi=200)
