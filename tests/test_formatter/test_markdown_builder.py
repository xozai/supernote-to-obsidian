"""Tests for MarkdownBuilder and document types."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from supernote_sync.formatter.markdown_builder import (
    FailureDocument,
    MarkdownBuilder,
    NoteDocument,
)
from supernote_sync.ingestion.note_parser import NotePage
from supernote_sync.ocr.engine_factory import OcrResult


@pytest.fixture()
def builder(tmp_path: Path) -> MarkdownBuilder:
    """Return a MarkdownBuilder with minimal config."""
    notes_dir = tmp_path / "vault" / "Supernote"
    notes_dir.mkdir(parents=True)
    cfg = {
        "obsidian": {
            "frontmatter": {
                "default_tags": ["supernote", "handwritten"],
                "extra_fields": {"device": "Manta"},
            }
        },
        "processing": {"output_filename_pattern": "%Y-%m-%d_{note_name}"},
    }
    return MarkdownBuilder(cfg=cfg, notes_dir=notes_dir)


@pytest.fixture()
def sample_page(tmp_path: Path) -> NotePage:
    """Return a simple NotePage."""
    img = Image.new("RGB", (100, 100), color=(255, 255, 255))
    return NotePage(index=0, image=img, source_file=tmp_path / "my_note.note")


@pytest.fixture()
def good_result() -> OcrResult:
    """Return a high-confidence OcrResult."""
    return OcrResult(text="Hello world", confidence=0.90, page_index=0, low_confidence=False)


@pytest.fixture()
def low_conf_result() -> OcrResult:
    """Return a low-confidence OcrResult."""
    return OcrResult(text="blurry text", confidence=0.40, page_index=0, low_confidence=True)


class TestNoteDocument:
    """Tests for NoteDocument produced by MarkdownBuilder."""

    def test_build_returns_note_document(
        self,
        builder: MarkdownBuilder,
        sample_page: NotePage,
        good_result: OcrResult,
    ) -> None:
        """build() returns a NoteDocument."""
        doc = builder.build(sample_page.source_file, [sample_page], [good_result])
        assert isinstance(doc, NoteDocument)

    def test_output_path_contains_note_stem(
        self,
        builder: MarkdownBuilder,
        sample_page: NotePage,
        good_result: OcrResult,
    ) -> None:
        """output_path filename contains the note stem."""
        doc = builder.build(sample_page.source_file, [sample_page], [good_result])
        assert "my_note" in doc.output_path.name

    def test_output_path_ends_with_md(
        self,
        builder: MarkdownBuilder,
        sample_page: NotePage,
        good_result: OcrResult,
    ) -> None:
        """output_path ends with .md."""
        doc = builder.build(sample_page.source_file, [sample_page], [good_result])
        assert doc.output_path.suffix == ".md"

    def test_one_attachment_per_page(
        self,
        builder: MarkdownBuilder,
        sample_page: NotePage,
        good_result: OcrResult,
    ) -> None:
        """One attachment is created per page."""
        img2 = Image.new("RGB", (100, 100))
        page2 = NotePage(index=1, image=img2, source_file=sample_page.source_file)
        result2 = OcrResult(text="page two", confidence=0.85, page_index=1)
        doc = builder.build(sample_page.source_file, [sample_page, page2], [good_result, result2])
        assert len(doc.attachments) == 2

    def test_rendered_output_contains_frontmatter_tags(
        self,
        builder: MarkdownBuilder,
        sample_page: NotePage,
        good_result: OcrResult,
    ) -> None:
        """Rendered output includes frontmatter tags."""
        doc = builder.build(sample_page.source_file, [sample_page], [good_result])
        rendered = doc.render()
        assert "supernote" in rendered
        assert "handwritten" in rendered

    def test_rendered_output_contains_ocr_text(
        self,
        builder: MarkdownBuilder,
        sample_page: NotePage,
        good_result: OcrResult,
    ) -> None:
        """Rendered output includes the OCR text."""
        doc = builder.build(sample_page.source_file, [sample_page], [good_result])
        rendered = doc.render()
        assert "Hello world" in rendered

    def test_low_confidence_marker_present(
        self,
        builder: MarkdownBuilder,
        sample_page: NotePage,
        low_conf_result: OcrResult,
    ) -> None:
        """OCR_LOW_CONFIDENCE marker is present when result.low_confidence=True."""
        doc = builder.build(sample_page.source_file, [sample_page], [low_conf_result])
        rendered = doc.render()
        assert "OCR_LOW_CONFIDENCE" in rendered

    def test_obsidian_image_embed_present(
        self,
        builder: MarkdownBuilder,
        sample_page: NotePage,
        good_result: OcrResult,
    ) -> None:
        """Rendered output contains Obsidian image embed syntax '![[...'."""
        doc = builder.build(sample_page.source_file, [sample_page], [good_result])
        rendered = doc.render()
        assert "![[" in rendered


class TestFailureDocument:
    """Tests for FailureDocument."""

    @pytest.fixture()
    def failure_doc(self, tmp_path: Path) -> FailureDocument:
        """Return a FailureDocument."""
        source = tmp_path / "bad_note.note"
        source.write_bytes(b"\x00")
        return FailureDocument(source_path=source)

    def test_render_contains_ocr_failed(self, failure_doc: FailureDocument) -> None:
        """render() contains OCR_FAILED marker."""
        assert "OCR_FAILED" in failure_doc.render()

    def test_output_path_contains_failed(self, failure_doc: FailureDocument) -> None:
        """output_path contains 'FAILED'."""
        assert "FAILED" in failure_doc.output_path.name

    def test_attachments_is_empty(self, failure_doc: FailureDocument) -> None:
        """FailureDocument has an empty attachments list."""
        assert failure_doc.attachments == []
