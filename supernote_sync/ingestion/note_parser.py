"""Parse Supernote .note files into a list of rasterised page images."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

logger = logging.getLogger(__name__)

# Default page dimensions for the Supernote Manta (1404 × 1872 px at 226 dpi)
_STUB_WIDTH = 1404
_STUB_HEIGHT = 1872


@dataclass
class NotePage:
    """A single rasterised page from a .note file.

    Attributes:
        index: Zero-based page index within the source note.
        image: PIL :class:`~PIL.Image.Image` representing the rendered page.
        source_file: Path to the originating ``.note`` file.
        metadata: Optional page-level metadata extracted from the notebook.
    """

    index: int
    image: Image.Image
    source_file: Path
    metadata: dict[str, Any] = field(default_factory=dict)


class NoteParser:
    """Parse a Supernote ``.note`` file into :class:`NotePage` objects.

    Args:
        dpi: Resolution (dots per inch) used when rasterising pages.
    """

    def __init__(self, dpi: int = 200) -> None:
        """Initialise the parser with a render DPI."""
        self.dpi = dpi

    def extract_pages(self, note_path: Path) -> list[NotePage]:
        """Extract all pages from *note_path* as PIL images.

        Attempts to use ``supernote_tool`` if available.  Falls back to a
        single blank white stub page when the library is not installed or the
        file cannot be parsed.

        Args:
            note_path: Path to the ``.note`` file to parse.

        Returns:
            List of :class:`NotePage` instances, one per page.
        """
        try:
            import supernote_tool  # type: ignore[import]

            logger.debug("Parsing %s with supernote_tool", note_path)
            notebook = supernote_tool.load_notebook(str(note_path))
            pages: list[NotePage] = []
            for idx, page in enumerate(notebook.pages):
                try:
                    img: Image.Image = page.to_image(dpi=self.dpi)
                except TypeError:
                    logger.warning("to_image() does not accept dpi kwarg — retrying without it")
                    img = page.to_image()  # type: ignore[call-arg]
                pages.append(NotePage(index=idx, image=img, source_file=note_path))
            logger.info("Extracted %d page(s) from %s", len(pages), note_path.name)
            return pages
        except ImportError:
            logger.warning(
                "supernote_tool is not installed — falling back to stub extraction for %s",
                note_path,
            )
            return self._stub_extract(note_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "supernote_tool failed to parse %s (%s) — falling back to stub extraction",
                note_path,
                exc,
            )
            return self._stub_extract(note_path)

    def _stub_extract(self, note_path: Path) -> list[NotePage]:
        """Return a single blank white page as a fallback.

        Args:
            note_path: Path to the originating ``.note`` file.

        Returns:
            A one-element list containing a blank :class:`NotePage`.
        """
        img = Image.new("RGB", (_STUB_WIDTH, _STUB_HEIGHT), color=(255, 255, 255))
        return [NotePage(index=0, image=img, source_file=note_path)]
