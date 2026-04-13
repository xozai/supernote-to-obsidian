"""Tests for the Pipeline orchestrator."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from supernote_sync.ingestion.note_parser import NotePage
from supernote_sync.ocr.engine_factory import OcrResult


@pytest.fixture()
def note_file(tmp_path: Path) -> Path:
    """Create a dummy .note file."""
    f = tmp_path / "test_note.note"
    f.write_bytes(b"dummy note content")
    return f


@pytest.fixture()
def vault_path(tmp_path: Path) -> Path:
    """Return a temporary vault path."""
    v = tmp_path / "vault"
    v.mkdir()
    return v


@pytest.fixture()
def cfg(tmp_path: Path, vault_path: Path) -> dict:
    """Return a minimal pipeline configuration."""
    return {
        "supernote": {"sync_folder": str(tmp_path / "sync")},
        "ocr": {"engine": "tesseract", "low_confidence_threshold": 0.70},
        "obsidian": {
            "vault_path": str(vault_path),
            "notes_subfolder": "Notes",
            "attachments_subfolder": "attachments",
            "frontmatter": {"default_tags": ["test"], "extra_fields": {}},
            "git_sync": {"enabled": False},
        },
        "processing": {
            "deduplicate": False,
            "state_dir": str(tmp_path / "state"),
            "render_dpi": 200,
            "output_filename_pattern": "%Y-%m-%d_{note_name}",
        },
        "logging": {"level": "DEBUG"},
    }


def _make_blank_page(note_file: Path) -> NotePage:
    img = Image.new("RGB", (100, 100), color=(255, 255, 255))
    return NotePage(index=0, image=img, source_file=note_file)


class TestPipeline:
    """Tests for Pipeline.process_file()."""

    def test_process_file_writes_markdown(self, cfg: dict, note_file: Path, vault_path: Path) -> None:
        """process_file writes a markdown file to the vault."""
        from supernote_sync.pipeline import Pipeline

        page = _make_blank_page(note_file)
        result = OcrResult(text="Hello", confidence=0.90, page_index=0)

        with (
            patch(
                "supernote_sync.pipeline.NoteParser.extract_pages",
                return_value=[page],
            ),
            patch(
                "supernote_sync.ocr.tesseract_engine.pytesseract.image_to_data",
                return_value={"text": ["Hello"], "conf": [90]},
            ),
            patch(
                "supernote_sync.pipeline.Pipeline._is_blank_page",
                return_value=False,
            ),
        ):
            pipeline = Pipeline(cfg)
            success = pipeline.process_file(note_file)

        assert success is True
        # Verify at least one .md file was written inside the vault
        md_files = list((vault_path / "Notes").glob("*.md"))
        assert len(md_files) == 1

    def test_process_file_returns_false_when_dedup_skips(
        self, cfg: dict, note_file: Path
    ) -> None:
        """process_file returns False when dedup.already_processed=True."""
        cfg = dict(cfg)
        cfg["processing"] = dict(cfg["processing"])
        cfg["processing"]["deduplicate"] = True

        from supernote_sync.pipeline import Pipeline

        mock_dedup = MagicMock()
        mock_dedup.already_processed.return_value = True

        with patch("supernote_sync.utils.dedup.DedupCache", return_value=mock_dedup):
            pipeline = Pipeline(cfg)
            # Re-assign the internal dedup so our mock is used
            pipeline._dedup = mock_dedup
            result = pipeline.process_file(note_file)

        assert result is False

    def test_process_file_writes_failed_stub_on_exception(
        self, cfg: dict, note_file: Path, vault_path: Path
    ) -> None:
        """process_file writes FAILED stub and returns False when parser raises."""
        from supernote_sync.pipeline import Pipeline

        with patch(
            "supernote_sync.ingestion.note_parser.NoteParser.extract_pages",
            side_effect=RuntimeError("parse error"),
        ):
            pipeline = Pipeline(cfg)
            result = pipeline.process_file(note_file)

        assert result is False
        # Verify a FAILED stub was written somewhere under vault or note location
        failed_files = list(note_file.parent.rglob("*FAILED*.md")) + list(
            vault_path.rglob("*FAILED*.md")
        )
        assert len(failed_files) >= 1


def test_is_blank_page_returns_true_for_white_image(tmp_path: Path) -> None:
    """_is_blank_page returns True for a pure white image."""
    from PIL import Image
    from supernote_sync.ingestion.note_parser import NotePage
    from supernote_sync.pipeline import Pipeline

    cfg = {
        "supernote": {"sync_folder": str(tmp_path / "sync")},
        "ocr": {"engine": "tesseract", "low_confidence_threshold": 0.70},
        "obsidian": {
            "vault_path": str(tmp_path / "vault"),
            "notes_subfolder": "Notes",
            "attachments_subfolder": "attachments",
            "frontmatter": {"default_tags": [], "extra_fields": {}},
            "git_sync": {"enabled": False},
        },
        "processing": {
            "deduplicate": False,
            "state_dir": str(tmp_path / "state"),
            "render_dpi": 200,
            "output_filename_pattern": "%Y-%m-%d_{note_name}",
        },
        "logging": {"level": "DEBUG"},
    }
    pipeline = Pipeline(cfg)
    white_img = Image.new("RGB", (100, 100), (255, 255, 255))
    page = NotePage(index=0, image=white_img, source_file=tmp_path / "test.note")
    assert pipeline._is_blank_page(page) is True


def test_is_blank_page_returns_false_for_dark_pixels(tmp_path: Path) -> None:
    """_is_blank_page returns False when there are enough dark pixels."""
    from PIL import Image
    from supernote_sync.ingestion.note_parser import NotePage
    from supernote_sync.pipeline import Pipeline

    cfg = {
        "supernote": {"sync_folder": str(tmp_path / "sync")},
        "ocr": {"engine": "tesseract", "low_confidence_threshold": 0.70},
        "obsidian": {
            "vault_path": str(tmp_path / "vault"),
            "notes_subfolder": "Notes",
            "attachments_subfolder": "attachments",
            "frontmatter": {"default_tags": [], "extra_fields": {}},
            "git_sync": {"enabled": False},
        },
        "processing": {
            "deduplicate": False,
            "state_dir": str(tmp_path / "state"),
            "render_dpi": 200,
            "output_filename_pattern": "%Y-%m-%d_{note_name}",
        },
        "logging": {"level": "DEBUG"},
    }
    pipeline = Pipeline(cfg)
    # Draw a 20x10 black rectangle — 200 dark pixels out of 10000 = 2%, below the 99% white threshold
    img = Image.new("RGB", (100, 100), (255, 255, 255))
    for x in range(20):
        for y in range(10):
            img.putpixel((x, y), (0, 0, 0))
    page = NotePage(index=0, image=img, source_file=tmp_path / "test.note")
    assert pipeline._is_blank_page(page) is False


def test_process_file_returns_false_for_all_blank_pages(tmp_path: Path, mocker) -> None:
    """process_file returns False when all pages are blank."""
    from PIL import Image
    from supernote_sync.ingestion.note_parser import NotePage
    from supernote_sync.ocr.engine_factory import OcrResult
    from supernote_sync.pipeline import Pipeline

    cfg = {
        "supernote": {"sync_folder": str(tmp_path / "sync")},
        "ocr": {"engine": "tesseract", "low_confidence_threshold": 0.70},
        "obsidian": {
            "vault_path": str(tmp_path / "vault"),
            "notes_subfolder": "Notes",
            "attachments_subfolder": "attachments",
            "frontmatter": {"default_tags": [], "extra_fields": {}},
            "git_sync": {"enabled": False},
        },
        "processing": {
            "deduplicate": False,
            "state_dir": str(tmp_path / "state"),
            "render_dpi": 200,
            "output_filename_pattern": "%Y-%m-%d_{note_name}",
        },
        "logging": {"level": "DEBUG"},
    }
    pipeline = Pipeline(cfg)
    white_img = Image.new("RGB", (100, 100), (255, 255, 255))
    mocker.patch.object(pipeline.parser, "extract_pages", return_value=[
        NotePage(index=0, image=white_img, source_file=tmp_path / "t.note")
    ])
    mocker.patch.object(pipeline.ocr, "run", return_value=OcrResult(text="", confidence=0.0, page_index=0))
    mocker.patch.object(pipeline.writer, "write")
    note = tmp_path / "blank.note"
    note.write_bytes(b"fake")
    result = pipeline.process_file(note)
    assert result is False
