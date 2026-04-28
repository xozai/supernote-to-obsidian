"""Build Obsidian Markdown documents from OCR results."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import frontmatter

from supernote_sync.ingestion.note_parser import NotePage
from supernote_sync.ocr.engine_factory import OcrResult

logger = logging.getLogger(__name__)

_LOW_CONFIDENCE_MARKER = "<!-- OCR_LOW_CONFIDENCE -->"
_FAILURE_MARKER = "<!-- OCR_FAILED -->"


def _dedupe_adjacent_lines(text: str) -> str:
    """Remove consecutive identical lines from OCR text.

    Tesseract sometimes repeats the same line when recognition confidence is
    borderline.  This collapses those runs without removing intentional
    duplicate content that is separated by a blank line.

    Args:
        text: Raw OCR text string.

    Returns:
        Text with consecutive identical lines collapsed to one.
    """
    lines = text.split("\n")
    deduped = [line for i, line in enumerate(lines) if i == 0 or line != lines[i - 1]]
    return "\n".join(deduped)


class Document(Protocol):
    """Protocol implemented by all document types produced by the formatter."""

    output_path: Path
    attachments: list[tuple[str, bytes]]

    def render(self) -> str:
        """Serialise the document to a Markdown string."""
        ...


@dataclass
class NoteDocument:
    """A successfully converted note ready to be written to the vault.

    Attributes:
        output_path: Full path (inside the vault) where the note will be saved.
        frontmatter_data: Key-value pairs written as YAML frontmatter.
        body: Markdown body text (excluding frontmatter).
        attachments: List of ``(filename, bytes)`` tuples for page images.
    """

    output_path: Path
    frontmatter_data: dict[str, Any]
    body: str
    attachments: list[tuple[str, bytes]] = field(default_factory=list)

    def render(self) -> str:
        """Return the complete Markdown string including YAML frontmatter.

        Returns:
            A string starting with ``---`` frontmatter followed by the body.
        """
        post = frontmatter.Post(self.body, **self.frontmatter_data)
        return str(frontmatter.dumps(post))


@dataclass
class FailureDocument:
    """A stub document written when a note could not be converted.

    Attributes:
        source_path: Path to the original ``.note`` file that failed.
    """

    source_path: Path

    @property
    def output_path(self) -> Path:
        """Return the output path with a ``_FAILED`` suffix."""
        return self.source_path.with_name(f"{self.source_path.stem}_FAILED.md")

    @property
    def attachments(self) -> list[tuple[str, bytes]]:
        """Return an empty attachment list (failures produce no images)."""
        return []

    def render(self) -> str:
        """Return a minimal stub Markdown document.

        Returns:
            A short Markdown string containing the :data:`_FAILURE_MARKER` comment.
        """
        return (
            f"---\nstatus: failed\n---\n\n"
            f"{_FAILURE_MARKER}\n\n"
            f"OCR processing failed for `{self.source_path.name}`.\n"
        )


class MarkdownBuilder:
    """Convert parsed note pages and OCR results into :class:`NoteDocument` objects.

    Args:
        cfg: Top-level configuration dictionary.
        notes_dir: Directory inside the vault where notes are saved.
    """

    def __init__(self, cfg: dict[str, Any], notes_dir: Path) -> None:
        """Initialise the builder."""
        self.cfg = cfg
        self.notes_dir = notes_dir
        obs_cfg: dict[str, Any] = cfg.get("obsidian", {})
        fm_cfg: dict[str, Any] = obs_cfg.get("frontmatter", {})
        self.default_tags: list[str] = fm_cfg.get("default_tags", [])
        self.extra_fields: dict[str, Any] = fm_cfg.get("extra_fields", {})
        proc_cfg: dict[str, Any] = cfg.get("processing", {})
        self.filename_pattern: str = proc_cfg.get(
            "output_filename_pattern", "%Y-%m-%d_{note_name}"
        )

    def build(
        self,
        note_path: Path,
        pages: list[NotePage],
        ocr_results: list[OcrResult],
        update_in_place: bool = False,
    ) -> NoteDocument:
        """Build a :class:`NoteDocument` from pages and their OCR results.

        For each page an attachment PNG is generated and an Obsidian image
        embed (``![[filename]]``) is inserted into the body.

        When *update_in_place* is ``True`` and a note whose filename contains
        the same stem already exists in :attr:`notes_dir`, that file's path is
        reused instead of generating a new dated filename.  This enables
        idempotent forced reruns.

        Args:
            note_path: Path to the source ``.note`` file.
            pages: Parsed note pages.
            ocr_results: OCR results aligned with *pages* by index.
            update_in_place: If ``True``, overwrite an existing note with the
                same stem rather than creating a new dated file.

        Returns:
            A :class:`NoteDocument` ready to be handed to the vault writer.
        """
        now = datetime.now(tz=timezone.utc)
        stem = note_path.stem

        # Resolve output path — reuse existing file when updating in place.
        output_path: Path
        if update_in_place:
            existing = list(self.notes_dir.glob(f"*{stem}*.md"))
            if existing:
                output_path = existing[0]
                logger.info("Updating existing note in place: %s", output_path.name)
            else:
                filename_base = now.strftime(self.filename_pattern).replace("{note_name}", stem)
                output_path = self.notes_dir / f"{filename_base}.md"
        else:
            filename_base = now.strftime(self.filename_pattern).replace("{note_name}", stem)
            output_path = self.notes_dir / f"{filename_base}.md"

        # Derive note date from file modification time; fall back to now.
        try:
            note_date = datetime.fromtimestamp(
                note_path.stat().st_mtime, tz=timezone.utc
            ).date().isoformat()
        except OSError:
            note_date = now.date().isoformat()

        attachments: list[tuple[str, bytes]] = []
        body_parts: list[str] = []

        for page, result in zip(pages, ocr_results):
            # Render page image to PNG bytes
            img_name = f"{stem}_page{page.index:03d}.png"
            buf = io.BytesIO()
            page.image.save(buf, format="PNG")
            attachments.append((img_name, buf.getvalue()))

            # Deduplicate adjacent identical lines then apply confidence marker.
            text_block = _dedupe_adjacent_lines(result.text)
            if result.low_confidence:
                text_block = f"{_LOW_CONFIDENCE_MARKER}\n{text_block}"

            body_parts.append(text_block)
            body_parts.append(f"![[{img_name}]]")
            body_parts.append("")  # blank line between pages

        body = "\n".join(body_parts).strip()

        fm_data: dict[str, Any] = {
            "title": stem,
            "date": note_date,
            "created": now.isoformat(),
            "source": "supernote",
            "original_file": str(note_path),
            "tags": list(self.default_tags),
            **self.extra_fields,
        }

        logger.info(
            "Built NoteDocument: %s (%d pages, %d attachment(s))",
            output_path.name,
            len(pages),
            len(attachments),
        )
        return NoteDocument(
            output_path=output_path,
            frontmatter_data=fm_data,
            body=body,
            attachments=attachments,
        )
